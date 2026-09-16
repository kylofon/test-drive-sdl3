# Reverse-engineering guide for the SDL3 port

Shared conventions for everyone writing port specs. Target: **TDEGA.EXE** (EGA build).

## Files

| Path | What |
|---|---|
| `work/TDEGA_unp.exe` | EXEPACK-unpacked MZ; image offsets exclude the MZ header (`tools/x86dis.py` strips it for you) |
| `port/decomp/tdega_ds.c` | Ghidra decompilation of every function, globals renamed to DS offsets |
| `port/decomp/tdega_globals_xref.txt` | For each DS global: which functions use it |
| `port/decomp/tdega_named.c` | Decompile after applying the merged `port/symbols.csv` names |
| `port/tdega_functions.json` | Capstone index: extent, callers/callees, DS reads/writes, strings, ints, ports per function |
| `tools/x86dis.py EXE dis OFF LEN` | Ground-truth disassembly when the decompile looks wrong |
| `FORMATS.md` | Already-decoded file formats, road data, car `.BIN`, sound, scores |
| `_tools/ghidra_proj` | Ghidra project (open with `_tools/ghidra_12.1.3_PUBLIC/ghidraRun.bat`, JDK in `_tools/jdk-21*`) |

## Addresses

* **Image offset** = offset into the unpacked load image. Code is 0x0000–0xC99F.
* Ghidra loads the image at segment `1000`: function `FUN_1000_2054` = image `0x2054`.
* **DGROUP** is segment `0x0C9A`, so `DS:xxxx` = image `0xC9A0 + xxxx`.
* In `tdega_ds.c` a global is written `<type>_DSxxxx`, e.g. `i_DS7478` (int at DS:7478),
  `b_DS0929` (byte), `pb_DS1E6D` (byte pointer). Offsets used through a register
  (`*(int *)(uVar6 + 0x18c5)`) are still raw DS offsets: that is DS:18C5 indexed by `uVar6`.
* Ghidra's `CONCAT11`, `._1_1_` etc. are byte-level artifacts of 16-bit code: simplify when writing specs.
* Memory model: small/near (one code, one data segment); far calls are rare (MS C runtime).

## Known so far (don't re-derive, cite FORMATS.md)

* 0x9E40 LZW decoder, 0x9CF9 RLE90 output, 0x9D64 input byte — PES loading.
* 0x2054 road renderer (40 rows), 0x2480 mirror view, 0x3FE8 forward motion/physics, 0x4241 look-ahead,
  0x467D object spawn dispatch, 0x2A4F sign drawing.
* 0x10E2 car `.BIN` loader into DS:268F; 0x8A3E sound tick, 0x8A0E queue song.
* 0x8DF1–0x91CF copy protection (drop it).
* Road stream DS:2D28–6360, record table DS:2B70, stage pointers DS:6361, sine table DS:22F2.
* Video: mode 0Dh set by 0x4D96 (called once from main at 0x56; it loads the stock palette DS:637C),
  then main at 0x5D calls 0x4D84 with DS:00CC — the remapped game palette used for the whole game
  (`00 01 02 03 04 05 07 16 00 10 06 12 13 14 11 17`). Timer int 8 hook ~0x4910/0x1F3E.
* 0x94AB: fatal error printf + exit.

## Subsystem split (by code address; use Ghidra's function boundaries)

| Spec file | Image range | Scope |
|---|---|---|
| `game_flow` | 0x0000–0x1F4D | `main`, launcher/mode detection, title/Accolade intro, car select, showroom and spec sheet, `.SS` animations, SCORES load/save/entry/table, credits, gas-station screen, stage results and scoring, ending (dealership, ticket, game over), "back to DOS" prompts |
| `scene_render` | 0x1F4E–0x3AFF | Stage start, per-frame scene composition, road renderer and mirror view, road-side objects/signs/posts/traffic drawing and scaling, scenery layers, cockpit overlay order, page flipping |
| `simulation` | 0x3B00–0x4940 | Main driving loop tick, input → steering/throttle/brake/shift (shift-gate graph), engine/torque/drag/speed, skid and crash, road look-ahead and object spawning, traffic AI, police/radar/tickets, hazards, collisions, gauges and dashboard updates, time/score counters, in-game sound triggers |
| `platform` | 0x4941–0xC99F | EGA primitives and planar blitters (plane map, masks, clipping, row table), video mode/palette/Hercules/CGA branches, keyboard (int 9 / int 16h) and joystick, timer ISR (int 8, PIT rate), speaker sound driver, PES/CMP loaders and memory management, copy protection (document briefly only), MS C runtime (just identify which functions are library code) |

Ranges are approximate: if a function clearly belongs to another subsystem, list it in your table with
a "see `<spec>`" note instead of analysing it in depth. When you depend on another subsystem's function,
use its address and a descriptive name, and note it under Open questions if unsure.

## Deliverable format (one file per subsystem: `port/spec/<subsystem>.md`)

1. **Overview** – what the subsystem does, in a few paragraphs, with a call graph of its main functions.
2. **Function table** – `image addr | proposed name | signature | one-line purpose | confidence`.
   Confidence: `verified` (checked against disassembly/data), `likely`, `guess`.
3. **Globals table** – `DS offset | proposed name | type/size | meaning | written by | read by`.
4. **Pseudocode** – clean C for every non-trivial function, faithful to the original arithmetic
   (integer widths, signedness, shifts, overflow). Keep original constants in hex with a comment.
5. **Hardware/DOS dependencies** – each interrupt, port, BIOS call, direct video memory access, with the
   SDL3 replacement.
6. **Timing** – what runs per frame vs per timer tick, tick rates, and anything frame-rate dependent.
7. **Open questions** – what couldn't be resolved.

Also write `port/spec/<subsystem>_symbols.csv` with `kind,address,name,type,notes`
(`kind` = `func` or `global`; addresses as `0x2054` for functions and `DS:18C5` for globals),
so the symbol sets can be merged into one table and applied back to Ghidra.
