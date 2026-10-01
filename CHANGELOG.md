# Changelog

## 0.3.0

- The Amiga version (`tdport-amiga.exe`): the whole game, run from the disk image (`.adf`) directly.
- Amiga: the original's bugs are fixed by default; `--original-bugs` keeps them.
- Launcher (`Test Drive.exe`): pick the version, game folder and options, then Play.
- Launcher: menus (File > Preferences with Always on top, Game settings, About).
- Launcher: Game settings > Key Bindings; the game applies them while driving (`--keys`).
- The picture is scaled with pixel-art sampling, so every source pixel has the same size.

## 0.2.0

- CGA and Hercules builds (`tdport-cga.exe`, `tdport-herc.exe`), ports of `TDCGA.EXE`.
- Hercules monitor colour (`--monitor green|amber|white`).
- `libiconv-2.dll`, which `SDL3.dll` needs, ships with the game.

## 0.1.0

- First release: the EGA version (`tdport.exe`).
- Driving keys are read while held (`--bios-keys` for the original's key repeat).
- The original's 8 fps drawing speed while driving (`--frame-rate`).
- Removed: copy protection and the `TD.EXE` password.
- A missing `SCORES` file starts an empty table instead of exiting.
- Extended-ASCII keys are ignored instead of crashing.
