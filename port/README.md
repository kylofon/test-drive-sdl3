# Test Drive SDL3 port — gathered material

Everything needed to start a faithful SDL3 reimplementation of **TDEGA.EXE** (Test Drive, 1987, EGA build).
Start with this file, then `RE_GUIDE.md` (address conventions), then the four specs.

## Contents

| Path | What |
|---|---|
| `RE_GUIDE.md` | Address conventions (image offset / Ghidra `1000:xxxx` / `DS:xxxx`), subsystem split, spec format |
| `spec/game_flow.md` | `main`, screen state machine, intro, car select/showroom, stage loop wrapper, scoring, lives, SCORES, font, endings |
| `spec/simulation.md` | Timer-ISR simulation: input, shifting, engine/drivetrain, steering, road motion, look-ahead/spawn, traffic, police/radar, crashes, RNG |
| `spec/scene_render.md` | Frame composition, road projection (main + mirror), object/traffic scaling and ordering, cockpit/dashboard, crash and dealership sequences |
| `spec/platform.md` | Drawing targets and planar blitters, fills/lines/text/fades, video mode + palette, timer/PIT, speaker sound driver, keyboard/joystick, resource loader, C runtime map, copy protection |
| `spec/*_symbols.csv` | Per-spec symbol tables |
| `symbols.csv` | Merged: 579 symbols (260 functions, 319 globals); owner = spec owning the address range, other names kept as aliases |
| `symbol_conflicts.txt` | Addresses where specs chose different names |
| `spec/tables/*.json` | Lookup tables dumped from the data segment (projection, road width/depth, sine/tan, drag, gear deltas, trap/traffic speeds, RNG table, palettes, 8×8 font, note/engine divisors, sound effects, input maps, blit masks, CRT function list) |
| `decomp/tdega_ds.c` | Ghidra decompile, globals renamed to DS offsets |
| `decomp/tdega_named.c`, `decomp/tdega_named_ds.c` | Same 258 functions after applying `symbols.csv` to the Ghidra project (231 with real function names; remaining unnamed globals renamed to DS offsets) |
| `decomp/tdega_globals_xref.txt` | Every DS global → functions using it (unnamed decompile) |
| `decomp/tdega_named_globals_xref.txt` | Globals still without a name in the named decompile → functions using them |
| `tdega_functions.json/.csv` | Capstone index: extent, callers/callees, globals, strings, ints, ports |
| `sdl3_check/` | Verified toolchain: CMake + Ninja + MinGW gcc 16.2 + SDL 3.4.16, 320×200 indexed framebuffer, 4:3 letterbox |
| `../FORMATS.md` | File formats (PES/CMP/sprites, road data, car `.BIN`, `TDSND.SND`, SCORES) |
| `../tools/` | Extractors (`tdres.py`, `roadmap.py`, `cardata.py`, `sndplay.py`), `unexepack.py`, `x86dis.py`, `funcindex.py`, `merge_symbols.py`, `ghidra/*.java` |
| `../_tools/` | Ghidra 12.1.3, JDK 21, Ghidra project `ghidra_proj` (symbols applied) |

## Port-critical findings (from the specs)

**Architecture**
- Two execution contexts. The frame loop (`run_stage` 0x1DC0) renders freely. The simulation runs inside the int 8 handler `sim_timer_isr` 0x3B1F: the PIT is at ~100.04 Hz (divisor 0x2E97), the song player runs every tick, and the physics runs every 8th tick (12.5 Hz). Port as a fixed 100 Hz tick with a physics step every 8th; render once per host frame. `snapshot_sim_state` 0x2013 is the hand-off point.
- All physics constants are per 12.5 Hz tick. Speed is 8.8 fixed-point mph, and a road unit is 90 sub-units.
- `rand` mutates a 256-byte table in place (`tables/rng_table.json`). It is also called once per rendered frame, so spawn randomness depends on frame rate. Decide whether to reproduce that or fix the render rate.
- Screen timing in menus is n × 10 ms (timer ticks). Stage time advances once per 8 simulation ticks; the results screen shows that count ÷ 12 as seconds.

**Video**
- Emulate a **planar** framebuffer: 4 bit planes for the screen, plus RAM draw targets laid out like sprites with up to 4 planes. The game uses per-plane replace/OR/AND/XOR blits (24 blit entry points). Convert to indexed 8-bit only at present time.
- No page flipping and no retrace waits. The road window (rows 19–110) is drawn into a 320×112, 3-plane RAM buffer every frame and copied to screen planes 0–2. Plane 3 stays 1 from the screen clear, so on-screen index = v | 8. The dashboard is drawn directly on screen.
- Palette: mode 0Dh loads the stock palette, then `main` loads DS:00CC for the rest of the game (`00 01 02 03 04 05 07 16 00 10 06 12 13 14 11 17`).
- Sprite plane map: the low nibble of each byte is the destination planes for that stored plane; byte 0's high nibble clears planes, byte 1's high nibble sets or XORs them. There is no transparent colour: masks are AND-blitted, then the image is OR-blitted.
- Text uses an 8×8 font at DS:6B44 for characters 0x20–0x7C. Cells are opaque, and x snaps to multiples of 8.
- Divide overflow must return 0xFFFF: the int 0 hook's behaviour is relied on throughout the projection code.

**Audio**
- PC speaker only: PIT channel 2 plus port 61h. Songs are `TDSND.SND` bytecode, and effects/engine notes use divisor tables (`tables/note_divisors.json`, `engine_divisors.json`, `sound_effects.json`). Replace with an SDL_AudioStream square wave at 1193182 / divisor Hz, changing frequency on tick boundaries.

**Input**
- The keyboard is read through INT 16h only (no INT 9 hook), so steering only registers on BIOS key-repeat events. Choose between emulating typematic repeat (faithful) and a held-key mode.
- Joystick at 0xA12F, using the gear-shift node graph from the car `.BIN`. Map to SDL_Gamepad.

**Things to drop**
- Copy protection 0x8DC7–0x91CF: treat as passed.
- The launcher password `94857102387604294775` that TD.EXE passes as argv[1].
- The CGA and Hercules code paths.

**Faithful quirks worth keeping (or consciously fixing)**
- Removing the front same-direction traffic car copies twice the intended length, which can overwrite the radar trap and hazard slot. Keep DS:0945–0A14 as one contiguous byte array.
- Road edges are asymmetric (+0x264 / −0x236). Skid is checked only on unit crossings, using the steering angle.
- Negating a negative heading byte-by-byte produces asymmetric drift.
- Line drawing uses the wrong x step when starting outside the clip; there is a carry error at the left clip edge.
- The span interpolator uses 8-bit error terms; the wheel sine table is read one entry past its end.
- Hazards (oil/pothole/gravel) are purely visual.

## Consolidated open questions

1. Plane 3 in the road window relies on a map-mask setting inherited from earlier screens (likely, not proven). The mirror and wheel may draw into plane 3 inside their own rectangles.
2. Whether any XOR blit lands directly on screen at an x that isn't a multiple of 8 (candidate 0x7E7C).
3. `DS:790A == 2` subtracts 18 from the speedometer index (car index 2 = Porsche).
4. Traffic slot field +4 and slot 10; the D-key toggle; resource lookups at stage start via 0x94C7.
5. Which divisions in simulation and scene code actually overflow in normal play.
6. Exact row pattern of the 8-step wipe (0x768B) and the direction of the car-select slide.
7. The Corvette digital dash drawing path, and car `.BIN` fields +002/+006/+010 (unused by TDEGA).
8. DS:02B2 `{250,233,291,333,375}` is copied into a global that nothing appears to read.

Most of these are best settled by comparing the port against the original running in DOSBox (`../DOSBOX`).

## Suggested port layout

```
src/
  main.c          SDL3 init, fixed 100 Hz tick scheduler, host frame loop
  platform/       planar framebuffer + blits (platform.md §4), palette, text,
                  speaker synth (SDL_AudioStream), input (keyboard repeat, gamepad)
  res/            PES/CMP decoding (port of tools/tdres.py), archive lookup, car .BIN, SCORES
  sim/            simulation.md: tick, drivetrain, steering, road motion, spawn, traffic, police, rng
  render/         scene_render.md: projection, road/objects, mirror, cockpit
  game/           game_flow.md: screens, state machine, scoring
  data/           tables from spec/tables/*.json (generated headers)
```

Load the original game files at runtime rather than redistributing them.
