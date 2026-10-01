// launcher.cpp -- the launcher window.
#include "launcher.h"

#include <wx/artprov.h>
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/dirdlg.h>
#include <wx/filename.h>
#include <wx/hyperlink.h>
#include <wx/menu.h>
#include <wx/msgdlg.h>
#include <wx/panel.h>
#include <wx/radiobut.h>
#include <wx/settings.h>
#include <wx/simplebook.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/statbmp.h>
#include <wx/statbox.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>

#ifdef __WXMSW__
#include <wx/msw/wrapcctl.h>
#include <shellapi.h>
#endif

#include "icon.h"
#include "settings.h"
#include "version.h"

const char* const APP_TITLE = "Test Drive";

namespace {

const char* const WEBSITE = "https://kkania.com";
const char* const SOURCE = "https://github.com/kylofon/test-drive-sdl3";
const char* const SUPPORT = "https://buymeacoffee.com/krzysztofkania";

const int ID_KEY_BINDINGS = wxID_HIGHEST + 1, ID_ABOUT = wxID_HIGHEST + 2;
enum Page { PAGE_MAIN, PAGE_KEYS };

const int MIN_SCALE = 1, MAX_SCALE = 6, DEFAULT_SCALE = 3;
const int DEFAULT_FRAME_RATE = 8;
const char* const MONITORS[] = {"green", "amber", "white"};

#ifdef __WXMSW__
HRESULT CALLBACK AboutCallback(HWND hwnd, UINT msg, WPARAM, LPARAM lp, LONG_PTR) {
    if (msg == TDN_HYPERLINK_CLICKED)
        ShellExecuteW(hwnd, L"open", reinterpret_cast<LPCWSTR>(lp), nullptr, nullptr, SW_SHOWNORMAL);
    return S_OK;
}
#else
// A label and a link on one line, for the portable About box.
void AddLink(wxWindow* parent, wxSizer* sizer, const wxString& label, const wxString& text, const wxString& url) {
    auto* line = new wxBoxSizer(wxHORIZONTAL);
    line->Add(new wxStaticText(parent, wxID_ANY, label + " "), 0, wxALIGN_CENTER_VERTICAL);
    line->Add(new wxHyperlinkCtrl(parent, wxID_ANY, text, url), 0, wxALIGN_CENTER_VERTICAL);
    sizer->Add(line);
}
#endif

wxString FolderKey(Family family) { return family == Family::Dos ? "GameFolderDOS" : "GameFolderAmiga"; }

wxStaticText* GreyText(wxWindow* parent, const wxString& text = wxEmptyString) {
    auto* label = new wxStaticText(parent, wxID_ANY, text);
    label->SetForegroundColour(wxSystemSettings::GetColour(wxSYS_COLOUR_GRAYTEXT));
    return label;
}

}  // namespace

LauncherFrame::LauncherFrame()
    : wxFrame(nullptr, wxID_ANY, APP_TITLE, wxDefaultPosition, wxDefaultSize,
              wxDEFAULT_FRAME_STYLE & ~(wxRESIZE_BORDER | wxMAXIMIZE_BOX)) {
    SetIcons(AppIcons());
    topmost_ = settings::GetInt("Preferences", "AlwaysOnTop", 0) != 0;
    if (topmost_) SetWindowStyleFlag(GetWindowStyleFlag() | wxSTAY_ON_TOP);
    bindings_ = keys::Load();
    edited_ = bindings_;

    // The launcher and, in its place while it is open, Key Bindings.
    book_ = new wxSimplebook(this);
    book_->AddPage(CreateMainPage(book_), "Game");
    book_->AddPage(CreateKeysPage(book_), "Key Bindings");
    auto* all = new wxBoxSizer(wxVERTICAL);
    all->Add(book_, 1, wxEXPAND);
    SetSizer(all);
    CreateMenus();

    // Settings from the last run.
    for (Family f : {Family::Dos, Family::Amiga}) FolderOf(f) = settings::GetString("Launcher", FolderKey(f), "");
    scale_->SetSelection(
        wxMax(MIN_SCALE, wxMin(MAX_SCALE, settings::GetInt("Launcher", "Scale", DEFAULT_SCALE))) - MIN_SCALE);
    frameRate_->SetValue(settings::GetInt("Launcher", "FrameRate", DEFAULT_FRAME_RATE));
    biosKeys_->SetValue(settings::GetInt("Launcher", "BiosKeys", 0) != 0);
    originalBugs_->SetValue(settings::GetInt("Launcher", "OriginalBugs", 0) != 0);
    const wxString monitor = settings::GetString("Launcher", "Monitor", MONITORS[0]);
    monitor_->SetSelection(0);
    for (int i = 0; i < 3; ++i)
        if (monitor == MONITORS[i]) monitor_->SetSelection(i);
    const wxString key = settings::GetString("Launcher", "Version", VERSIONS[0].key);
    for (size_t i = 0; i < VERSIONS.size(); ++i)
        if (key == VERSIONS[i].key) selected_ = i;
    for (Family f : {Family::Dos, Family::Amiga})
        if (FolderOf(f).empty()) FolderOf(f) = DefaultGameDir(f);
    radios_[selected_]->SetValue(true);
    folder_->ChangeValue(FolderOf(Selected().family));
    ShowEditedKeys();
    loading_ = false;
    UpdateState();

    Bind(wxEVT_ACTIVATE, [this](wxActivateEvent& event) {
        if (event.GetActive()) UpdateState();  // files may have been copied in meanwhile
        event.Skip();
    });
    Bind(wxEVT_CLOSE_WINDOW, [this](wxCloseEvent&) {
        Save();
        Destroy();
    });

    FitPage();
    if (!settings::RestoreWindowPosition("Launcher", this)) Centre();
}

wxWindow* LauncherFrame::CreateMainPage(wxWindow* parent) {
    auto* page = new wxPanel(parent);
    const int margin = FromDIP(12), gap = FromDIP(8), small = FromDIP(4);

    // Version
    auto* versionBox = new wxStaticBoxSizer(wxVERTICAL, page, "Version");
    wxWindow* vb = versionBox->GetStaticBox();
    auto* versionGrid = new wxFlexGridSizer(2, small, FromDIP(16));
    for (size_t i = 0; i < VERSIONS.size(); ++i) {
        auto* radio = new wxRadioButton(vb, wxID_ANY, VERSIONS[i].label, wxDefaultPosition, wxDefaultSize,
                                        i == 0 ? wxRB_GROUP : 0);
        radio->Bind(wxEVT_RADIOBUTTON, [this, i](wxCommandEvent&) { Select(i); });
        auto* note = GreyText(vb);
        versionGrid->Add(radio, 0, wxALIGN_CENTER_VERTICAL);
        versionGrid->Add(note, 0, wxALIGN_CENTER_VERTICAL);
        radios_.push_back(radio);
        notes_.push_back(note);
    }
    versionBox->Add(versionGrid, 0, wxALL, gap);

    // Game files
    auto* folderBox = new wxStaticBoxSizer(wxVERTICAL, page, "Game files");
    wxWindow* fb = folderBox->GetStaticBox();
    auto* folderRow = new wxBoxSizer(wxHORIZONTAL);
    auto* folderLabel = new wxStaticText(fb, wxID_ANY, "&Folder:");
    folder_ = new wxTextCtrl(fb, wxID_ANY, wxEmptyString, wxDefaultPosition, wxSize(FromDIP(300), -1));
    folder_->SetToolTip("The folder with the original game's files.");
    auto* browse = new wxButton(fb, wxID_ANY, "&Browse...");
    folderRow->Add(folderLabel, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, gap);
    folderRow->Add(folder_, 1, wxALIGN_CENTER_VERTICAL | wxRIGHT, gap);
    folderRow->Add(browse, 0, wxALIGN_CENTER_VERTICAL);
    auto* statusRow = new wxBoxSizer(wxHORIZONTAL);
    folderIcon_ = new wxStaticBitmap(fb, wxID_ANY, wxArtProvider::GetBitmapBundle(wxART_WARNING, wxART_MENU));
    folderNote_ = new wxStaticText(fb, wxID_ANY, wxEmptyString);
    statusRow->Add(folderIcon_, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, small);
    statusRow->Add(folderNote_, 1, wxALIGN_CENTER_VERTICAL);
    folderBox->Add(folderRow, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, gap);
    folderBox->Add(statusRow, 0, wxEXPAND | wxALL, gap);
    folder_->Bind(wxEVT_TEXT, [this](wxCommandEvent&) {
        if (loading_) return;
        FolderOf(Selected().family) = folder_->GetValue();
        UpdateState();
    });
    browse->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Browse(); });

    // Options
    auto* optionsBox = new wxStaticBoxSizer(wxVERTICAL, page, "Options");
    wxWindow* ob = optionsBox->GetStaticBox();
    auto* grid = new wxFlexGridSizer(2, gap, gap);
    grid->Add(new wxStaticText(ob, wxID_ANY, "Window &size:"), 0, wxALIGN_CENTER_VERTICAL);
    scale_ = new wxChoice(ob, wxID_ANY);
    for (int s = MIN_SCALE; s <= MAX_SCALE; ++s) scale_->Append(wxString::Format(L"%d × %d", 320 * s, 240 * s));
    scale_->SetToolTip("The window's size when the game starts. Alt+Enter switches to full screen.");
    grid->Add(scale_, 0, wxALIGN_CENTER_VERTICAL);

    frameRateLabel_ = new wxStaticText(ob, wxID_ANY, "&Frame rate:");
    grid->Add(frameRateLabel_, 0, wxALIGN_CENTER_VERTICAL);
    auto* frameRow = new wxBoxSizer(wxHORIZONTAL);
    frameRate_ = new wxSpinCtrl(ob, wxID_ANY, wxEmptyString, wxDefaultPosition, wxSize(FromDIP(64), -1),
                                wxSP_ARROW_KEYS, 0, 100, DEFAULT_FRAME_RATE);
    frameRow->Add(frameRate_, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, gap);
    frameRateHint_ = GreyText(ob, "while driving: 8 as in the original, 0 as fast as possible");
    frameRow->Add(frameRateHint_, 0, wxALIGN_CENTER_VERTICAL);
    grid->Add(frameRow, 0, wxALIGN_CENTER_VERTICAL);

    monitorLabel_ = new wxStaticText(ob, wxID_ANY, "&Monitor:");
    grid->Add(monitorLabel_, 0, wxALIGN_CENTER_VERTICAL);
    monitor_ = new wxChoice(ob, wxID_ANY);
    monitor_->Append("Green");
    monitor_->Append("Amber");
    monitor_->Append("White");
    monitor_->SetToolTip("The phosphor colour of the Hercules monochrome picture.");
    grid->Add(monitor_, 0, wxALIGN_CENTER_VERTICAL);
    optionsBox->Add(grid, 0, wxLEFT | wxRIGHT | wxTOP, gap);

    biosKeys_ = new wxCheckBox(ob, wxID_ANY, "Original &keyboard handling");
    biosKeys_->SetToolTip(
        "Driving keys act only through the keyboard's key repeat, exactly like the original. "
        "When off, keys act for as long as they are held.");
    optionsBox->Add(biosKeys_, 0, wxLEFT | wxRIGHT | wxTOP, gap);

    originalBugs_ = new wxCheckBox(ob, wxID_ANY, "Original b&ugs");
    originalBugs_->SetToolTip(
        "Keep the original game's bugs, such as the traffic that never appears. "
        "When off, the port fixes them.");
    optionsBox->Add(originalBugs_, 0, wxALL, gap);

    // Buttons
    auto* buttons = new wxBoxSizer(wxHORIZONTAL);
    play_ = new wxButton(page, wxID_ANY, "&Play");
    auto* close = new wxButton(page, wxID_CLOSE, "Close");
    buttons->AddStretchSpacer();
    buttons->Add(play_, 0, wxRIGHT, gap);
    buttons->Add(close);
    play_->SetDefault();
    play_->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Play(); });
    close->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Close(); });

    auto* all = new wxBoxSizer(wxVERTICAL);
    all->Add(versionBox, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, margin);
    all->Add(folderBox, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, margin);
    all->Add(optionsBox, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, margin);
    all->Add(buttons, 0, wxEXPAND | wxALL, margin);
    page->SetSizer(all);
    return page;
}

wxWindow* LauncherFrame::CreateKeysPage(wxWindow* parent) {
    auto* page = new wxPanel(parent);
    const int margin = FromDIP(12), gap = FromDIP(8), small = FromDIP(4);

    auto* intro = GreyText(page, "The menus and the name entry keep the game's own keys. Actions marked DOS or "
                                 "Amiga are only in those versions.");

    // A box per group with a label, a key button and the versions of each action. Driving shares its column
    // with the keys that can't be changed.
    wxStaticBoxSizer* boxes[keys::GROUP_COUNT];
    wxFlexGridSizer* grids[keys::GROUP_COUNT];
    for (int g = 0; g < keys::GROUP_COUNT; ++g) {
        boxes[g] = new wxStaticBoxSizer(wxVERTICAL, page, keys::GROUP_TITLES[g]);
        grids[g] = new wxFlexGridSizer(3, small, gap);
        grids[g]->AddGrowableCol(1);
        boxes[g]->Add(grids[g], 0, wxEXPAND | wxALL, gap);
    }
    for (int i = 0; i < keys::ACTION_COUNT; ++i) {
        const keys::Action& a = keys::ACTIONS[i];
        wxWindow* box = boxes[a.group]->GetStaticBox();
        grids[a.group]->Add(new wxStaticText(box, wxID_ANY, a.label), 0, wxALIGN_CENTER_VERTICAL);
        auto* button = new wxButton(box, wxID_ANY, wxEmptyString, wxDefaultPosition, wxSize(FromDIP(120), -1));
        button->Bind(wxEVT_BUTTON, [this, i](wxCommandEvent&) { ChangeKey(i); });
        grids[a.group]->Add(button, 0, wxEXPAND);
        grids[a.group]->Add(GreyText(box, keys::VersionsNote(a.versions)), 0, wxALIGN_CENTER_VERTICAL);
        keyButtons_.push_back(button);
    }
    auto* fixedBox = new wxStaticBoxSizer(wxVERTICAL, page, "Keys that keep their job");
    wxWindow* xb = fixedBox->GetStaticBox();
    auto* fixedGrid = new wxFlexGridSizer(2, small, FromDIP(16));
    for (int i = 0; i < keys::FIXED_COUNT; ++i) {
        fixedGrid->Add(new wxStaticText(xb, wxID_ANY, keys::FIXED[i].keys));
        fixedGrid->Add(GreyText(xb, keys::FIXED[i].what));
    }
    fixedBox->Add(fixedGrid, 0, wxALL, gap);

    auto* first = new wxBoxSizer(wxVERTICAL);
    first->Add(boxes[keys::DRIVING], 0, wxEXPAND);
    first->Add(fixedBox, 0, wxEXPAND | wxTOP, margin);
    auto* columns = new wxBoxSizer(wxHORIZONTAL);
    columns->Add(first, 0, wxEXPAND);
    columns->Add(boxes[keys::GAME], 0, wxEXPAND | wxLEFT, margin);

    auto* buttons = new wxBoxSizer(wxHORIZONTAL);
    auto* defaults = new wxButton(page, wxID_ANY, "&Default");
    defaults->SetToolTip("Put every key back as the game has it.");
    auto* apply = new wxButton(page, wxID_APPLY, "&Apply");
    apply->SetToolTip("Keep these keys and go back.");
    auto* cancel = new wxButton(page, wxID_CANCEL, "Cancel");
    cancel->SetToolTip("Go back without changing the keys.");
    buttons->Add(defaults);
    buttons->AddStretchSpacer();
    buttons->Add(apply, 0, wxRIGHT, gap);
    buttons->Add(cancel);
    defaults->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) {
        edited_ = keys::Defaults();
        ShowEditedKeys();
    });
    apply->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) {
        bindings_ = edited_;
        keys::Save(bindings_);
        CloseKeys();
    });
    cancel->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { CloseKeys(); });

    auto* all = new wxBoxSizer(wxVERTICAL);
    all->Add(intro, 0, wxLEFT | wxRIGHT | wxTOP, margin);
    all->Add(columns, 1, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, margin);
    all->Add(buttons, 0, wxEXPAND | wxALL, margin);
    page->SetSizer(all);
    return page;
}

void LauncherFrame::CreateMenus() {
    auto* file = new wxMenu;
    file->Append(wxID_PREFERENCES, wxString::FromUTF8("&Preferences…"));
    file->AppendSeparator();
    file->Append(wxID_EXIT, "E&xit\tAlt+F4");
    auto* settingsMenu = new wxMenu;
    settingsMenu->Append(ID_KEY_BINDINGS, wxString::FromUTF8("&Key Bindings…"));

    auto* bar = new wxMenuBar;
    bar->Append(file, "&File");
    bar->Append(settingsMenu, "&Game settings");
#ifndef __WXMSW__
    auto* about = new wxMenu;
    about->Append(ID_ABOUT, wxString::FromUTF8("&About ") + APP_TITLE + wxString::FromUTF8("…"));
    bar->Append(about, "A&bout");
#endif
    SetMenuBar(bar);
#ifdef __WXMSW__
    // A top-level About item that acts straight away, which wxWidgets menus
    // can't express; MSWWindowProc handles its command.
    const HMENU native = static_cast<HMENU>(bar->GetHMenu());
    AppendMenuW(native, MF_STRING, ID_ABOUT, L"A&bout");
    DrawMenuBar(static_cast<HWND>(GetHWND()));
#endif

    Bind(wxEVT_MENU, [this](wxCommandEvent&) { Close(); }, wxID_EXIT);
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { Preferences(); }, wxID_PREFERENCES);
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { OpenKeys(); }, ID_KEY_BINDINGS);
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { About(); }, ID_ABOUT);
}

#ifdef __WXMSW__
WXLRESULT LauncherFrame::MSWWindowProc(WXUINT msg, WXWPARAM wParam, WXLPARAM lParam) {
    if (msg == WM_COMMAND && LOWORD(wParam) == ID_ABOUT && lParam == 0) {
        CallAfter([this] { About(); });
        return 0;
    }
    return wxFrame::MSWWindowProc(msg, wParam, lParam);
}
#endif

void LauncherFrame::Select(size_t index) {
    const Family was = Selected().family;
    selected_ = index;
    radios_[index]->SetValue(true);
    if (Selected().family != was) {
        loading_ = true;
        folder_->ChangeValue(FolderOf(Selected().family));
        loading_ = false;
    }
    UpdateState();
}

void LauncherFrame::UpdateState() {
    bool any = false;
    for (size_t i = 0; i < VERSIONS.size(); ++i) {
        const bool installed = PortInstalled(VERSIONS[i]);
        any |= installed;
        radios_[i]->Enable(installed);
        notes_[i]->SetLabel(installed ? wxString() : "Not installed");
    }
    // Move off a version that isn't there (any more) to the first one that is.
    if (!PortInstalled(Selected()))
        for (size_t i = 0; i < VERSIONS.size(); ++i)
            if (PortInstalled(VERSIONS[i])) {
                Select(i);
                return;
            }

    const Version& v = Selected();
    const wxString gameFile = FindGameFile(v, folder_->GetValue());
    const bool found = !gameFile.empty();
    wxString note;
    if (!any)
        note = "The game isn't installed: no tdport executable is beside the launcher.";
    else if (found)
        note = wxString::Format("Found %s.", gameFile);
    else
        note = wxString::Format("This folder needs %s.", v.needs);
    folderIcon_->Show(!any || !found);
    folderNote_->SetLabel(note);

    frameRateLabel_->Enable(v.dosOptions);
    frameRate_->Enable(v.dosOptions);
    frameRateHint_->Enable(v.dosOptions);
    biosKeys_->Enable(v.dosOptions);
    originalBugs_->Enable(v.originalBugs);
    monitorLabel_->Enable(v.monitor);
    monitor_->Enable(v.monitor);
    play_->Enable(any && found);
    play_->GetParent()->Layout();
}

void LauncherFrame::Browse() {
    wxDirDialog dialog(this, "Choose the folder with the game's files", folder_->GetValue(),
                       wxDD_DEFAULT_STYLE | wxDD_DIR_MUST_EXIST);
    if (dialog.ShowModal() == wxID_OK) folder_->SetValue(dialog.GetPath());  // raises wxEVT_TEXT
}

void LauncherFrame::Play() {
    Save();
    LaunchOptions options;
    options.gameDir = wxFileName(folder_->GetValue()).GetFullPath();
    options.scale = scale_->GetSelection() + MIN_SCALE;
    options.frameRate = frameRate_->GetValue();
    options.biosKeys = biosKeys_->GetValue();
    options.originalBugs = originalBugs_->GetValue();
    options.monitor = MONITORS[wxMax(0, monitor_->GetSelection())];
    options.keys = keys::Argument(bindings_, Selected().family == Family::Dos ? keys::DOS : keys::AMIGA);
    wxString error;
    if (!Launch(Selected(), options, error)) {
        wxMessageBox(error, APP_TITLE, wxOK | wxICON_ERROR, this);
        return;
    }
    Close();
}

void LauncherFrame::Save() {
    settings::SetString("Launcher", "Version", Selected().key);
    // A folder left at its default is stored empty, so it follows the launcher if it moves.
    for (Family f : {Family::Dos, Family::Amiga}) {
        const wxString& dir = FolderOf(f);
        settings::SetString("Launcher", FolderKey(f),
                            wxFileName(dir).SameAs(wxFileName(DefaultGameDir(f))) ? wxString() : dir);
    }
    settings::SetInt("Launcher", "Scale", scale_->GetSelection() + MIN_SCALE);
    settings::SetInt("Launcher", "FrameRate", frameRate_->GetValue());
    settings::SetInt("Launcher", "BiosKeys", biosKeys_->GetValue() ? 1 : 0);
    settings::SetInt("Launcher", "OriginalBugs", originalBugs_->GetValue() ? 1 : 0);
    settings::SetString("Launcher", "Monitor", MONITORS[wxMax(0, monitor_->GetSelection())]);
    settings::SaveWindowPosition("Launcher", this);
}

void LauncherFrame::Preferences() {
    wxDialog dialog(this, wxID_ANY, "Preferences");
    auto* all = new wxBoxSizer(wxVERTICAL);
    auto* topmost = new wxCheckBox(&dialog, wxID_ANY, "Always on &top");
    topmost->SetValue(topmost_);
    topmost->SetToolTip("Keep the launcher above other windows.");
    all->Add(topmost, 0, wxALL, dialog.FromDIP(12));
    all->Add(dialog.CreateStdDialogButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM,
             dialog.FromDIP(12));
    dialog.SetSizerAndFit(all);
    dialog.SetMinSize(wxSize(dialog.FromDIP(300), -1));
    dialog.Fit();
    dialog.CentreOnParent();
    topmost->SetFocus();
    if (dialog.ShowModal() != wxID_OK) return;
    if (topmost->GetValue() != topmost_) SetTopmost(topmost->GetValue());
}

void LauncherFrame::SetTopmost(bool on) {
    topmost_ = on;
    const long style = GetWindowStyleFlag();
    SetWindowStyleFlag(on ? style | wxSTAY_ON_TOP : style & ~wxSTAY_ON_TOP);
    settings::SetInt("Preferences", "AlwaysOnTop", on ? 1 : 0);
}

// The window takes the size of the page shown (the book on its own would take the largest page's).
void LauncherFrame::FitPage() {
    SetClientSize(book_->GetCurrentPage()->GetBestSize());
}

void LauncherFrame::OpenKeys() {
    if (book_->GetSelection() == PAGE_KEYS) return;
    edited_ = bindings_;
    ShowEditedKeys();
    book_->ChangeSelection(PAGE_KEYS);
    FitPage();
    GetMenuBar()->Enable(ID_KEY_BINDINGS, false);
    SetDefaultItem(book_->GetPage(PAGE_KEYS)->FindWindow(wxID_APPLY));
    keyButtons_.front()->SetFocus();
}

void LauncherFrame::CloseKeys() {
    book_->ChangeSelection(PAGE_MAIN);
    FitPage();
    GetMenuBar()->Enable(ID_KEY_BINDINGS, true);
    SetDefaultItem(play_);
    UpdateState();
    play_->SetFocus();
}

void LauncherFrame::ShowEditedKeys() {
    for (int i = 0; i < keys::ACTION_COUNT; ++i) {
        const wxString name = keys::Name(edited_[i]);
        // Buttons treat '&' as a mnemonic marker.
        wxString label = name;
        label.Replace("&", "&&");
        keyButtons_[i]->SetLabel(label);
        keyButtons_[i]->SetToolTip(wxString::Format("%s: %s. Click to change it.", keys::ACTIONS[i].label, name));
        // A key that differs from the game's own stands out.
        wxFont font = keyButtons_[i]->GetParent()->GetFont();
        if (edited_[i] != keys::ACTIONS[i].def) font.MakeBold();
        keyButtons_[i]->SetFont(font);
    }
    book_->GetPage(PAGE_KEYS)->Layout();
}

void LauncherFrame::ChangeKey(int action) {
    const keys::Action& a = keys::ACTIONS[action];
    const int key = keys::AskKey(this, a.label);
    if (key < 0 || key == edited_[action]) return;
    if (key != 0) {
        // Actions of different versions can share a key.
        for (int other = 0; other < keys::ACTION_COUNT; ++other) {
            const keys::Action& o = keys::ACTIONS[other];
            if (other == action || edited_[other] != key || !(o.versions & a.versions)) continue;
            const wxString question = wxString::Format(
                "%s is already the key for %s.\n\nUse it for %s instead? %s will have no key.", keys::Name(key),
                o.label, a.label, o.label);
            if (wxMessageBox(question, "Key Bindings", wxYES_NO | wxICON_QUESTION, this) != wxYES) return;
            edited_[other] = 0;
        }
    }
    edited_[action] = key;
    ShowEditedKeys();
}

void LauncherFrame::About() {
    const wxString title = wxString("About ") + APP_TITLE;
    const wxString heading = wxString(APP_TITLE) + " " + APP_VERSION_TEXT;
    const wxString blurb = "The launcher for the SDL3 port of Test Drive (1987).";
#ifdef __WXMSW__
    // The Windows task dialog.
    const wxString content = wxString::Format(
        "%s\n\n"
        "Author: Krzysztof Kania\n"
        "Website: <a href=\"%s\">kkania.com</a>\n"
        "Source: <a href=\"%s\">github.com/kylofon/test-drive-sdl3</a>\n"
        "Support: <a href=\"%s\">buymeacoffee.com/krzysztofkania</a>",
        blurb, WEBSITE, SOURCE, SUPPORT);
    wxIcon icon;
    icon.CopyFromBitmap(AppBitmap(FromDIP(32)));
    TASKDIALOGCONFIG dialog{};
    dialog.cbSize = sizeof dialog;
    dialog.hwndParent = static_cast<HWND>(GetHWND());
    dialog.dwFlags = TDF_ENABLE_HYPERLINKS | TDF_USE_HICON_MAIN | TDF_ALLOW_DIALOG_CANCELLATION |
                     TDF_POSITION_RELATIVE_TO_WINDOW;
    dialog.dwCommonButtons = TDCBF_OK_BUTTON;
    dialog.pszWindowTitle = title.wc_str();
    dialog.hMainIcon = static_cast<HICON>(icon.GetHICON());
    dialog.pszMainInstruction = heading.wc_str();
    dialog.pszContent = content.wc_str();
    dialog.pfCallback = AboutCallback;
    TaskDialogIndirect(&dialog, nullptr, nullptr, nullptr);
#else
    wxDialog dialog(this, wxID_ANY, title);
    auto* body = new wxBoxSizer(wxHORIZONTAL);
    body->Add(new wxStaticBitmap(&dialog, wxID_ANY, AppBitmap(dialog.FromDIP(48))), 0, wxALL, dialog.FromDIP(12));

    auto* text = new wxBoxSizer(wxVERTICAL);
    auto* headingText = new wxStaticText(&dialog, wxID_ANY, heading);
    headingText->SetFont(dialog.GetFont().Bold().Scaled(1.3f));
    text->Add(headingText, 0, wxBOTTOM, dialog.FromDIP(8));
    text->Add(new wxStaticText(&dialog, wxID_ANY, blurb), 0, wxBOTTOM, dialog.FromDIP(12));
    text->Add(new wxStaticText(&dialog, wxID_ANY, "Author: Krzysztof Kania"));
    AddLink(&dialog, text, "Website:", "kkania.com", WEBSITE);
    AddLink(&dialog, text, "Source:", "github.com/kylofon/test-drive-sdl3", SOURCE);
    AddLink(&dialog, text, "Support:", "buymeacoffee.com/krzysztofkania", SUPPORT);
    body->Add(text, 1, wxTOP | wxRIGHT | wxBOTTOM, dialog.FromDIP(12));

    auto* all = new wxBoxSizer(wxVERTICAL);
    all->Add(body, 1, wxEXPAND);
    all->Add(dialog.CreateStdDialogButtonSizer(wxOK), 0, wxEXPAND | wxALL, dialog.FromDIP(8));
    dialog.SetSizerAndFit(all);
    dialog.CentreOnParent();
    dialog.ShowModal();
#endif
}
