// versions.cpp -- the versions table, file checks and starting a port.
#include "versions.h"

#include <wx/dir.h>
#include <wx/filename.h>
#include <wx/log.h>
#include <wx/stdpaths.h>
#include <wx/utils.h>

#include <string>
#include <vector>

// "td" is the program the Amiga disk's Startup-Sequence runs.
const std::array<Version, 4> VERSIONS = {{
    {"ega", "&EGA (16 colours)", "tdport", Family::Dos, "TDEGA.EXE", "TDEGA.EXE and the *.PES files", true, false,
     false},
    {"cga", "&CGA (4 colours)", "tdport-cga", Family::Dos, "TDCGA.EXE", "TDCGA.EXE and the *.CMP files", true,
     false, false},
    {"herc", "&Hercules (monochrome)", "tdport-herc", Family::Dos, "TDCGA.EXE", "TDCGA.EXE and the *.CMP files",
     true, true, false},
    {"amiga", "A&miga", "tdport-amiga", Family::Amiga, "td", "the Amiga disk image (.adf) or the files from the disk",
     false, false,
     true},
}};

wxString LauncherDir() { return wxFileName(wxStandardPaths::Get().GetExecutablePath()).GetPath(); }

wxString PortPath(const Version& v) {
    wxFileName name(LauncherDir(), v.exe);
#ifdef __WXMSW__
    name.SetExt("exe");
#endif
    return name.GetFullPath();
}

bool PortInstalled(const Version& v) { return wxFileName::FileExists(PortPath(v)); }

wxString DefaultGameDir(Family family) {
    return wxFileName(LauncherDir(), family == Family::Dos ? "Game" : "Game Amiga").GetFullPath();
}

wxString FindGameFile(const Version& v, const wxString& dir) {
    if (dir.empty() || !wxFileName::DirExists(dir)) return wxString();
    const wxString name(v.gameFile);
    // Case matters outside Windows: accept the name as written or in lower case.
    if (wxFileName::FileExists(wxFileName(dir, name).GetFullPath())) return name;
    if (wxFileName::FileExists(wxFileName(dir, name.Lower()).GetFullPath())) return name.Lower();
    if (v.family == Family::Amiga) {
        wxDir folder(dir);
        wxString adf;
        if (folder.IsOpened() && (folder.GetFirst(&adf, "*.adf", wxDIR_FILES) || folder.GetFirst(&adf, "*.ADF", wxDIR_FILES)))
            return adf;
    }
    return wxString();
}

bool Launch(const Version& v, const LaunchOptions& o, wxString& error) {
    std::vector<wxString> args{PortPath(v), "--game-dir", o.gameDir, "--scale", wxString::Format("%d", o.scale)};
    if (v.dosOptions) {
        args.insert(args.end(), {"--frame-rate", wxString::Format("%d", o.frameRate)});
        if (o.biosKeys) args.push_back("--bios-keys");
    }
    if (v.monitor && !o.monitor.empty()) args.insert(args.end(), {"--monitor", o.monitor});
    if (v.originalBugs && o.originalBugs) args.push_back("--original-bugs");

    std::vector<std::wstring> wide;
    for (const wxString& a : args) wide.push_back(a.ToStdWstring());
    std::vector<const wchar_t*> argv;
    for (const std::wstring& w : wide) argv.push_back(w.c_str());
    argv.push_back(nullptr);

    wxExecuteEnv env;  // an empty variable map: the port inherits the launcher's environment
    env.cwd = LauncherDir();
    long pid;
    {
        wxLogNull quiet;  // wxExecute would show its own error box
        pid = wxExecute(argv.data(), wxEXEC_ASYNC, nullptr, &env);
    }
    if (pid == 0) {
        error = wxString::Format("Couldn't start %s.\n\n%s", wxFileName(PortPath(v)).GetFullName(),
                                 wxSysErrorMsgStr(wxSysErrorCode()));
        return false;
    }
    return true;
}
