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
| `Cars/<car>.B` | Car record, the DOS `.BIN` layout with 16-bit fields big-endian (1238 bytes; `Vette.B` is 816, like the DOS `Game/VETTE.BIN`) |
| `Cars/<car>.SS` | Spec-sheet animation script (text, like DOS `.SS`) |
| `Cars/<car>.ST`, `<car>Dash` | IFF ILBM, 320×200, 5 planes: spec sheet, dashboard |
| `Cars/<car>.ST.Shp`, `<car>Dash.Shp`, `<car>Gas`, `<car>Logo`, `<car>Logo.Shp`, `<car>.SB` | `Pckd` containers (below) |
| `Cars/<car>Logo.Pal` | Text palette, one 12-bit `RGB` hex value per line |
| `Pics/title2`, `Title3`, `Title4` | IFF ILBM title screens |
| `Pics/Road.Shp` | Shape archive: a directory of 4-character names (`bug0`, `cld0`, ...) like the DOS PES archives |
| `Pics/TitleCar.Shp`, `EndGame`, `Endgame.Shp`, `Gas.Shp` | `Pckd` containers |
| `Sfx/*` | 8-bit signed samples: header `u32` length, `u16` rate (Hz; below 100 read as kHz; Accolade 10000, Bump 9400), no loop fields, then data |
| `Songs/*.Iff.Sng` | IFF SMUS scores (`TestDrive`, `Test2`, `TestGas`, `EndSuccess`, `Loser`) |
| `Songs/Drum`, `Drum2`, `BuzzSynth` | Instrument samples, the same 6-byte header as `Sfx` (no loop fields; the looping is chosen by the code) |
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
The image lays the overlays out side by side. The overlay manager (0x168A4) loads a node on its first call and
patches its stubs to `jmp abs.l`; it never unloads by itself, but `main` calls `overlay_unload` 0x162E0 with the
overlay-1 stub before each game and the overlay-2 stub after it (freeing the hunks and restoring the stubs).
`show_view` 0x1C62E lives in overlay 1 and is called during the drive, so both overlays are then resident
together. None of this matters to the port, which links everything.

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
with extent, callers/callees, globals read/written, strings, library calls (LVO) and constants. The index misses
code reached only through an address: 17 functions (VBL and audio interrupt servers, the input handler, the
RawDoFmt and TDScroller callbacks, the Road Drawer entry, their local call targets, the overlay manager and two
glue bodies reached by `jmp`; the Ghidra script adds them, see `tools/ghidra/AmigaTd.java`), plus 11 secondary
entries and branch-only asm routines listed in `coverage.txt`. Landmarks:

| Address | What |
|---|---|
| 0x163B0 | Aztec C startup (clears BSS, saves exec base, checks for a 68881, opens dos.library) |
| 0x10346 | Reads `Cars.Txt` |
| 0x11554 | Opens intuition.library and graphics.library |
| 0x1180E | Installs the `Ticks VBLInt` vertical-blank server (60 Hz NTSC in the port, see *Decisions*) |
| 0x11ABE-0x11C96 | trackdisk.device / disk.resource, own disk interrupt: the copy protection |
| 0x12304, 0x126AE, 0x12616 | Sound effects: init (installs the `Sfx VBLInt` server 0x126AE and the level-4 audio handler 0x12616) |
| 0x1278C, 0x12A54, 0x12826-0x12EF6 | Songs: init, `Song VBLInt` server 0x12A54, SMUS loading and the five songs |
| 0x13028, 0x1313E | HighScores load and save |
| 0x13708, 0x13BD8 | High-score entry ("You have qualified as one of Test Drive's best drivers") and table |
| 0x1444C | Stage results ("Your average speed was %ld and it took you ...") |
| 0x147E4 | Gas station |
| 0x154E4 | input.device / console.device |
| 0x1AED0 | Overlay 1 entry: title sequence (`pics/TitleCar.Shp`, `sfx/Accolade`, `pics/Title2..4`, `sfx/Starter`) |
| 0x1BDCA, 0x1C244 | Showroom / spec sheet (`%s.ST`, `%s.SB`, `%s.ST.Shp`, `%s.SS`) |
| 0x1C83C, 0x1C820 | `TDScroller` task: start, entry |
| 0x1C900 | Overlay 2 entry: the drive |
| 0x1CF76, 0x1D484, 0x1D5C8 | Ending, "Pulling into the gas station / dealership", play-again menu |
| 0x24ACA | Stage loading: "Loading Game...", `Pics/Road.Shp`, `%s.b`, `%sDash.Shp`, `%sDash` |
| 0x24E94, 0x24F9A, 0x1D484 | `Road Drawer` task: start, entry, body |
| 0x26B7A | Loads the sound effects (`sfx/Radar`, `TheEngine`, `TheTurbo`, `Squeal`, `Bump`) |

## Findings that shape the port

* **Same game, same data layouts, partly new code.** The car record is the DOS `.BIN` byte for byte apart from
  endianness and a few values, the road data are byte-identical, and the screens, files and messages follow the
  DOS game, so the DOS specs in `port/spec/` are the map for naming. The drive itself is largely new,
  hand-written 68000 assembly with register arguments: a different road renderer, lateral model, grip and hazard
  handling, and units (see *Specs*). Arithmetic is 16-bit `int` in both.
* **The OS is used for the display structure, the hardware for the drawing.** exec (memory, signals, tasks,
  devices, interrupts), graphics.library for the two double-buffered Views (`InitView`/`MakeVPort`/`MrgCop`/
  `LoadView`, `LoadRGB4`, user copper lists, `WaitTOF`, `BltBitMap`, `Text`, `Draw`), input.device and
  console.device for keys, intuition.library only for `CloseWindow`/`CloseWorkBench` (with the `p` argument) and
  `DrawImage` (stage results). Shapes are blitted by programming the blitter directly, and sound, sprites and the
  joystick go straight to the hardware: custom chips at `$DFF000` (blitter, DMACON 096, colour registers 180,
  sprites 120/140-14C, audio, DSKLEN 024, VHPOSR 006, JOY1DAT 00C) and the CIAs (`$BFE001` fire button; the
  filter bit is never written; `$BFD100` drive select). The port will emulate the effects of the custom chips and
  of the few graphics.library structures the game uses (Views, ViewPorts, copper lists), not reimplement AmigaOS.
* **Timing is the vertical blank** (three VBL servers: ticks, sound effects, songs), where DOS used a 100 Hz
  PIT tick. The port uses NTSC rates (60 Hz): see *Decisions* below.
* **Copy protection** reads the disk directly (0x11ABE-0x11C96): it measures a long track on cylinder 0 with raw
  DMA (sync 0x4489) and CRCs its own code; on failure it corrupts the `load_file` jump slot. The crack replaced the
  gap counting with the constants 0x3E0/0x3E8, which always fall in the accepted range 0x38E..0x44C
  (platform_video §4.16). The port drops it, as the DOS port does.

## Specs

Porting specs in `port/amiga/spec/`, in the `port/spec` format (`port/RE_GUIDE.md`): overview, function table
with DOS equivalents, globals, pseudocode from the disassembly, OS/hardware → SDL3 table, timing, differences
from DOS, open questions. Each has a `_symbols.csv`. Everything was re-read from `amigaidx dis`, because the
Ghidra decompile (`port/amiga/decomp/td.c`) drops stack arguments and hides the register arguments of the
hand-written overlay-2 assembly.

| Spec | Covers |
|---|---|
| `title_select.md` | Overlay 1: the title sequence (Title2 + bull + Accolade, Title4 + car drive-off, Title3 logo drop + KEYS), car selection and showroom (two ViewPorts, TDScroller task, `.ST`/`.SB` cache), the spec-sheet drive-away, `show_view` |
| `game_flow.md` | Aztec startup and `main` (argv dispatch, overlay unload, state machine), `Cars.txt`, HighScores (CRC-16), name entry, score table, credits, stage results and gas station, and in overlay 2 `run_game` (stages, lives, drive frame, stage end, crash, game over), scoring, stage load/unload, ending hand-off, play-again menu |
| `drive_sim.md` | Overlay-2 simulation: controls, shifting (incl. O-mode gate shifting in the VBL), engine, lateral physics and grip, road advance and objects, radar and police, traffic, stage road setup, RNG |
| `drive_scene.md` | Overlay-2 picture: the Road Drawer task, the new road walker and span fill, object queue and slot cars, clouds, bugs, cockpit overlays, hardware-sprite gauges and gear knob, copper palette split, crash, ending |
| `platform_video.md` | Root platform layer: display (two Views, ILBM + `CMP2`, dissolve, view copy), blitter model and shape blits, text, VBL timing, input (input.device handler, joystick), files and `Pckd`, memory, overlays, fixed-point helpers, Aztec runtime and library glue, copy protection |
| `platform_audio.md` | Sfx engine (4 Paula channels, VBL start, level-4 repeat counting), SMUS song player, drive engine/turbo/squeal/radar/bump sounds, Paula model for the port |

Merged in `symbols.csv` (kind, address, name, type, dos_equiv, owner, aliases, notes): **901 rows, 514
functions and 387 globals**, one row per address, owner = the spec whose scope covers it, other specs' names in
`aliases`. The conflicts found while merging and how they were settled are in `symbol_conflicts.txt`.

**Coverage** (`coverage.txt`): all **538** functions (the 521 of the index plus the 17 address-only functions the
Ghidra run added) are covered: 503 have their own symbol row and 35 are documented as groups (25 protection
internals, 10 unused C wrappers of the math cores). Owners: platform_video 315, drive_scene 101, platform_audio
40, drive_sim 30, game_flow 26, title_select 26. 11 further rows are secondary entries or branch-only asm the
index does not list. Of the 72 DOS functions in the game_flow / simulation / scene_render ranges, 57 have an
Amiga counterpart named in the specs; the other 15 (the DOS projection and span helpers, atan, the sim ISR exit,
the 40-unit look-ahead, `select_screen`, `car_data_ptr`, `wait_fire_button`, the sim key handler) have none,
because the Amiga design differs (see `coverage.txt`).

### Port-critical findings

**Architecture and timing**
- No simulation interrupt. The drive loop `run_game` 0x1C900 (main task, priority 4) runs one logic step per
  *drive frame* of at least 5 VBL: it calls `WaitTOF` (last + 5 − tick_count) times, with no catch-up. A second
  exec task, **Road Drawer** (priority −1, entry 0x24F9A, body 0x1D484), takes a Forbid/Permit snapshot of the sim
  state, draws straight into the back View and flips with `show_view`, as fast as the CPU allows. Port: one
  thread, a logic step every 5th VBL tick, render every host frame; the real A500 render rate is unmeasured.
- **The sim reads values the renderer computes**: the row-0 road half-widths D:0D94/D:0D96, the `car_x` snapshot
  D:289A, and the traffic lateral positions D:0CC2/D:0D28 used by the collision tests. The port must compute them
  every logic step even when nothing is drawn.
- All waits count VBLs (`tick_count` D:03D8, Ticks VBLInt 0x118B2, priority −80; 60 Hz in the port) or use dos
  `Delay` (1/50 s whatever the VBL rate). Gate shifting (O key) runs inside that VBL server and calls
  `engine_update` there every VBL.
- Stage time is counted in drive frames; the results show frames/12 as seconds. Par {700, 1100, 1200, 1100,
  1500}, "too slow" limit {3000, 2800, 3500, 4000, 4500} frames (= DOS STAGE_CONST_B × 12, a table DOS never
  reads); average speed below 50 does not end the run. A stage ends past len − 45, or within 80 units of it at
  ≤ 17 mph.
- `int` is 16-bit (Aztec C) as on DOS, but units are new: speed D:28A6 16.16 mph, road position D:28AE 16.16
  units (road moves speed>>6 per frame, about 1.35× DOS at the same mph), steering 16.16 degrees, lateral x
  + = right.

**Video**
- Two graphics.library Views (A/B, 320×200, 5 planes of 8000 bytes, 32 colours) used as double buffers; motion
  in the title and showroom comes from ViewPort DxOffset/DyOffset/RyOffset. Emulate a display list per View:
  ViewPorts (incl. the 640-wide 2-plane hires band of the showroom), user copper lists (drive palette split at
  line 0x75, the `CMP2` second palette of every `<car>Gas` picture at line 110, per-row logo palettes in the
  score table) and **hardware sprites** (needles 0-3, gear knob 4-7, wheel-marker dot on 7).
- Blitter: the shape routines 0x10D14-0x11552 program the custom chips directly (cookie-cut 0x0FCA, copy
  0x05CC, masked copy 0x07CA, shifted XOR 0x076A, aligned XOR 0x0B5A, one-plane clear/fill), always 5 planes
  from D:0BEC, clipped to D:0380..D:0386 in 16-pixel columns. A small blitter emulator on `mem[]` is the
  recommended port route.
- The road renderer is a new design (fixed-point walker over 40 rows, 30 for the mirror; per-row blitter spans;
  an object queue of up to 199 entries drawn LIFO). The road data are byte-identical to DOS; the DOS "flag" byte
  is a width code.
- The dissolve 0x109D0 (8 passes, rows in 7r mod 200 order) is CPU-bound, with no frame sync.

**Audio**
- Paula: 4 channels of 8-bit samples; the sfx engine starts DMA on the next VBL (at least 2 ticks after a stop)
  and counts repeats in the level-4 interrupt. The SMUS player uses a fixed tempo (6 VBL per 16th), instruments
  hard-coded per track, waveform notes 17/16 sharp, notes cut one tick early, songs loop. Periods use the NTSC
  clock constant 0x369E99. Engine, turbo and squeal loops are updated once per drive frame.

**Input**
- Driving is joystick only (JOY1DAT + CIA-A fire, DOS 0..8 clockwise direction code). Keys go through an
  input.device handler (priority 127): P pause, M music, S sound, D gearbox display, O gate shifting, Ctrl-R
  (key 0x12) abort (from a game back to car selection, from car selection back to the title). In car selection stick down = next car (the reverse of DOS).

**Things to drop**
- Copy protection (0x10588, 0x11954-0x11DD3) and the crack's constants; the overlay manager; closing the CLI
  window and Workbench (`p` argument); the dead $BFF002/$BFF096 writes; the CIA-B DDRA/PRA writes in `main`
  (purpose unknown).

**Original bugs: fixed by default, `--original-bugs` restores them**

The port fixes the defects below. Started with `--original-bugs` (the launcher's **Original bugs** option), it
behaves exactly like the original instead. Each fix sits behind one runtime flag (`g_original_bugs`) at the
place the spec describes, so both behaviours stay in the code:

| # | Bug in the original | Where | Fix |
|---|---|---|---|
| 1 | Probability-gated traffic never spawns: the spawn code indexes the slot with the full object byte, so those objects (86 of 148) write stray words past the slot array (D:0D72, D:0D76, D:0D7A, the renderer's scanline table) | drive_sim | index with the slot number, so the cars spawn and nothing is overwritten |
| 2 | Rows 3..6: same-direction slot cars 0/2/3/4 get a garbage x (a product used without its `swap`), which hides near cars | drive_scene | use the high word, as the other rows do |
| 3 | The `Pckd` decoder never writes the last unpacked byte (VetteDash.Shp, Endgame.Shp, Gas.Shp) | platform_video | write it |
| 4 | The play-again menu timeout is dead (reversed compare) | game_flow | the compare the code intends |
| 5 | `fill_row_span` overwrites whole 16-pixel words at the span ends | drive_scene | mask the end words |
| 6 | Two-line trapezoids use the previous row's step | drive_scene | use the row's own step |
| 7 | `lateral_physics` can overflow `divs` at very low speed on a curve (the 68000 leaves the operands unchanged) | drive_sim | clamp the quotient |
| 8 | With sound off at stage start, squeal and turbo are still audible | platform_audio | S off at stage start starts no drive loops |
| 9 | The looped engine, turbo and squeal samples include their 6-byte headers (a click every loop) | platform_audio | loop from +6 |
| 10 | BuzzSynth waveform notes play 17/16 sharp (length 17, 16 bytes played) | platform_audio | period from the 16 bytes played |
| 11 | A `Cars.txt` last line without `\n` loses its last character | game_flow | keep it |
| 12 | The SMUS track tie flag is never reset between songs | platform_audio | clear the four tie flags whenever the song is parsed (start and every loop restart) |

Not bugs, kept in both modes: hazards affecting grip (80/60/80/75 %), the blown engine only after 10 frames over
the rev limit, Loser.Iff.Sng never played, EndSuccess track 2 on the Drum, the needles redrawn every frame (no
visible effect). Not applicable to the port: the O-mode VBL gear selection calling overlay code (there are no
overlays). Rossa and Lotus name a missing `fac7` shape: a data problem, the frame stays empty in both modes.

**Credits.** The first four credits lines are the crackers' ("Test Drive was Cracked by: ..."); the original
Amiga text is not in this dump. Deferred: to be decided later.

### Decisions

1. **NTSC.** The port runs the Amiga's clock at the NTSC rates: a 60 Hz VBL (so the drive frame of 5 VBL is
   12 Hz and the results' frames/12 are real seconds) and the NTSC Paula clock 3579545 Hz (the game's own
   constant 0x369E99). The evidence: frames/12 shown as seconds, the NTSC Paula constant, the per-tick
   torque/drag constants equal to DOS's (12.5 Hz), 200 lines being the NTSC full height, an American developer.
   `dos.library Delay` stays 1/50 s (it is not VBL-based). Every VBL count in the specs is converted at 60 Hz,
   except the song player: the songs' tempo matches PAL captures, so its server runs at 50 Hz (it skips every
   sixth VBL).
2. **Original bugs** are fixed, with `--original-bugs` to restore them (see above).
3. **Credits**: deferred.

### Blocking questions

1. **Real A500 timings** (emulator measurement): the Road Drawer's render rate (slides, bug spawn, cloud drift
   and the police flash advance per rendered frame), the dissolve duration (estimated 1.8 s reveal / 0.9 s to
   black by instruction count), whether the drive frame really stays at 5 VBL, and whether loops that rebuild a
   ViewPort every VBL (MakeVPort + MrgCop + LoadView) keep up.
2. **ViewPort placement** for negative DyOffset and large negative DxOffset under graphics.library 1.x, and what
   shows outside the ViewPort: needed for the title logo drop and the showroom drive-offs.
Not blocking but open: the unit relation between `car_x` and the road half-widths in the rumble/marker tests
(drive_sim §8), `D:0360` and other write-only globals, the O-mode VBL gear selection calling overlay code from
the interrupt outside the drive (a latent crash in the original), and FORMATS.md updates for its owner (the
`CMP2` chunk: word line + 32 RGB triplets, 100 bytes in every `<car>Gas`; car +17A/+324 direction 0 is a vertical
bar clipped from the top; the road record's byte 0 is a width code).

## Plan

1. **Formats** — done: `Pckd`, shape archives, shapes, ILBM, samples and the sfx engine, SMUS, `.SS`, the car
   record, HighScores, `Cars.txt`, `Logo.Pal` (`tools/amigares.py`, `FORMATS.md`). Left: the `CMP2` ILBM chunk
   is described only in platform_video.
2. **Decompilation** — done: `tools/ghidra/AmigaTd.java` → `port/amiga/decomp/td.c` (538 functions) and
   `td_globals_xref.txt`. The decompile drops stack arguments of many calls and hides asm register arguments, so
   the specs work from the disassembly.
3. **Mapping to DOS** — done: `dos_equiv` in every spec and in `symbols.csv`; `coverage.txt` lists the DOS
   functions without an Amiga counterpart; each spec has a *Differences from DOS* section.
4. **Specs** — done, with open questions: the six specs above (see *Decisions* and *Blocking questions*).
5. **Port** — `tdport-amiga` (`tdport/src/amiga`, CMake option `TDPORT_AMIGA`), in stages:
   1. *Framework* — done. `amem` loads `td` into a big-endian 68000 memory image laid out like `td.bin`
      (globals at `DATA_HUNK + D:xxxx`, names from `asymbols.h`, generated by `tools/gen_amiga_symbols.py`) and
      provides exec `AllocMem`/`FreeMem`; `ahost` is the SDL3 side (window, 60 Hz VBL with prioritised
      servers, stereo audio stream, raw keys, joystick in port 2, case-insensitive disk paths); `agfx` emulates
      graphics.library Views/ViewPorts/ColorMaps/user copper lists and composes the front View at 640×200;
      `paula` is the 4-channel mixer with per-pass reloads, audio interrupts and the A500 filters.
      `platform/` ports the root platform code (display init, `show_view`, ILBM with `CMP2`, view copy and
      dissolve, `mem_alloc`/`free_mem`, `load_file` with `Pckd` incl. bug 3, the Ticks VBL server, the
      input.device key queue with a USA keymap, the joystick). `adisk` reads the game files straight from the `.adf` (OFS/FFS)
      or from the extracted folder. `--check` verifies the image and unpacks all 34 `Pckd` files against their CRCs. `game/main.c` wraps a placeholder (title picture + Accolade sample).
   2. *Title and car selection* — done. `platform/audio.c` (sfx engine, SMUS player, bugs 10 and 12),
      `platform/blit.c` (blitter emulator and the shape routines), `arast.c` (RastPort drawing), `font8.c` (the 8×8
      cells of the CC BY "Amiga Topaz" recreation, rasterised by `tools/gen_font8.py`, in place of the ROM's
      topaz 8),
      `platform/text.c`, `platform/system.c` (rand16, poll_input), `game/title.c` (overlay 1; TDScroller runs
      synchronously), `game/cars.c` (Cars.txt, bug 11), `game/main.c` (main 0x10018 and high_scores 0x12F28).
      The later stages' functions are stubs in `game/stubs.c`.
   3. *The drive* — done. `game/sim.c` (drive_sim: controls, engine and gears, steering, grip and skids,
      traffic, police and radar; bugs 1 and 7), `platform/fixed.c` (sin/cos/abs/ldiv), `game/scene.c`
      (drive_scene: the road walker and mirror, object queue, clouds and bugs, cockpit, analog needles and the
      Corvette cluster, crash; bugs 2, 5 and 6) with hardware sprites added to `agfx.c`,
      `platform/audio_drive.c` (engine, turbo, squeal, bump, radar; bugs 8 and 9) and `game/drive.c`
      (run_game, stage load/unload, the stage clock and scoring, play-again menu; bug 4). The port is
      single-threaded: one rendered frame per 60 Hz tick, one simulation frame every 5th tick.
   4. *Game flow* — done. `game/scores.c` (the HighScores file and its CRC, name entry, the table with the
      per-car logo palettes, the credits) and `game/screens.c` (the scrolling stage results, the gas station
      with its `CMP2` palette, the dealership ending). Saved files go beside the disk image (`adisk_write`),
      which is never modified. No stubs are left.
