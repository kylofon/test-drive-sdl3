// launcher.cpp -- the launcher window.
#include "launcher.h"

#include <wx/artprov.h>
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/dirdlg.h>
#include <wx/filename.h>
#include <wx/hyperlink.h>
#include <wx/msgdlg.h>
#include <wx/radiobut.h>
#include <wx/settings.h>
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

LauncherDialog::LauncherDialog()
    : wxDialog(nullptr, wxID_ANY, APP_TITLE, wxDefaultPosition, wxDefaultSize,
               wxDEFAULT_DIALOG_STYLE | wxMINIMIZE_BOX) {
    SetIcons(AppIcons());
    const int margin = FromDIP(12), gap = FromDIP(8), small = FromDIP(4);

    // Version
    auto* versionBox = new wxStaticBoxSizer(wxVERTICAL, this, "Version");
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
    auto* folderBox = new wxStaticBoxSizer(wxVERTICAL, this, "Game files");
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
    auto* optionsBox = new wxStaticBoxSizer(wxVERTICAL, this, "Options");
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
    optionsBox->Add(biosKeys_, 0, wxALL, gap);

    // Buttons
    auto* buttons = new wxBoxSizer(wxHORIZONTAL);
    auto* about = new wxButton(this, wxID_ABOUT, "&About");
    play_ = new wxButton(this, wxID_ANY, "&Play");
    auto* close = new wxButton(this, wxID_CLOSE, "Close");
    buttons->Add(about);
    buttons->AddStretchSpacer();
    buttons->Add(play_, 0, wxRIGHT, gap);
    buttons->Add(close);
    play_->SetDefault();
    SetEscapeId(wxID_CLOSE);
    about->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { About(); });
    play_->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Play(); });
    close->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Close(); });

    auto* all = new wxBoxSizer(wxVERTICAL);
    all->Add(versionBox, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, margin);
    all->Add(folderBox, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, margin);
    all->Add(optionsBox, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, margin);
    all->Add(buttons, 0, wxEXPAND | wxALL, margin);
    SetSizer(all);

    // Settings from the last run.
    for (Family f : {Family::Dos, Family::Amiga}) FolderOf(f) = settings::GetString("Launcher", FolderKey(f), "");
    scale_->SetSelection(
        wxMax(MIN_SCALE, wxMin(MAX_SCALE, settings::GetInt("Launcher", "Scale", DEFAULT_SCALE))) - MIN_SCALE);
    frameRate_->SetValue(settings::GetInt("Launcher", "FrameRate", DEFAULT_FRAME_RATE));
    biosKeys_->SetValue(settings::GetInt("Launcher", "BiosKeys", 0) != 0);
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

    Fit();
    if (!settings::RestoreWindowPosition("Launcher", this)) Centre();
}

void LauncherDialog::Select(size_t index) {
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

void LauncherDialog::UpdateState() {
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
    const bool found = GameFilePresent(v, folder_->GetValue());
    wxString note;
    if (!any)
        note = "The game isn't installed: no tdport executable is beside the launcher.";
    else if (found)
        note = wxString::Format("Found %s.", v.gameFile);
    else
        note = wxString::Format("This folder needs %s.", v.needs);
    folderIcon_->Show(!any || !found);
    folderNote_->SetLabel(note);

    frameRateLabel_->Enable(v.dosOptions);
    frameRate_->Enable(v.dosOptions);
    frameRateHint_->Enable(v.dosOptions);
    biosKeys_->Enable(v.dosOptions);
    monitorLabel_->Enable(v.monitor);
    monitor_->Enable(v.monitor);
    play_->Enable(any && found);
    Layout();
}

void LauncherDialog::Browse() {
    wxDirDialog dialog(this, "Choose the folder with the game's files", folder_->GetValue(),
                       wxDD_DEFAULT_STYLE | wxDD_DIR_MUST_EXIST);
    if (dialog.ShowModal() == wxID_OK) folder_->SetValue(dialog.GetPath());  // raises wxEVT_TEXT
}

void LauncherDialog::Play() {
    Save();
    LaunchOptions options;
    options.gameDir = wxFileName(folder_->GetValue()).GetFullPath();
    options.scale = scale_->GetSelection() + MIN_SCALE;
    options.frameRate = frameRate_->GetValue();
    options.biosKeys = biosKeys_->GetValue();
    options.monitor = MONITORS[wxMax(0, monitor_->GetSelection())];
    wxString error;
    if (!Launch(Selected(), options, error)) {
        wxMessageBox(error, APP_TITLE, wxOK | wxICON_ERROR, this);
        return;
    }
    Close();
}

void LauncherDialog::Save() {
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
    settings::SetString("Launcher", "Monitor", MONITORS[wxMax(0, monitor_->GetSelection())]);
    settings::SaveWindowPosition("Launcher", this);
}

void LauncherDialog::About() {
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
