// versions.h -- the versions of the port the launcher knows, where their
// executables and game files are, and starting one.
#pragma once

#include <wx/string.h>

#include <array>

// Versions of one family read the same game files, so they share a game folder.
enum class Family { Dos, Amiga };

struct Version {
    const char* key;        // its name in settings.ini
    const char* label;      // the radio button
    const char* exe;        // the port's executable beside the launcher, without ".exe"
    Family family;
    const char* gameFile;   // the original file the port loads from the game folder
    const char* needs;      // what the game folder must hold, for the status line
    bool dosOptions;        // takes --frame-rate and --bios-keys
    bool monitor;           // takes --monitor
    bool originalBugs;      // takes --original-bugs
};

extern const std::array<Version, 4> VERSIONS;

// The folder the launcher runs from; the ports sit beside it.
wxString LauncherDir();

// The full path of a version's executable, and whether it is there.
wxString PortPath(const Version& v);
bool PortInstalled(const Version& v);

// Where a family's game files are by default: "Game" (DOS) or "Game Amiga"
// beside the launcher.
wxString DefaultGameDir(Family family);

// The game file the version would load from `dir` (its name, as found), or an empty string if there is none.
// The Amiga version also takes an Amiga disk image (.adf) in the folder.
wxString FindGameFile(const Version& v, const wxString& dir);

struct LaunchOptions {
    wxString gameDir;
    int scale = 3;          // --scale: the window is 320x240 times this
    int frameRate = 8;      // --frame-rate: 0 draws as fast as possible
    bool biosKeys = false;  // --bios-keys
    wxString monitor;       // --monitor: green, amber or white
    bool originalBugs = false;  // --original-bugs: keep the original's bugs
};

// Starts the version from the launcher's folder. On failure returns false and
// says why in `error`.
bool Launch(const Version& v, const LaunchOptions& options, wxString& error);
