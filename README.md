# Test Drive (1987) — SDL3 port

A faithful C reimplementation of the EGA version of Accolade / Distinctive Software's *Test Drive* (1987),
running natively on SDL3. The CGA and Hercules modes of the original release can be built as separate
executables. It is not an emulator - the original data is not redistributed, and you need to get it yourself.

## How to play (Windows)

You need the files of the original DOS *Test Drive*. They are not included.

1. Open the [latest release](https://github.com/kylofon/test-drive-sdl3/releases/latest) and download
   `tdport-…-win64.zip` (the one without `cga` or `herc` in its name).
2. Put your original game files in a folder named `Game`.
3. Open the zip. Copy everything inside its `tdport` folder into the folder that holds `Game`, so that
   `tdport.exe` sits next to `Game`:

   ```text
   Test Drive\
   ├── Game\             <- your original game files (TDEGA.EXE, CARS.TXT, SCORES, ...)
   ├── tdport.exe
   ├── SDL3.dll
   ├── libiconv-2.dll
   └── (the other files from the zip)
   ```

4. Double-click `tdport.exe`.

Keep the folder somewhere you can save files, such as Documents or the Desktop, not Program Files. The game
saves its high scores in `Game`. If Windows says "Windows protected your PC", click **More info**, then
**Run anyway**. Press Alt+Enter for fullscreen. The keys are listed under [Controls](#controls-from-the-original).

The `cga` and `herc` zips are the CGA and Hercules versions. They work the same way, with `tdport-cga.exe` or
`tdport-herc.exe`, but need `TDCGA.EXE` and the `*.CMP` files in `Game`.

## Requirements

* Your game files in a folder. The port needs `TDEGA.EXE`, `CARS.TXT`, `SCORES`, `TDSND.SND`, the `*.PES`
  archives and the car `*.BIN` / `*.SS` files. By default the port looks in `Game` under the working directory.
  The CGA and Hercules builds need `TDCGA.EXE` and the `*.CMP` archives instead of `TDEGA.EXE` and `*.PES`.
* CMake 3.24+, a C11 compiler and SDL 3. 

## Build

From the repository root, in Git Bash or an MSYS2 MinGW64 shell:

```bash
export PATH="/c/msys64/mingw64/bin:$PATH"
cmake -S tdport -B tdport/build -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release
cmake --build tdport/build
```

This builds `tdport.exe` (EGA). The other graphics modes are opt-in CMake options. Each one adds an executable
that ports `TDCGA.EXE`:

| Option | Executable | Mode |
|---|---|---|
| `-DTDPORT_CGA=ON` | `tdport-cga.exe` | CGA, 4 colours (`TD.EXE` menu choice 1) |
| `-DTDPORT_HERCULES=ON` | `tdport-herc.exe` | Hercules monochrome (`TD.EXE` menu choice 3, `tdcga herc`) |

```bash
cmake -S tdport -B tdport/build -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release -DTDPORT_CGA=ON -DTDPORT_HERCULES=ON
cmake --build tdport/build
```

The build copies `SDL3.dll` next to the executables. The MSYS2 `SDL3.dll` also needs `libiconv-2.dll`, so the
build copies it from `C:\msys64\mingw64\bin` too. To run the port on another PC, keep both DLLs next to the `.exe`.

In your own build setup, compile the sources with `TD_CGA=1` (CGA) or `TD_CGA=1 TD_HERC=1` (Hercules)
defined, using `src/platform/gfx_cga.c` instead of `src/platform/gfx.c`.

## Run

```bash
./tdport/build/tdport.exe --game-dir Game
```

`tdport-cga.exe` and `tdport-herc.exe` take the same options.

| Option | Meaning |
|---|---|
| `--game-dir DIR` | Folder with the original game files (default `Game`) |
| `--scale N` | Initial window size as a multiple of 320×240 (default 3) |
| `--frame-rate FPS` | Emulated drawing speed of the original PC while driving (default 8, `0` = unpaced; see below) |
| `--bios-keys` | Original keyboard behaviour for driving: keys act only through key repeat (see below) |
| `--check` | Verify that `TDEGA.EXE` (`TDCGA.EXE` for CGA/Hercules) loads, then exit without opening a window |
| `--monitor COLOUR` | Hercules build only: phosphor colour, `green` (default), `amber` or `white` |

Alt+Enter toggles fullscreen. The window keeps the 4:3 aspect of the original monitor. The Hercules build
shows the card's 640×300 picture.

## Controls (from the original)

* Arrow keys / numeric keypad: steer, accelerate, brake and shift through the gear gate, as in the original.
* Esc: quit the current drive or menu.
* Ctrl-J / Ctrl-K: joystick / keyboard control. A connected gamepad acts as the joystick (left stick or
  D-pad, A = fire).
* Ctrl-Q / Ctrl-S: sound off / on.


## Changes from original

* **Held-key driving:** arrows / keypad and A / Z are read while held, not only through key repeat
  (`--bios-keys` restores the original).
* **Frame rate:** the driving loop is paced to 8 fps, so frame-counted behaviour (gear-shift panel, traffic
  randomness, crash animation) matches a 1987 PC (`--frame-rate`).
* **Removed:** copy protection and the TD.EXE launcher password (TDCGA.EXE never asked for it).
* **Graphics modes:** one executable per mode instead of the `TD.EXE` menu (see Build).
* **Missing SCORES:** starts with an empty table instead of exiting.
* **Extended-ASCII keys:** ignored instead of crashing.

## Layout

See `tdport/PORTING.md` for the architecture and porting rules. In short:
* `tdport/src/mem.*` emulates the real-mode address space the game ran in.
* `tdport/src/host.*` wraps SDL3.
* `tdport/src/platform/` holds the graphics layers (EGA `gfx.c`, CGA/Hercules `gfx_cga.c`), timer/sound,
  input and resource layers.
* `tdport/src/game/` holds game flow, scene rendering and simulation, shared by all builds.

Reverse-engineering tools, specs and file formats are in `tools/`, `port/` and `FORMATS.md`. `port/cga/`
documents TDCGA.EXE and how it differs from TDEGA.EXE.

## Support

https://buymeacoffee.com/krzysztofkania
