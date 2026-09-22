# Test Drive (Amiga) — reverse-engineering notes

Groundwork for `tdport-amiga`, a faithful SDL3 reimplementation of the Amiga release, alongside the DOS ports.
The only dump available is a cracked disk, `Test_Drive_1987_Accolade_cr_DF_TKT.adf` (bootblock by the Swiss
Cracking Association); the game has no other surviving source.

## Getting the files

```bash
python tools/adf.py Test_Drive_1987_Accolade_cr_DF_TKT.adf list
python tools/adf.py Test_Drive_1987_Accolade_cr_DF_TKT.adf extract work/amiga/disk
python tools/hunk.py work/amiga/disk/td info
python tools/hunk.py work/amiga/disk/td image work/amiga/td.bin      # flat relocated image, base 0x10000
python tools/amigaidx.py work/amiga/disk/td map                     # hunks, A4, call table
python tools/amigaidx.py work/amiga/disk/td dis 1aed0 0x100          # annotated disassembly
python tools/amigaidx.py work/amiga/disk/td index port/amiga/td_functions
```

The disk is a plain AmigaDOS OFS volume, "TEST DRIVE". `S/Startup-Sequence` runs `KickRAMTest`, adds the
slow RAM at F80000-FBFFFF when present, 20 buffers for df0:, then `td >nil: p`.

| Path | What |
|---|---|
| `td` | The game, 90112 bytes (see below) |
| `Cars.txt` | Car count, then one path per car: `5`, `cars/P911t`, `cars/Rossa`, `cars/Lotus`, `cars/Countach`, `cars/Vette` |
| `Cars/<car>.B` | Car record, the DOS `.BIN` layout with 16-bit fields big-endian (1238 bytes; `Vette.B` is 816) |
| `Cars/<car>.SS` | Spec-sheet animation script (text, like DOS `.SS`) |
| `Cars/<car>.ST`, `<car>Dash` | IFF ILBM, 320×200, 5 planes: spec sheet, dashboard |
| `Cars/<car>.ST.Shp`, `<car>Dash.Shp`, `<car>Gas`, `<car>Logo`, `<car>Logo.Shp`, `<car>.SB` | `Pckd` containers (below) |
| `Cars/<car>Logo.Pal` | Text palette, one 12-bit `RGB` hex value per line |
| `Pics/title2`, `Title3`, `Title4` | IFF ILBM title screens |
| `Pics/Road.Shp` | Shape archive: a directory of 4-character names (`bug0`, `cld0`, ...) like the DOS PES archives |
| `Pics/TitleCar.Shp`, `EndGame`, `Endgame.Shp`, `Gas.Shp` | `Pckd` containers |
| `Sfx/*` | Raw 8-bit signed samples: `.L` length, `.W` rate in Hz (Accolade 10000, Bump 9400), then data |
| `Songs/*.Iff.Sng` | IFF SMUS scores (`TestDrive`, `Test2`, `TestGas`, `EndSuccess`, `Loser`) |
| `Songs/Drum`, `Drum2`, `BuzzSynth` | Instrument samples (header like `Sfx`, plus loop fields) |
| `HighScores` | Text, three lines per entry: name, score, car path |

`Pckd` is the DOS `.PES` container big-endian (ARC methods 4 and 8 in use), shape archives have the DOS archive
layout, and ILBM is standard: see the Amiga section of `FORMATS.md` and `tools/amigares.py`.

## The executable

An overlaid AmigaDOS load file built with **Manx Aztec C** (small code and data model, 16-bit `int`):

| Hunk | Kind | Image address | Size | Contents |
|---|---|---|---|---|
| 0 | CODE | 0x010000 | 0x7C0C | Root: Aztec startup (entry 0x163B0), overlay manager (0x168A4), C library, platform code, songs, high scores, gas station, input |
| 1 | DATA | 0x017C10 | 0x32A4 (0x1E94 initialised) | Call table, initialised globals, then BSS |
| 2 | BSS | 0x01AEC0 | 4 | |
| 3 | CODE, overlay 1 | 0x01AED0 | 0x1A28 | Title, Accolade intro, car select, showroom and spec sheet |
| 4 | CODE, overlay 2 | 0x01C900 | 0xA61C | The drive: stage setup, road, dashboard, sound effects, stage results, ending |

The first long of hunk 0 is `bra` to the startup and the second is `0000ABCD`, the overlay supervisor's signature.
Overlays 1 and 2 are not resident at the same time; the image lays them out side by side.

**Addressing.** A4 = data hunk + 0x7FFE = 0x1FC0E. Globals are `d16(A4)` and are named **`D:xxxx`**, the offset
into the data hunk (the Amiga counterpart of `DS:xxxx`). The exec base is kept at `D:27DC` (`-$5822(a4)`),
graphics.library at `D:03D4` (`-$7C2A(a4)`).

**Calls.** Within a hunk: `bsr` / `jsr d16(pc)` (no relocations: overlay 2 has none at all). Between hunks: `jsr
d16(A4)` into the call table at the start of the data hunk:

* slots 0x17C10-0x17E91: 107 × `jmp abs.l` into the root;
* slots 0x17E94-0x17F4B: 23 × `bsr ovlmgr ; dc.w node<<8, offset` overlay stubs (3 into overlay 1, 20 into
  overlay 2), followed by `jmp 0x168A4` (the overlay manager).

`amigaidx.py` resolves both kinds, so calls show their real targets.

**String literals** are in the code hunks, referenced PC-relative (`pea $1b262(pc)`).

## Function index

`td_functions.json` / `.csv`: 521 functions (355 root, 23 overlay 1, 143 overlay 2), about 17,900 instructions,
with extent, callers/callees, globals read/written, strings, library calls (LVO) and constants. Landmarks:

| Address | What |
|---|---|
| 0x163B0 | Aztec C startup (clears BSS, saves exec base, checks for a 68881, opens dos.library) |
| 0x10346 | Reads `Cars.Txt` |
| 0x11554 | Opens intuition.library and graphics.library |
| 0x1180E | Installs the `Ticks VBLInt` vertical-blank server (50 Hz on PAL) |
| 0x11ABE-0x11C96 | trackdisk.device / disk.resource, own disk interrupt: the copy protection |
| 0x12304 | `Sfx VBLInt` server (sound effects) |
| 0x1278C, 0x12826-0x12EF6 | `Song VBLInt` server, SMUS loading and the five songs |
| 0x13028, 0x1313E | HighScores load and save |
| 0x13708, 0x13BD8 | High-score entry ("You have qualified as one of Test Drive's best drivers") and table |
| 0x1444C | Stage results ("Your average speed was %ld and it took you ...") |
| 0x147E4 | Gas station |
| 0x154E4 | input.device / console.device |
| 0x1AED0 | Overlay 1 entry: title sequence (`pics/TitleCar.Shp`, `sfx/Accolade`, `pics/Title2..4`, `sfx/Starter`) |
| 0x1BDCA, 0x1C244 | Showroom / spec sheet (`%s.ST`, `%s.SB`, `%s.ST.Shp`, `%s.SS`) |
| 0x1C83C | `TDScroller` |
| 0x1C900 | Overlay 2 entry: the drive |
| 0x1CF76, 0x1D484, 0x1D5C8 | Ending, "Pulling into the gas station / dealership", play-again menu |
| 0x24ACA | Stage loading: "Loading Game...", `Pics/Road.Shp`, `%s.b`, `%sDash.Shp`, `%sDash` |
| 0x24E94 | `Road Drawer` |
| 0x26B7A | Loads the sound effects (`sfx/Radar`, `TheEngine`, `TheTurbo`, `Squeal`, `Bump`) |

## Findings that shape the port

* **Same game, same data layouts.** The car record is the DOS `.BIN` byte for byte apart from endianness and a
  few values, and the screens, files and messages follow the DOS game. The Amiga code is very likely compiled from
  the same C design, so the DOS specs in `port/spec/` are the map for naming and checking the Amiga functions.
  Arithmetic is 16-bit `int` in both.
* **Little use of the OS.** Library calls are few: exec (memory, signals, tasks, devices, interrupts), a handful
  of graphics.library calls through Aztec glue (`BltBitMap` -30, `Text` -60, and a few others),
  input.device and console.device (intuition.library is opened, but no call to it has been found yet). Most of the display and sound work goes straight to the hardware: custom chips at
  `$DFF000` (DMACON 096, colour registers 180, sprites 120/140-14C, DSKLEN 024, VHPOSR 006, JOY1DAT 00C) and the
  CIAs (`$BFE001` fire button and filter, `$BFD100` drive select). The port will emulate the effects of the
  custom chips the game uses (playfield/bitplanes, copper, blitter, audio DMA), not reimplement AmigaOS.
* **Timing is the 50 Hz vertical blank** (three VBL servers: ticks, sound effects, songs), where DOS used a 100 Hz
  PIT tick. Which PAL/NTSC rate the game assumes needs checking.
* **Copy protection** reads the disk directly (0x11ABE-0x11C96). This dump is cracked; how the crack bypasses it
  is still to be checked. The port drops it, as the DOS port does.

## Plan

1. **Formats** — done: `Pckd`, shape archives, shapes, ILBM (`tools/amigares.py`, `FORMATS.md`). Still to do:
   SMUS and the instrument/sfx headers, the `.SS` script, and the car record differences against the DOS
   field table.
2. **Decompilation** — import `work/amiga/td.bin` into Ghidra (68000, base 0x10000, A4 = 0x1FC0E as register
   context, call-table slots labelled) and export a decompile with globals named `D:xxxx`, like
   `port/decomp/tdega_ds.c`.
3. **Mapping to DOS** — match Amiga functions to the DOS specs (strings, constants, call shape, globals) and write
   `port/amiga/symbols.csv`; list where the Amiga game differs.
4. **Specs** — for what the DOS specs don't cover: the Amiga platform layer (display/copper/blitter, audio and
   SMUS player, input, VBL timing, file loading), in the `port/spec` format.
5. **Port** — `tdport-amiga`: the 68000 memory image in a big-endian `mem[]`, globals at their `D:xxxx` offsets,
   game functions ported to C one by one, the custom-chip effects emulated host-side, SDL3 through the shared
   `host.c` (adding sample-based audio). Built by the same CMake project and picked from the launcher.
