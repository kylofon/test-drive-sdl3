# Test Drive (1987) — reverse engineering and SDL3 port

Reverse engineering of Accolade / Distinctive Software's *Test Drive* (DOS, EGA), and a native C11 + SDL3 port
that runs it from your own copy of the game.

## Layout

| Path | Contents |
|---|---|
| `tdport/` | The SDL3 port (see `tdport/README.md`) |
| `port/` | Specs, lookup tables and merged symbols used for the port |
| `tools/` | Extractors (sprites, road, cars, sound), EXEPACK unpacker, Ghidra scripts |
| `FORMATS.md` | File formats and data layouts |

Not in the repository: the game files (`Game/`), DOSBox, Ghidra/JDK, and generated output.

## Quick start

Needs your original game files in `Game/`, plus CMake, a C11 compiler and SDL 3 (for example MSYS2 MinGW64).

```bash
cd tdport
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
./build/tdport.exe --game-dir ../Game
```

Extract the graphics to PNG (Python 3 with Pillow and numpy):

```bash
python tools/tdres.py export Game/LOTUS.PES work/ega/LOTUS
```
