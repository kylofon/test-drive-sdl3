// launcher.h -- the launcher window: choose a version, its game folder and
// options, then Play.
#pragma once

#include <wx/dialog.h>

#include <vector>

#include "versions.h"

class wxButton;
class wxCheckBox;
class wxChoice;
class wxRadioButton;
class wxSpinCtrl;
class wxStaticBitmap;
class wxStaticText;
class wxTextCtrl;

extern const char* const APP_TITLE;

class LauncherDialog : public wxDialog {
public:
    LauncherDialog();

private:
    const Version& Selected() const { return VERSIONS[selected_]; }
    wxString& FolderOf(Family family) { return folders_[family == Family::Dos ? 0 : 1]; }

    void Select(size_t index);
    // Re-checks which ports are installed and whether the game folder holds
    // what the selected version needs, and enables controls to match.
    void UpdateState();
    void Browse();
    void Play();
    void About();
    void Save();

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

    size_t selected_ = 0;
    wxString folders_[2];  // game folder per family: DOS, Amiga
    bool loading_ = true;  // no folder edits are recorded while the window is built
};
