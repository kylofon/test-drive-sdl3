// launcher.h -- the launcher window: choose a version, its game folder and options, then Play. Game settings >
// Key Bindings is shown in the window in its place to change the keys.
#pragma once

#include <wx/frame.h>

#include <vector>

#include "keys.h"
#include "versions.h"

class wxButton;
class wxCheckBox;
class wxChoice;
class wxRadioButton;
class wxSimplebook;
class wxSpinCtrl;
class wxStaticBitmap;
class wxStaticText;
class wxTextCtrl;

extern const char* const APP_TITLE;

class LauncherFrame : public wxFrame {
public:
    LauncherFrame();

private:
    const Version& Selected() const { return VERSIONS[selected_]; }
    wxString& FolderOf(Family family) { return folders_[family == Family::Dos ? 0 : 1]; }

    wxWindow* CreateMainPage(wxWindow* parent);
    wxWindow* CreateKeysPage(wxWindow* parent);
    void CreateMenus();
#ifdef __WXMSW__
    WXLRESULT MSWWindowProc(WXUINT msg, WXWPARAM wParam, WXLPARAM lParam) override;
#endif

    void Select(size_t index);
    // Re-checks which ports are installed and whether the game folder holds
    // what the selected version needs, and enables controls to match.
    void UpdateState();
    void Browse();
    void Play();
    void About();
    void Preferences();
    void SetTopmost(bool on);
    void Save();

    // Key Bindings, shown in place of the main page.
    void OpenKeys();
    void CloseKeys();
    void FitPage();
    // A new key for action i; the buttons from edited_.
    void ChangeKey(int action);
    void ShowEditedKeys();

    wxSimplebook* book_ = nullptr;
    std::vector<wxRadioButton*> radios_;
    std::vector<wxStaticText*> notes_;
    wxTextCtrl* folder_ = nullptr;
    wxStaticBitmap* folderIcon_ = nullptr;
    wxStaticText* folderNote_ = nullptr;
    wxChoice* scale_ = nullptr;
    wxStaticText* frameRateLabel_ = nullptr;
    wxSpinCtrl* frameRate_ = nullptr;
    wxStaticText* frameRateHint_ = nullptr;
    wxCheckBox* biosKeys_ = nullptr;
    wxCheckBox* originalBugs_ = nullptr;
    wxStaticText* monitorLabel_ = nullptr;
    wxChoice* monitor_ = nullptr;
    wxButton* play_ = nullptr;

    // The Key Bindings page: one button per action.
    std::vector<wxButton*> keyButtons_;
    keys::Bindings bindings_;  // saved
    keys::Bindings edited_;    // on the Key Bindings page

    size_t selected_ = 0;
    wxString folders_[2];  // game folder per family: DOS, Amiga
    bool topmost_ = false;
    bool loading_ = true;  // no folder edits are recorded while the window is built
};
