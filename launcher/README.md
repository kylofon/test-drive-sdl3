# Test Drive launcher

`Test Drive.exe` lets players choose which version of the port to start. It is built with
[wxWidgets](https://www.wxwidgets.org/) 3.2 from the platform's own controls, so on Windows it looks like any
Windows dialog: group boxes, radio buttons, push buttons and menus, themed through Common Controls 6, DPI aware.

It sits in the same folder as the port executables and looks for them there:

| Version | Executable | Game file it checks for |
|---|---|---|
| EGA (16 colours) | `tdport.exe` | `TDEGA.EXE` |
| CGA (4 colours) | `tdport-cga.exe` | `TDCGA.EXE` |
| Hercules (monochrome) | `tdport-herc.exe` | `TDCGA.EXE` |
| Amiga | `tdport-amiga.exe` | an Amiga disk image (`*.adf`), or `td` from the extracted disk |

A version whose executable is missing is greyed out and marked **Not installed**. `tdport-amiga.exe` is built
with `-DTDPORT_AMIGA=ON`; its game folder holds the Amiga disk image (`.adf`) or the files extracted from it (`td`, `Cars/`, `Pics/`,
...).

## The window

* **Version**: one of the four above.
* **Game files**: the folder with the original game's files. The DOS versions share one folder (default `Game`
  beside the launcher) and the Amiga version has its own (default `Game Amiga`). The line below it says whether
  the folder has the file the chosen version loads. **Play** stays greyed out until it does.
* **Options**:
  * **Window size**: 320 × 240 to 1920 × 1440 (`--scale`, default 960 × 720).
  * **Frame rate**: the drawing speed while driving (`--frame-rate`, default 8 as in the original, 0 as fast as
    possible). DOS versions only.
  * **Monitor**: green, amber or white phosphor (`--monitor`). Hercules only.
  * **Original keyboard handling**: driving keys act only through key repeat (`--bios-keys`). DOS versions only.
  * **Original bugs**: keep the original game's bugs instead of the port's fixes (`--original-bugs`; the list is
    in `port/amiga/README.md`). Amiga only.
* **Play** starts the version from the launcher's folder with `--game-dir` and those options, then closes the
  launcher. If the version can't be started, a message box says why. Errors inside the game (a missing data file,
  say) are reported by the game itself.

## Menus

The menus follow Test Drive III Enhanced's launcher.

* **File**: **Preferences** (**Always on top** keeps the launcher above other windows) and **Exit**.
* **Game settings > Key Bindings** shows the game's keys in the window, in two groups (driving, game). Click a
  key and press the new one ("Press new key"; Shift, Ctrl or Alt can be held with it, Esc cancels, **No key**
  leaves the action without one). Keys are the keyboard's places, whatever its layout. Some actions are only in
  the DOS versions (A / Z shifting, Ctrl+Q / S / J / K) or only in the Amiga version (fire, M, S); they are
  marked so, and actions of different versions may share a key. A key already used by another action of the
  same version can be moved, leaving that one without a key. **Default** puts every key back, **Apply** keeps
  them and goes back, **Cancel** goes back without changing them. The version gets the changed ones with
  `--keys` and applies them while driving; the menus, the name entry and the waits for a key keep the game's own
  keys. The keypad, Home / PgUp / End / PgDn (DOS diagonals), Right Ctrl (Amiga fire), Esc, Enter and Alt+Enter
  keep their jobs. Stored under `[Keys]`.
* **About**: the version, author and links, in the Windows task dialog.

The ports and the game folder are checked again whenever the window is activated, so files copied in while it is
open show up straight away.

Everything is remembered in `%APPDATA%\Test Drive Launcher\settings.ini` (`~/.config/test-drive-launcher` on
Linux): the version, both game folders, the options, the keys, the preferences and where the window was. A game folder left at its default
is stored empty, so it follows the launcher if the whole folder moves. Delete the file to go back to the
defaults.

## Building

Needs CMake 3.24, a C++17 compiler and wxWidgets 3.2 (MSYS2 `mingw64`: `mingw-w64-x86_64-wxwidgets3.2-msw`;
Debian and Ubuntu: `libwxgtk3.2-dev`). To build it beside the port executables, add `-DTDPORT_LAUNCHER=ON` when
configuring `tdport`:

```bash
cmake -S tdport -B tdport/build -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release -DTDPORT_CGA=ON -DTDPORT_HERCULES=ON -DTDPORT_AMIGA=ON -DTDPORT_LAUNCHER=ON
cmake --build tdport/build
```

It also builds on its own (`cmake -S launcher -B launcher/build -G Ninja`), but then it has to be copied next to
the port executables to find them.

On Windows the build copies every DLL the launcher needs beside it (`copy_dlls.cmake`): the two wxWidgets DLLs
and the MSYS2 libraries they load (libstdc++, libpng, libtiff, ...). Keep them with the `.exe` in a release.
The C++ runtime of the launcher itself is linked in.

## Files

* `app.cpp`: the wxWidgets application.
* `launcher.h`, `launcher.cpp`: the window, its menus, the Key Bindings page, Preferences and the About box.
* `keys.h`, `keys.cpp`: the game's keys that can be changed, their names and the "Press new key" prompt (the
  port's own list is `tdport/src/keybind.c`).
* `versions.h`, `versions.cpp`: the versions table, the file checks and starting a port.
* `settings.h`, `settings.cpp`: `settings.ini`.
* `icon.h`, `icon.cpp`: the app icon, a chequered flag drawn in code. `make_icon.py` (Pillow) writes the same
  drawing to `app.ico` for Explorer.
* `app.rc`, `app.manifest`, `app.ico`, `version.h`: icon, visual styles, DPI awareness, version info.
* `copy_dlls.cmake`: the post-build DLL copy.
* `CMakeLists.txt`: the build, standalone or from `tdport`.
