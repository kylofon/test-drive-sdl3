# Test Drive (1987) — SDL3 port

A faithful C reimplementation of the EGA version of Accolade / Distinctive Software's *Test Drive* (1987),
running natively on SDL3. It is not an emulator - the original data is not redistributed, and you need to get it yourself.

## Requirements

* Your game files in a folder. The port needs `TDEGA.EXE`, `CARS.TXT`, `SCORES`, `TDSND.SND`, the `*.PES`
  archives and the car `*.BIN` / `*.SS` files. `../Game` is used by default.
* CMake 3.24+, a C11 compiler and SDL 3. 

## Build

From this folder, in Git Bash or an MSYS2 MinGW64 shell:

```bash
export PATH="/c/msys64/mingw64/bin:$PATH"
cmake -S . -B build -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

## Run

```bash
./build/tdport.exe --game-dir ../Game
```

| Option | Meaning |
|---|---|
| `--game-dir DIR` | Folder with the original game files (default `Game`) |
| `--scale N` | Initial window size as a multiple of 320×240 (default 3) |
| `--frame-rate FPS` | Emulated drawing speed of the original PC while driving (default 8, `0` = unpaced; see below) |
| `--bios-keys` | Original keyboard behaviour for driving: keys act only through key repeat (see below) |
| `--check` | Verify `TDEGA.EXE` loads and exit, without opening a window |

Alt+Enter toggles fullscreen. The window keeps the 4:3 aspect of a 200-line EGA monitor.

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
* **Removed:** copy protection, the TD.EXE launcher password, and Hercules / CGA modes.
* **Missing SCORES:** starts with an empty table instead of exiting.
* **Extended-ASCII keys:** ignored instead of crashing.

## Layout

See `PORTING.md` for the architecture and porting rules. In short:
* `src/mem.*` emulates the real-mode address space the game ran in.
* `src/host.*` wraps SDL3.
* `src/platform/` holds the EGA graphics, timer/sound, input and resource layers.
* `src/game/` holds game flow, scene rendering and simulation.

## Support

https://buymeacoffee.com/krzysztofkania
