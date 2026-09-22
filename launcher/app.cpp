// app.cpp -- Test Drive launcher: picks a version of the SDL3 port (EGA, CGA,
// Hercules, Amiga) and starts it.
#include <wx/app.h>

#include "launcher.h"

class LauncherApp : public wxApp {
public:
    bool OnInit() override {
        SetAppName("Test Drive Launcher");
        SetVendorName("Krzysztof Kania");
        if (!wxApp::OnInit()) return false;
        auto* dialog = new LauncherDialog;
        SetTopWindow(dialog);
        dialog->Show();
        return true;
    }
};

wxIMPLEMENT_APP(LauncherApp);
