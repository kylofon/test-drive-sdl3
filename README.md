# Test Drive (1987) — SDL3

A faithful native port of Accolade / Distinctive Software's *Test Drive* (1987): the DOS release in EGA, CGA and
Hercules, and the Amiga release. Not an emulator. The original game files are not included.

## Features

* The DOS EGA, CGA and Hercules versions and the Amiga version, each its own executable.
* The original's 8 fps drawing speed while driving, so timing matches a 1987 PC.
* Driving keys read while held, not only through key repeat.
* Key bindings for the driving and game keys.
* Fixes to crashes and original bugs (see `CHANGELOG.md`; the Amiga bugs can be kept with `--original-bugs`).
* A launcher to pick the version, game folder, options and keys.

## How to play (Windows)

1. Put your original DOS game files in a folder named `Game`, and/or the Amiga disk image (`.adf`) in a folder
   named `Game Amiga`.
2. Place the program files next to them:

   ```text
   Test Drive\
   ├── Game\              <- DOS game files (TDEGA.EXE, TDCGA.EXE, CARS.TXT, SCORES, ...)
   ├── Game Amiga\        <- the Amiga disk image (.adf), or the files from it
   ├── Test Drive.exe     <- the launcher
   ├── tdport.exe, tdport-cga.exe, tdport-herc.exe, tdport-amiga.exe
   └── SDL3.dll and the other DLLs
   ```

3. Run `Test Drive.exe`, pick a version and options and press **Play**.

* The folder must be writable (high scores are saved in `Game`, and beside the Amiga disk image).
* If Windows says "Windows protected your PC", click **More info**, then **Run anyway**.
* Alt+Enter: full screen.
* Launcher settings: `%APPDATA%\Test Drive Launcher\settings.ini`.

## Requirements

* EGA: `TDEGA.EXE` and the `*.PES` archives. CGA and Hercules: `TDCGA.EXE` and the `*.CMP` archives. All three
  also need `CARS.TXT`, `SCORES`, `TDSND.SND` and the car `*.BIN` / `*.SS` files.
* Amiga: the disk image (`.adf`), or the files extracted from it (`td`, `Cars/`, `Pics/`, ...).
* To build: CMake 3.24+, C11, SDL 3; the launcher needs C++17 and wxWidgets 3.2.

## Build

In Git Bash or an MSYS2 MinGW64 shell:

```bash
export PATH="/c/msys64/mingw64/bin:$PATH"
cmake -S tdport -B tdport/build -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release \
      -DTDPORT_CGA=ON -DTDPORT_HERCULES=ON -DTDPORT_AMIGA=ON -DTDPORT_LAUNCHER=ON
cmake --build tdport/build
```

* Without options only `tdport.exe` (EGA) is built. `TDPORT_CGA`, `TDPORT_HERCULES`, `TDPORT_AMIGA` and
  `TDPORT_LAUNCHER` add `tdport-cga.exe`, `tdport-herc.exe`, `tdport-amiga.exe` and `Test Drive.exe`.
* The MSYS2 `SDL3.dll` also needs `libiconv-2.dll` from `C:\msys64\mingw64\bin`; the build copies both.

## Run

```bash
./tdport/build/tdport.exe --game-dir Game
```

| Option | Meaning |
|---|---|
| `--game-dir DIR` | Game files folder (default `Game`; Amiga: `Game Amiga`, the `.adf` or a folder) |
| `--scale N` | Window size, × 320×240 (default 3) |
| `--frame-rate FPS` | Drawing speed while driving (default 8, 0 = unpaced). DOS only |
| `--bios-keys` | Driving keys only through key repeat, as the original. DOS only |
| `--monitor COLOUR` | Phosphor colour: `green` (default), `amber` or `white`. Hercules only |
| `--original-bugs` | Keep the original's bugs instead of the fixes. Amiga only |
| `--keys NAME=CODE,...` | Key bindings (the launcher's Game settings > Key Bindings) |
| `--check` | Check that the game executable loads, then exit |

## Controls

* Arrows / keypad: steer, gas, brake and shift through the gear gate.
* A / Z: shift up / down (DOS). Space: fire, held to shift with Up / Down (Amiga).
* P pause, D gear box always shown, O gate shifting with the joystick. Esc: leave.
* Ctrl-J joystick, Ctrl-K keyboard, Ctrl-Q / Ctrl-S sound off / on (DOS). M music, S sound effects (Amiga).
* A gamepad acts as the joystick (left stick or D-pad, A = fire).
* The launcher's Game settings > Key Bindings changes the driving and game keys.

## Layout

* `tdport/src/` — the DOS port (`tdport/PORTING.md`); `tdport/src/amiga/` — the Amiga port.
* `launcher/` — the launcher (`launcher/README.md`).
* `port/`, `tools/`, `FORMATS.md` — reverse-engineering specs, tools and file formats (`port/amiga/README.md`
  for the Amiga release).

## License

MIT (`LICENSE`). The Amiga text uses the CC BY "Amiga Topaz" font by Patrick H. Lauke (`licenses/amiga-topaz/`).
*Test Drive* is © Accolade; its files are not included.

## Support

https://buymeacoffee.com/krzysztofkania
