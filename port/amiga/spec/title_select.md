# title_select — Test Drive (Amiga) `td`, overlay 1 (0x1AED0–0x1C8F8)

Porting spec for the title sequence, car selection, the showroom (car picture and spec sheet) and the
showroom drive-away. Conventions: `port/RE_GUIDE.md` and `port/amiga/README.md`. Functions are named by image
address (td image, base 0x10000). Globals are `D:xxxx`, offsets into the data hunk (A4-relative displacement
d = `D:(0x7FFE + d)`). `int` is 16 bits (Aztec C), `long` 32 bits, all data big-endian.

Sources: the annotated disassembly (`tools/amigaidx.py work/amiga/disk/td dis 1aed0 0x1a28`, kept as
`work/amiga/scratch/title_select/ov1.dis`) and the Ghidra output `port/amiga/decomp/td.c`. The Ghidra output
**drops most stack arguments** of Aztec calls (for example `FUN_1B396()` really takes the TitleCar archive,
`FUN_10E3A()` takes four arguments). Every call, argument order and constant below was read from the
disassembly. DOS references are to `port/spec/game_flow.md` and the merged `port/symbols.csv`.

---

## 1. Overview

Overlay 1 holds the out-of-game screens that `main` (0x10018, see game_flow) runs before a drive:

* **Title sequence** `run_intro` 0x1AED0 (DOS `run_intro` 0x037A). It shows three IFF ILBM pictures and one
  shape archive (`pics/TitleCar.Shp`) in a fixed order:
  1. `Pics/title2`, the "Accolade presents" screen (repainted by the crackers on this dump), dissolved in, then
     the `bull` bar slides in under it (0x1B2B2), then the `sfx/Accolade` sample plays.
  2. `Pics/Title4`, the side view of the car. The screen dissolves to black and then to Title4. `sfx/Starter`
     starts, and 113 VBLs later the window animation plays and the car drives off to the left (0x1B396).
  3. `Pics/Title3`, the "TEST DRIVE" logo. The whole picture drops in from the top with damped bounces
     (0x1B62E). Then the `KEYS` shape (the key fob) is dissolved in. After 300 VBL (5 s) the screen dissolves to black.
  It returns −1 when it runs to the end (main then shows the high-score table) and 1 when the player
  interrupts it with fire or Ctrl-C (main then goes to car selection).
* **Car selection** `car_select` 0x1B8E6 (DOS 0x098C). It rebuilds the display as two viewports per view:
  a 320×88 lowres 5-plane band on top for the car picture (`<car>.ST`, an ILBM) and a 640×111 hires 2-plane
  band from line 89 for the spec sheet (rows 89–199 of `<car>.SB`, a hires ILBM). The joystick moves between
  cars. Each change scrolls the old picture out in a separate exec task, **TDScroller** (0x1C83C), while the
  main task loads and decodes the next car into the hidden view, then scrolls the new picture in. Fire selects
  the car and plays the **showroom drive-away** (0x1C244, DOS `showroom_drive_away` 0x0D75), which is driven by
  the `<car>.SS` script and the `<car>.ST.Shp` shapes.
* **Display model.** Everything is drawn through two graphics.library `View`s, D:293E and D:2950, used as double
  buffers. `show_view` 0x1C62E does the `LoadView` and records which view is on screen (D:24CE) and which one
  is hidden (D:24C8). Animations are done with the blitter (root blit helpers), and scrolling is done by
  changing ViewPort offsets (`DxOffset`, `DyOffset`, `DHeight`, `RasInfo.RyOffset`) and rebuilding the copper
  lists (`MakeVPort`/`MrgCop`/`LoadView`). Screen changes use a bitplane dissolve (root 0x109D0).

`show_view` 0x1C62E lives in overlay 1 but the whole game uses it: root (0x11756, 0x13708, 0x13A9E, 0x13BD8,
0x147E4) and overlay 2 (0x1C900, 0x1CF76, 0x1D484, 0x1D5C8, 0x1FBD8, 0x24ACA) call it through the overlay stub
at 0x17EA4 (node 1, offset 0x175E). The overlay manager (0x168A4) loads a node on its first call and then
patches that node's stubs into `jmp abs.l`. The manager itself never unloads, but `main` does: it calls
`overlay_unload` 0x162E0 (game_flow / platform_video) with the overlay-1 stub before each game (0x10270) and the
overlay-2 stub after it (0x102A8), which frees the node's hunks and restores its stubs to `bsr ovlmgr`. During a
drive the first `show_view` call reloads overlay 1, so both overlays are then resident together. (Corrected in
the merge; an earlier version of this spec said nothing is ever unloaded.)

### Call graph

```
main 0x10018 [game_flow]
 ├─ run_intro 0x1AED0
 │   ├─ intro_accolade_bull 0x1B2B2
 │   ├─ intro_testdrive_car 0x1B396 ── res_find_list 0x10B22 (root, only caller)
 │   ├─ intro_testdrive_logo 0x1B62E
 │   └─ show_view 0x1C62E ── LoadView glue 0x17AAA (root, only caller)
 └─ car_select 0x1B8E6
     ├─ showroom_display_init 0x1BA7C ── colormap_clear 0x1C15C
     ├─ show_car 0x1BDCA
     │   ├─ start_scroller 0x1C83C ──(AddTask "TDScroller")──> scroller_task_entry 0x1C820
     │   │                                                        ├─ scroll_out_down 0x1C682   (dir +1)
     │   │                                                        └─ scroll_out_up   0x1C76A   (dir −1)
     │   ├─ load_file_retry 0x1BD9C ── car_pics_free_all 0x1BD14
     │   ├─ ilbm_to_view 0x1063A [platform_video]   (.ST → top viewport)
     │   ├─ sb_load_ilbm 0x1BF40 ── sb_parse_ilbm 0x1BF8E ── sb_decode_body 0x1C068   (.SB → hires viewport)
     │   ├─ scroll_in_up 0x1C700 (dir −1) / scroll_in_down 0x1C7CC (dir +1) / show_view (dir 0)
     ├─ car_pics_free_all 0x1BD14
     ├─ showroom_drive_away 0x1C244 ── fade_plate_colours 0x1C190 ── wait_frames 0x1C22A
     └─ showroom_display_free 0x1BC64
```

### Screen flow inside overlay 1 (from main's point of view)

```
main: song TestDrive (0x12E12) ─> run_intro
        -1 (ran to the end)          -> high scores (game_flow)
         1 (fire / Ctrl-C / fire held at entry) -> song stop, car selection
main: song Test2 (0x12E58), reload Cars.txt ─> car_select
        idx >= 0                   -> drive-away already played; demo_mode = 0; game
        -1, D:0346 set             -> demo_mode = 1, back to run_intro
        -1 otherwise (timeout/end of attract list) -> demo_mode = 1, random car (rand16 % g_numCars), game
        Ctrl-C (quit_requested)    -> exit
```
(The main side is owned by game_flow; it is summarised from `FUN_10018` only to show the return-value contract.)

---

## 2. Function table

### 2a. Functions in this subsystem

| Address | Name | Signature | Purpose | DOS equivalent | Confidence |
|---|---|---|---|---|---|
| 0x1AED0 | `run_intro` | `int (void)` → −1 complete, 1 interrupted | Title sequence: Title2 + bull + Accolade, Title4 + car, Title3 logo + KEYS | 0x037A `run_intro` (covers 0x03F4/0x051B/0x0792 too) | verified |
| 0x1B2B2 | `intro_accolade_bull` | `void (Archive *titleCar)` | `bull` bar slides from x=0 to its x (240) in 4-px steps, one step per VBL | 0x03F4 `intro_accolade` (bull loop only) | verified |
| 0x1B396 | `intro_testdrive_car` | `void (Archive *titleCar)` | Window animation, then the car drives off left by moving the ViewPort | 0x051B `intro_testdrive_car` | verified |
| 0x1B62E | `intro_testdrive_logo` | `void (Archive *titleCar)` | Title3 drops with damped bounce (ViewPort DyOffset), then KEYS shape dissolves in | 0x0792 `intro_testdrive_logo` | verified |
| 0x1B8E6 | `car_select` | `int (void)` → car index, −1 | Showroom loop: joystick up/down, fire selects, timeouts, attract cycling | 0x098C `car_select` | verified |
| 0x1BA7C | `showroom_display_init` | `void (void)` | Adds a 640×111 hires 2-plane ViewPort under a 320×88 top ViewPort in both views | — | verified |
| 0x1BC64 | `showroom_display_free` | `void (void)` | Removes the hires ViewPorts, restores DHeight 200, frees planes/colormaps/copper lists | — | verified |
| 0x1BD14 | `car_pics_free_all` | `void (void)` | Frees and clears the 20-slot `.ST` and `.SB` caches | — | verified |
| 0x1BD9C | `load_file_retry` | `void *(char *name)` | `load_file`; on failure free the car caches and try once more | — | verified |
| 0x1BDCA | `show_car` | `void (int idx, View *view, int dir)` dir ∈ {0, 1, −1} | Scroll out old car (task), load/decode new `.ST`/`.SB` into `view`, scroll it in | 0x0AB2 `show_car` | verified |
| 0x1BF40 | `sb_load_ilbm` | `void (long *data, View *view)` | If `FORM`…`ILBM`, parse it into the hires ViewPort of `view` | — | verified |
| 0x1BF8E | `sb_parse_ilbm` | `void (char *form, View *view)` | Chunk walk (BMHD, BODY, CMAP), then `sb_decode_body` | — (root 0x106BE is the lowres twin) | verified |
| 0x1C068 | `sb_decode_body` | `void (BMHD *bmhd, uint colors[32], char *body, View *view)` | ByteRun1 rows; rows < 0x59 discarded, rows ≥ 0x59 into the hires planes; LoadRGB4 | — | verified |
| 0x1C15C | `colormap_clear` | `void (ColorMap *cm)` | `ColorTable[0..Count-1] = 0` | — | verified |
| 0x1C190 | `fade_plate_colours` | `void (void)` | Steps colours 29–31 of the shown top ViewPort to black, 12 VBL per step | — | verified (purpose of colours 29–31: guess) |
| 0x1C22A | `wait_frames` | `void (int n)` | `n` × `WaitTOF` | 0x6C3B `delay_ticks` (analogue) | verified |
| 0x1C244 | `showroom_drive_away` | `void (int idx)` | `.SS` script: standing animation, then the car drives off; Starter sample | 0x0D75 `showroom_drive_away` | verified |
| 0x1C62E | `show_view` | `void (View *v)` | `LoadView(v)`; set front/back view and RastPort globals | — (DOS has no double-buffered display) | verified |
| 0x1C682 | `scroll_out_down` | `void (View *v)` | Top ViewPort moves down out of the 88-line band, 88 frames (TDScroller body, dir +1) | part of 0x0AB2 (`gfx_scroll_window` 0x91CF loops) | verified |
| 0x1C700 | `scroll_in_up` | `void (View *v)` | New picture rises into the band from line 87, 88 frames (dir −1) | part of 0x0AB2 | verified |
| 0x1C76A | `scroll_out_up` | `void (View *v)` | `RyOffset` 0..0x58: old picture scrolls up, 89 frames (TDScroller body, dir −1) | part of 0x0AB2 | verified |
| 0x1C7CC | `scroll_in_down` | `void (View *v)` | `RyOffset` 0x58..0: new picture scrolls down into place, 89 frames (dir +1) | part of 0x0AB2 | verified |
| 0x1C820 | `scroller_task_entry` | task entry, no args | Reloads A4 from D:0B2A, calls `D:288A(D:2886)`, sets D:2824 = 1, returns (task ends) | — | verified |
| 0x1C83C | `start_scroller` | `void (int up, View *v)` | Allocates a 2000-byte stack and a Task, `AddTask("TDScroller", pri 5)` | — | verified |
| 0x10B22 (root) | `res_find_list` | `void (Archive *a, long *names, Shape **out, long pool)` | Resolves a 0-terminated long list of names with mode codes 0..5 | 0x94C7 `res_find_list` | verified |
| 0x17AAA (root) | `gfx_LoadView` | `void (View *v)` | Glue: graphics.library `LoadView` (LVO −222) | — | verified |

0x1C682 and 0x1C76A have no direct callers: `start_scroller` stores one of them in D:288A and the task calls it.
0x1C820 is missing from `td_functions.json` (it is the tail between 0x1C7CC's `rts` and 0x1C83C).

### 2b. External functions used here (owned by other specs)

| Address | Provisional name | Use here | Spec |
|---|---|---|---|
| 0x10018 | `main` | caller of 0x1AED0 and 0x1B8E6 | see game_flow |
| 0x10402 | `skip_line` | `.SS` parser: advance past `\n` | see game_flow (Cars.txt reader) |
| 0x10462 | `poll_input` | keyboard poll: M/S toggles, P/D/O in game, key 0x12 → D:0346 | see platform_video (input) |
| 0x1063A | `ilbm_to_view` | clear view (0x1574E), decode ILBM into the view's first ViewPort, LoadRGB4 32 | see platform_video |
| 0x10692 / 0x107B4 | `iff_next_chunk` / `cmap_to_rgb4` | used by 0x1BF8E | see platform_video |
| 0x109D0 | `view_dissolve(src or NULL, dst)` | 8-step bitplane dissolve into `dst`; NULL = to black | see platform_video |
| 0x10D14 / 0x10E26 / 0x10E78 | `blit_begin` / `blit_set_dest(planes[5])` / `blit_wait` | blitter set-up and wait | see platform_video |
| 0x10E3A | `blit_shape_word(shape, mask, x, y)` | word-aligned shape copy (x & ~15); mask < 0x7D0 → plain copy | see platform_video |
| 0x10E58 | `blit_shape(shape, mask, x, y)` | pixel-precise shape copy (shifted); used for `bull` | see platform_video |
| 0x10FA4 | `set_clip_full` | clip 0..199 × 0..320 (D:0380–D:0386) | see platform_video |
| 0x1246A / 0x12546 / 0x1258E | `play_sample(s, ch, vol)` / `stop_channel(ch)` / `channel_busy(ch)` | Accolade, Starter | see platform_audio |
| 0x12942 | `song_volume(vol, step)` | duck / restore / fade the title song | see platform_audio |
| 0x149D2 / 0x149E8 | `load_file` / `load_file_chip` | result also in D:24BC | see platform_video (files) |
| 0x1530E | `rand16` | stirred in wait loops, used by main | see platform_video (system) |
| 0x153E4 / 0x153EC | `joy_fire` / `joy_dir` | fire (CIAA PRA bit 7, active low) → D:2858; JOY1DAT → D:2512 (0 none, 1 up … 8 up-left, clockwise) | see platform_video (input) |
| 0x1544E | `quit_requested` | sticky Ctrl-C break signal (SetSignal 0x1000) | see platform_video (system) |
| 0x15472 | `find_shape(archive, long name)` | 0 when missing | see platform_video |
| 0x1574E | `view_clear` | LoadRGB4 zeros (1 << depth) + BltClear every plane, for every ViewPort in the chain | see platform_video |
| 0x1580C / 0x1582C | `view_copy(src, dst)` / `view_copy_palette(src, dst)` | palette (+ BltBitMap for 0x1580C) per ViewPort pair | see platform_video |
| 0x15344 | `unpack_byterun1_row(&src, &dst, n)` | used by 0x1C068 | see platform_video |
| 0x15904 / 0x1591A / 0x159FA | `alloc_public` / `alloc_chip` / `free_mem` | | see platform_video (memory) |
| 0x15D4C / 0x16AC8 / 0x16ED8 | `sscanf` / `sprintf` / signed long divide | C runtime | see platform_video |
| 0x175EA | `dos_Delay(ticks)` | dos.library `Delay` (LVO −198), 1/50 s | see platform_video (system) |
| 0x17892 | `exec_AddTask(task, initPC, finalPC)` | LVO −282 | see platform_video (system) |
| 0x17A18…0x17B9A | graphics glue | `DisownBlitter` 17A18, `FreeColorMap` 17A32, `FreeVPortCopLists` 17A4A, `GetColorMap` 17A56, `InitBitMap` 17A62, `InitRastPort` 17A74, `InitVPort` 17A8C, `LoadRGB4` 17A98, `MakeVPort` 17AB6, `MrgCop` 17AD6, `OwnBlitter` 17AEE, `ScrollRaster` 17B08, `SetBPen` 17B34, `WaitTOF` 17B9A | see platform_video |

---

## 3. Globals

Display structures (all set up by root 0x115BC, see platform_video; the overlay changes the fields listed):

| D: offset | Name | Type | Meaning | Written here by | Read here by |
|---|---|---|---|---|---|
| 293E | `g_viewA` | `struct View` (0x12) | View A; `ViewPort` = &D:2E8E | — | everywhere |
| 2950 | `g_viewB` | `struct View` | View B; `ViewPort` = &D:2EB6 | — | everywhere |
| 2E8E | `g_vpA` | `struct ViewPort` (0x28) | +0 `Next` (0, or &D:2F2E in the showroom), +18 DWidth 320, +1A DHeight (D:2EA8), +1C DxOffset (D:2EAA), +1E DyOffset (D:2EAC), +24 RasInfo &D:28FE → BitMap D:2EDE | 1BA7C, 1BC64, 1B396, 1B62E, 1C244, 1AED0 | graphics |
| 2EB6 | `g_vpB` | `struct ViewPort` | same for view B: D:2ECE, D:2ED0 DHeight, D:2ED2 DxOffset, D:2ED4 DyOffset, RasInfo &D:290A → BitMap D:2F06 | same | graphics |
| 2EDE / 2F06 | `g_bitmapA` / `g_bitmapB` | `struct BitMap` (0x28) | 320×200×5 planes (8000 bytes each, chip), planes at D:2EE6 / D:2F0E | — | 1B62E (ScrollRaster on D:2F06) |
| 30AE / 3112 | `g_rpA` / `g_rpB` | `struct RastPort` (0x64) | RastPorts on bitmap A / B | — | — |
| 24CE | `g_frontView` | `View *` | View on screen (last `show_view` argument) | 1C62E | 1BDCA, 1C190, 1C244 |
| 24C8 | `g_backView` | `View *` | The other one of A/B (A when B is shown, else B) | 1C62E | 1B2B2, 1B62E, 1B8E6, 1C244 |
| 24C0 | `g_frontRastPort` | `RastPort *` | &D:30AE when A shown (default), &D:3112 when B shown | 1C62E | other specs (text) |
| 287A | `g_backRastPort` | `RastPort *` | the other RastPort | 1C62E | other specs |
| 2F2E / 2F56 | `g_sheetVpA` / `g_sheetVpB` | `struct ViewPort` | Showroom hires ViewPorts: DWidth 0x280, DHeight 0x6F, DyOffset 0x59, Modes 0x8000 (HIRES), ColorMap D:288E / D:2892, RasInfo &D:2916 / &D:2922 | 1BA7C | graphics |
| 2916 / 2922 | `g_sheetRasA` / `g_sheetRasB` | `struct RasInfo` (0xC) | BitMap &D:2F7E / &D:2FA6, Rx/RyOffset 0 | 1BA7C | graphics |
| 2F7E / 2FA6 | `g_sheetBmA` / `g_sheetBmB` | `struct BitMap` | 640×111×2 planes; planes D:2F86[2] / D:2FAE[2], 0x22B0 bytes each (chip) | 1BA7C | 1C068 |
| 288E / 2892 | `g_sheetCmA` / `g_sheetCmB` | `ColorMap *` | `GetColorMap(32)`, cleared | 1BA7C | 1BC64 |
| 31DA / 323E | `g_sheetRpA` / `g_sheetRpB` | `struct RastPort` | on the sheet bitmaps; set up but not used in overlay 1 | 1BA7C | — |
| 2876 | `g_tmpRastPort` | `RastPort *` | 100-byte temp RastPort (shared with the high-score code) | 1B62E | 1B62E |

Title, car selection and showroom state:

| D: offset | Name | Type | Meaning | DOS | Written by | Read by |
|---|---|---|---|---|---|---|
| 03D8 | `tick_count` | `ulong` | +1 per vertical blank ("Ticks VBLInt", 0x1180E) | DS:642A (100 Hz there) | VBL server | all loops |
| 0344 | `g_sfxOn` | `int` | Sound effects on (key S toggles) | — | 10462 | 1AED0, 1C244 |
| 0346 | `g_abortKey` | `int` | Set by 0x10462 when the converted key is 0x12 (Ctrl-R, likely); cleared by main | — | 10462, main | 1B8E6, 1C244 |
| 0350 | `g_numCars` | `int` | Cars in Cars.txt | DS:0088 | 10346 | 1B8E6 |
| 2E66 | `g_carNames` | `char *[]` | Car path stems (`cars/P911t`) | DS:78F2 | 10346 | 1BDCA, 1C244 |
| 2816 | `demo_mode` | `int` | Attract mode; cleared by any stick/fire in car select | DS:0084 | main, 1B8E6 | 1B8E6 |
| 2512 | `g_joyDir` | `int` | Last `joy_dir()`: 0 none, 1 up, 2 up-right, 3 right, 4 down-right, 5 down, 6 down-left, 7 left, 8 up-left | — | 153EC | 1B8E6 |
| 2858 | `g_joyFire` | `int` | Last `joy_fire()` | — | 153E4 | — |
| 24BC | `g_loadedBuf` | `void *` | Buffer of the last `load_file` | — | 149FE | 1AED0 |
| 0A7A | `g_titleShapeNames` | `long[44]` (initialised) | `frm0..frm4 rrm0..rrm4 wnd1..wnd9 wndA..wndK wndS wndT wndS wndL..wndR wndR wndR wndR`, then 0 | DS:0148 (window list) | — | 1B396 |
| 1EFC | `g_titleShapes` | `Shape *[43]` | 0..4 front wheel (D:1EFC), 5..9 rear wheel (D:1F10), 10..42 window frames (D:1F24, 33 entries) | — | 10B22 | 1B396 |
| 03CC | `g_blitTag` | `long` | 4-char tag written before some blits (`bull`, `fwhl`, `rwhl`, `wndw`, `KEYS`); never read | — | 1B2B2, 1B396, 1B62E, 0x13E86 | — |
| 300E | `g_stCache` | `void *[20]` | Loaded `<car>.ST` per car index | (DOS caches in load_archive) | 1BDCA, 1BD14 | 1BDCA |
| 305E | `g_sbCache` | `void *[20]` | Loaded `<car>.SB` per car index | — | 1BDCA, 1BD14 | 1BDCA |
| 2824 | `g_scrollerDone` | `int` | 0 while TDScroller runs; 1 when it has finished (or was never started) | — | 1BDCA, 1C83C, 1C820 | 1BDCA |
| 287E | `g_scrollerStack` | `void *` | 2000-byte task stack | — | 1C83C, 1BDCA | 1BDCA |
| 2882 | `g_scrollerTask` | `struct Task *` | 0x5C-byte Task | — | 1C83C, 1BDCA | 1BDCA |
| 2886 | `g_scrollerView` | `View *` | Argument for the task body | — | 1C83C | 1C820 |
| 288A | `g_scrollerFunc` | `void (*)(View *)` | 0x1C682 (dir +1) or 0x1C76A (dir −1) | — | 1C83C | 1C820 |
| 0B2A | `g_savedA4` | `long` (image 0x1873A) | A4 for the task (small data model) | — | 1C83C | 1C820 |

---

## 4. Pseudocode

Types: `int` = int16, `uint` = uint16, `long` = int32, `ulong` = uint32. `Shape` fields (FORMATS.md): `+8 x`,
`+0A y`. `vp->DxOffset` etc. are the ViewPort fields above. The helpers used everywhere:

```c
/* the 5-line busy wait that follows many animations (1AED0) */
static int wait_until(ulong t)          /* returns 1 when interrupted */
{
    do {
        rand16();                        /* 0x1530E: result discarded */
        poll_input();                    /* 0x10462 */
        if (quit_requested() || joy_fire()) return 1;
        WaitTOF();
    } while (t > tick_count);            /* unsigned compare */
    return 0;
}
```

### show_view — 0x1C62E (verified)
```c
void show_view(View *v)
{
    LoadView(v);                               /* 0x17AAA */
    g_frontView      = v;                      /* D:24CE */
    g_backView       = &g_viewB;               /* D:24C8 */
    g_frontRastPort  = &g_rpA;                 /* D:24C0 = D:30AE */
    g_backRastPort   = &g_rpB;                 /* D:287A = D:3112 */
    if (v == &g_viewB) {
        g_backView = &g_viewA; g_frontRastPort = &g_rpB; g_backRastPort = &g_rpA;
    }
}
```
Any view other than B (including the startup view D:2866 passed by 0x11756) makes B the back view.

### run_intro — 0x1AED0 (verified)
```c
int run_intro(void)
{
    void *acc = 0, *starter = 0; Archive *car = 0; int result = 1; ulong t;
    poll_input();
    if (joy_fire()) goto out;                               /* fire held: skip everything */
    view_clear(&g_viewA); show_view(&g_viewA);
    car = load_file_chip("pics/TitleCar.Shp");
    acc = load_file_chip("sfx/Accolade");
    load_file("pics/Title2"); ilbm_to_view(g_loadedBuf, &g_viewB); free_mem(g_loadedBuf);
    view_copy_palette(&g_viewB, &g_viewA);                  /* 0x1582C(src, dst) */
    view_dissolve(&g_viewB, &g_viewA);                      /* Title2 appears on A (shown) */
    poll_input();
    if (g_sfxOn) song_volume(7, 0x7000);                    /* duck the song */
    intro_accolade_bull(car);
    poll_input();
    if (joy_fire()) goto out;
    if (g_sfxOn) play_sample(acc, 3, 0x40);
    t = tick_count + 0xC8;                                  /* 200 VBL from the sample start */
    if (joy_fire()) goto out;
    while (channel_busy(3)) ;                               /* busy loop until Accolade ends (idle at once if sfx off) */
    if (joy_fire()) goto out;
    poll_input();
    song_volume(0x20, 0x9000);                              /* not conditional on g_sfxOn */
    load_file("pics/Title4"); poll_input();
    ilbm_to_view(g_loadedBuf, &g_viewB); free_mem(g_loadedBuf);
    show_view(&g_viewA);
    starter = load_file_chip("sfx/Starter");
    poll_input();
    if (wait_until(t)) goto out;
    view_dissolve(NULL, &g_viewA);                          /* Title2 to black */
    poll_input();
    view_copy_palette(&g_viewB, &g_viewA);
    if (g_sfxOn) song_volume(7, 0x3500);
    view_dissolve(&g_viewB, &g_viewA);                      /* Title4 appears */
    poll_input();
    if (wait_until(tick_count + 0x50)) goto out;
    if (g_sfxOn) play_sample(starter, 3, 0x40);
    if (joy_fire()) goto out;
    poll_input();
    intro_testdrive_car(car);                               /* not interruptible */
    song_volume(0x20, 0x9000);
    if (wait_until(tick_count + 5)) goto out;
    show_view(&g_viewB);
    load_file("pics/Title3"); poll_input();
    ilbm_to_view(g_loadedBuf, &g_viewA); free_mem(g_loadedBuf);
    poll_input();
    intro_testdrive_logo(car);
    if (wait_until(tick_count + 0x12C)) goto out;           /* 300 VBL = 5 s */
    view_dissolve(NULL, &g_viewB);                          /* to black */
    poll_input();
    if (!quit_requested()) result = -1;
out:
    if (result != -1) song_volume(0, 0x7000);               /* fade the song out when interrupted */
    view_clear(&g_viewA); view_clear(&g_viewB);
    g_vpA.DyOffset = 0;                                     /* D:2EAC */
    MakeVPort(&g_viewA, &g_vpA); MrgCop(&g_viewA); show_view(&g_viewA);
    if (starter) free_mem(starter);
    if (acc) free_mem(acc);
    if (car) free_mem(car);
    return result;
}
```
The sample and song functions are platform_audio's: `play_sample` starts channel 3 at volume 0x40,
`song_volume(v, step)` slides the song volume to `v` at `step` (16.16) per VBL.

### intro_accolade_bull — 0x1B2B2 (verified)
```c
void intro_accolade_bull(Archive *car)
{
    Shape *bull = find_shape(car, 'bull');       /* 48x3, x=240 y=80 */
    set_clip_full();
    show_view(&g_viewA);
    int donePrev, done = 0, x = 0; ulong t0 = tick_count; long delay = 1;
    do {
        OwnBlitter(); blit_begin();
        blit_set_dest(g_backView->ViewPort->RasInfo->BitMap->Planes);
        g_blitTag = 'bull';
        blit_shape(bull, NULL, x, bull->y);      /* 0x10E58: pixel-precise, no mask = opaque */
        blit_wait(); DisownBlitter();
        donePrev = done;
        done = (x >= bull->x);                   /* signed int compare */
        if (!done) x += 4;
        while (tick_count < t0 + delay) ;        /* delay is always 1 */
        show_view(g_backView);
        t0 = tick_count;
        WaitTOF();
        poll_input();
    } while (!donePrev);
}
```
x = 0, 4, …, 240, then 240 once more, so both buffers end with the bar at 240: 62 frames. The bar is never erased
(each buffer gets every other step), so it leaves a trail like the DOS version. Not interruptible.

### intro_testdrive_car — 0x1B396 (verified)
```c
void intro_testdrive_car(Archive *car)
{
    ulong t0 = tick_count;
    res_find_list(car, g_titleShapeNames, g_titleShapes, /*pool: not pushed, garbage, unused*/);
    while (tick_count < t0 + 0x71) ;                 /* busy wait 113 VBL (starter cranking) */
    set_clip_full();
    View *front = &g_viewA, *back = &g_viewB; ViewPort *vpFront = &g_vpA, *vpBack = &g_vpB;
    show_view(front);
    int moving = 0, wf = 0, x = 0, done = 0; long vel = 0; long delay /* set before first use */;
    Shape **frm = &g_titleShapes[0], **rrm = &g_titleShapes[5], **wnd = &g_titleShapes[10];
    t0 = tick_count;
    do {
        OwnBlitter(); blit_begin();
        blit_set_dest(vpBack->RasInfo->BitMap->Planes);
        if (moving == 1) {
            int fw = ((x + 4) / 5) % 5;              /* divs.w, divs.w + swap: 16-bit signed */
            int rw = x % 5;
            vpBack->DxOffset = -x;
            g_blitTag = 'fwhl'; blit_shape_word(frm[fw], NULL, frm[fw]->x, frm[fw]->y);
            g_blitTag = 'rwhl'; blit_shape_word(rrm[rw], NULL, rrm[rw]->x, rrm[rw]->y);
            MakeVPort(back, vpBack); MrgCop(back);
            x += (int)(vel >> 16);                   /* asr.l #16, add.w */
            vel += 0x3A98;                           /* 15000 */
            done = (x >= 0x140);
            delay = 2;
        }
        if (moving == 0 || wf < 0x21) {
            g_blitTag = 'wndw'; blit_shape_word(wnd[wf], NULL, wnd[wf]->x, wnd[wf]->y);
            wf++;
            if (wf < 0x1A) delay = 9; else moving = 1;
        }
        blit_wait(); DisownBlitter();
        show_view(back);
        WaitTOF();
        while (tick_count < t0 + delay) ;
        t0 = tick_count;
        swap(front, back); swap(vpFront, vpBack);
        poll_input();
    } while (!done);
    g_vpA.DxOffset = 0; g_vpB.DxOffset = 0;          /* D:2EAA, D:2ED2 */
    view_clear(&g_viewA); view_clear(&g_viewB);
    MakeVPort(&g_viewA, &g_vpA); MakeVPort(&g_viewB, &g_vpB);
    MrgCop(&g_viewA); MrgCop(&g_viewB);
}
```
Both views hold Title4 at the start (A by dissolve, B by `ilbm_to_view`). The frames alternate between the two
buffers, so each buffer gets every other window frame; the frames overlap the same rectangle (x=144, y=113), so
the result looks continuous. Window frames 0..25 take 9 VBL each; from frame 26 the car moves and each frame is
2 VBL; window frames 26..32 keep playing while it moves. The car (the whole top ViewPort) slides left as
`DxOffset = −x`. The loop ends at x ≥ 320. Not interruptible (only `poll_input`).

### intro_testdrive_logo — 0x1B62E (verified)
Physics identical to DOS `intro_testdrive_logo` (game_flow §4, 0x0792): same constants 0x30C, −0xC3, damp 7,
×−7, the zero-crossing test, `vel / damp` signed 32-bit (0x16ED8), the 0xDAC window, `settle > 5`. Checked
instruction by instruction at 0x1B662–0x1B73A. What differs is what `y` moves and the frame rate:
```c
void intro_testdrive_logo(Archive *car)
{
    int phase = 0, settle = 0, accel = 0x30C, y = -0xC3, damp = 7, finished = 0;
    long vel = 0; ulong t0 = tick_count; long delay = 1;
    do {
        g_vpA.DyOffset = y + 0xA0;           /* D:2EAC; set before the step: display lags one step */
        /* phase 0/1/2 update of y, vel, accel, damp, settle, finished: exactly as DOS 0x0792 */
        while (tick_count < t0 + delay) ;
        MakeVPort(&g_viewA, &g_vpA); MrgCop(&g_viewA); show_view(&g_viewA);
        t0 = tick_count;
        WaitTOF();
        poll_input();
    } while (!finished && !quit_requested());    /* fire does not interrupt */
    g_vpA.DyOffset = 0xA0;
    MakeVPort(&g_viewA, &g_vpA); MrgCop(&g_viewA); show_view(&g_viewA);
    g_vpB.DyOffset = 0;                          /* D:2ED4 */
    MakeVPort(&g_viewB, &g_vpB); MrgCop(&g_viewB);
    view_copy(&g_viewA, &g_viewB);               /* 0x1580C: palettes + bitmaps A -> B */
    g_tmpRastPort = alloc_public(100);
    InitRastPort(g_tmpRastPort);
    g_tmpRastPort->BitMap = &g_bitmapB;          /* D:2F06 */
    SetBPen(g_tmpRastPort, 0);
    ScrollRaster(g_tmpRastPort, 0, -0xA0, 0, 0, 0x13F, 0xC7);   /* rows move down 160; rows 0..159 = pen 0 */
    free_mem(g_tmpRastPort); g_tmpRastPort = 0;
    show_view(&g_viewB);                         /* B with DyOffset 0 now looks like A with DyOffset 160 */
    view_copy(&g_viewB, &g_viewA);
    poll_input();
    Shape *keys = find_shape(car, 'KEYS');       /* 128x72 at (80,37) */
    OwnBlitter();                                /* no blit_begin here */
    blit_set_dest(g_backView->ViewPort->RasInfo->BitMap->Planes);   /* back = A */
    g_blitTag = 'KEYS';
    blit_shape_word(keys, NULL, keys->x, keys->y);
    blit_wait(); DisownBlitter();
    poll_input();
    dos_Delay(0x3C);                             /* 60/50 s = 1.2 s, not interruptible */
    poll_input();
    if (!quit_requested()) { view_dissolve(&g_viewA, &g_viewB); poll_input(); }   /* KEYS appears */
}
```
Title3 is the "TEST DRIVE" logo in its top ~20 rows, black below. The ViewPort's top edge starts at display
line −35 (y = −0xC3) and settles at line 160, so the logo drops to the bottom of the screen. One physics step
per VBL (DOS: one per 100 ms). g_vpA.DyOffset stays 0xA0 until `run_intro` resets it on exit.

### res_find_list — 0x10B22 (root; verified)
```c
void res_find_list(Archive *a, long *names, Shape **out, long pool)
{
    int mode = 1;
    do {
        long v = *names++;
        if (v >= 0 && v <= 5) mode = (int)v;          /* low word of the long */
        else {
            Shape *s = find_shape(a, v);
            if (mode == 1)      *out++ = s;             /* may be 0: blitter ignores shapes <= 0x32 */
            else if (mode == 2) *out++ = make_shape_mask(pool, s);   /* 0x10C5A; not used by overlay 1 */
        }
    } while (mode != 0);
}
```

### car_select — 0x1B8E6 (verified)
```c
int car_select(void)
{
    int idx = 0, dir = 0; ulong deadline;
    int unused = g_vpA.DyOffset;                /* read into a local, never used */
    showroom_display_init();
    int fireReleased  = (joy_fire() == 0);
    int stickReleased = (joy_dir() == 0);
show:
    show_car(idx, g_backView, dir);
reset_timeout:
    deadline = tick_count + (demo_mode ? 0x21C : 0x1770);   /* 540 or 6000 VBL (9 s / 100 s) */
    for (;;) {
        poll_input();
        if (g_abortKey) goto abort;
        if (joy_fire()) { demo_mode = 0; if (fireReleased) goto chosen; }
        else fireReleased = 1;
        if (quit_requested()) goto abort;
        if (joy_dir() == 0) stickReleased = 1; else demo_mode = 0;
        if (g_joyDir == 5 && stickReleased) {            /* down: next car */
            stickReleased = 0; idx++; dir = 1;
            if (idx >= g_numCars) idx = 0;
            goto show;
        }
        if (g_joyDir == 1 && stickReleased) {            /* up: previous car */
            stickReleased = 0; idx--; dir = -1;
            if (idx < 0) idx = g_numCars - 1;
            goto show;
        }
        rand16();
        dos_Delay(5);                                    /* 0.1 s: the loop polls at 10 Hz */
        if (g_joyDir != 0) goto reset_timeout;           /* any held direction restarts the timeout */
        if (deadline > tick_count) continue;
        /* timeout */
        if (!demo_mode) goto abort;
        if (++idx >= g_numCars) goto abort;              /* attract: next car, until the end of the list */
        dir = 1; goto show;
    }
abort:
    idx = -1;
chosen:
    car_pics_free_all();
    poll_input();
    if (idx >= 0 && !g_abortKey) showroom_drive_away(idx);
    view_clear(&g_viewA); show_view(&g_viewA);
    showroom_display_free();
    return idx;
}
```
Fire only counts after it has been seen released once inside `car_select` (so a fire held from the previous
screen does not select). The keyboard is not read here except through `poll_input` (D:0346, M/S toggles).

### showroom_display_init — 0x1BA7C / showroom_display_free — 0x1BC64 (verified)
```c
void showroom_display_init(void)
{
    view_clear(&g_viewB); show_view(&g_viewB); view_clear(&g_viewA);
    InitVPort(&g_sheetVpA); InitVPort(&g_sheetVpB);
    InitBitMap(&g_sheetBmA, 2, 0x280, 0x6F); InitBitMap(&g_sheetBmB, 2, 0x280, 0x6F);
    g_sheetRasA = (RasInfo){ .Next = 0, .BitMap = &g_sheetBmA, .RxOffset = 0, .RyOffset = 0 };
    g_sheetRasB = (RasInfo){ .Next = 0, .BitMap = &g_sheetBmB, .RxOffset = 0, .RyOffset = 0 };
    for (vp in {g_sheetVpA, g_sheetVpB}) { vp.DyOffset = 0x59; vp.DWidth = 0x280; vp.DHeight = 0x6F;
                                           vp.Modes = 0x8000 /* HIRES */; }
    g_sheetVpA.RasInfo = &g_sheetRasA; g_sheetVpB.RasInfo = &g_sheetRasB;
    InitRastPort(&g_sheetRpA); g_sheetRpA.BitMap = &g_sheetBmA;
    InitRastPort(&g_sheetRpB); g_sheetRpB.BitMap = &g_sheetBmB;
    g_sheetCmA = GetColorMap(0x20); g_sheetCmB = GetColorMap(0x20);
    g_sheetVpA.ColorMap = g_sheetCmA; g_sheetVpB.ColorMap = g_sheetCmB;
    colormap_clear(g_sheetCmA); colormap_clear(g_sheetCmB);
    for (int i = 0; i < 2; i++) { g_sheetBmA.Planes[i] = alloc_chip(0x22B0); g_sheetBmB.Planes[i] = alloc_chip(0x22B0); }
    g_vpA.Next = &g_sheetVpA; g_vpB.Next = &g_sheetVpB;
    g_vpA.DHeight = 0x58; g_vpB.DHeight = 0x58;         /* D:2EA8, D:2ED0: top band = 88 lines */
    MakeVPort(&g_viewA, &g_vpA); MakeVPort(&g_viewA, &g_sheetVpA); MrgCop(&g_viewA); show_view(&g_viewA);
    MakeVPort(&g_viewB, &g_vpB); MakeVPort(&g_viewB, &g_sheetVpB); MrgCop(&g_viewB);
}

void showroom_display_free(void)
{
    g_vpA.Next = 0; g_vpB.Next = 0; g_vpA.DHeight = 200; g_vpB.DHeight = 200;
    MakeVPort(&g_viewA, &g_vpA); MakeVPort(&g_viewB, &g_vpB); MrgCop(&g_viewA); MrgCop(&g_viewB);
    for (int i = 0; i < 2; i++) { free_mem(g_sheetBmA.Planes[i]); free_mem(g_sheetBmB.Planes[i]); }
    FreeColorMap(g_sheetCmA); FreeColorMap(g_sheetCmB);
    FreeVPortCopLists(&g_sheetVpA); FreeVPortCopLists(&g_sheetVpB);
}
```
Layout while in the showroom: lines 0–87 lowres 320 px, 5 planes, 32 colours (car picture); line 88 empty
(the gap graphics.library needs between ViewPorts); lines 89–199 hires 640 px, 2 planes, 4 colours (spec sheet).

### colormap_clear — 0x1C15C (verified)
`for (uint i = 0; i < cm->Count; i++) cm->ColorTable[i] = 0;`

### car_pics_free_all — 0x1BD14 / load_file_retry — 0x1BD9C (verified)
```c
void car_pics_free_all(void)
{
    for (int i = 0; i < 0x14; i++) {
        if (g_stCache[i]) { free_mem(g_stCache[i]); g_stCache[i] = 0; }
        if (g_sbCache[i]) { free_mem(g_sbCache[i]); g_sbCache[i] = 0; }
    }
}
void *load_file_retry(char *name)
{
    void *p = load_file(name);
    if (p == 0) { car_pics_free_all(); p = load_file(name); }   /* out of memory: drop the cache, retry */
    return p;
}
```

### show_car — 0x1BDCA (verified)
```c
void show_car(int idx, View *view, int dir)       /* view = the hidden view */
{
    char name[40];
    g_scrollerDone = 1;
    if (dir == 1)  start_scroller(0, g_frontView);  /* task: scroll_out_down */
    if (dir == -1) start_scroller(1, g_frontView);  /* task: scroll_out_up   */
    if (!g_stCache[idx]) { sprintf(name, "%s.ST", g_carNames[idx]); g_stCache[idx] = load_file_retry(name); }
    if (!g_sbCache[idx]) { sprintf(name, "%s.SB", g_carNames[idx]); g_sbCache[idx] = load_file_retry(name); }
    ilbm_to_view(g_stCache[idx], view);   /* 0x1063A: clears both ViewPorts of view, decodes .ST (320x200x5)
                                             into the top bitmap, LoadRGB4(top vp, CMAP, 32) */
    sb_load_ilbm(g_sbCache[idx], view);   /* rows 89..199 of .SB into the hires bitmap, LoadRGB4(hires vp) */
    while (g_scrollerDone == 0) WaitTOF();
    if (g_scrollerStack) { free_mem(g_scrollerStack); g_scrollerStack = 0; }
    if (g_scrollerTask)  { free_mem(g_scrollerTask);  g_scrollerTask  = 0; }
    if (dir == 0)  show_view(view);
    if (dir == -1) scroll_in_up(view);
    if (dir == 1)  scroll_in_down(view);
}
```
`<car>.ST` is 320×200: the car and its name plate in the top 88 rows, black below. `<car>.SB` is a 640×200
2-plane ILBM with the spec sheet in rows 89–199 (rows 0–88 are blank and are skipped). If a file cannot be
loaded, `ilbm_to_view` gets 0: the FORM test fails and the view is only cleared.

Direction: dir −1 (stick up) moves both pictures **up**: the old one scrolls up (`RyOffset` 0→88), the new one
rises from the bottom of the band. dir +1 (stick down) moves both **down**: the old one slides down and is cut at
line 88, the new one scrolls down from `RyOffset` 88 (its black lower half) to 0.

### start_scroller — 0x1C83C / scroller_task_entry — 0x1C820 (verified)
```c
void start_scroller(int up, View *v)
{
    g_savedA4 = A4;                                   /* D:0B2A (image 0x1873A) */
    g_scrollerStack = alloc_public(0x7D0);
    if (!g_scrollerStack) return;                     /* no scroll-out; g_scrollerDone stays 1 */
    g_scrollerTask = alloc_public(0x5C);
    if (!g_scrollerTask) return;                      /* no scroll-out; show_car frees the stack */
    Task *t = g_scrollerTask;
    t->tc_Node.ln_Type = 1 /* NT_TASK */; t->tc_Node.ln_Name = "TDScroller"; t->tc_Node.ln_Pri = 5;
    t->tc_SPLower = g_scrollerStack; t->tc_SPUpper = g_scrollerStack + 0x7D0; t->tc_SPReg = t->tc_SPUpper;
    g_scrollerView = v;
    g_scrollerFunc = up ? scroll_out_up /*0x1C76A*/ : scroll_out_down /*0x1C682*/;
    g_scrollerDone = 0;
    AddTask(t, scroller_task_entry /*0x1C820*/, 0);
}

void scroller_task_entry(void)                        /* runs as task "TDScroller", priority 5 */
{
    A4 = *(long *)0x1873A;                            /* D:0B2A */
    g_scrollerFunc(g_scrollerView);
    g_scrollerDone = 1;
}                                                     /* rts -> exec's default final PC ends the task */
```
The task (priority 5) pre-empts the main task (priority 0) whenever it is not waiting in `WaitTOF`, so in
practice the scroll runs one step per frame while the main task loads and decodes in the gaps.

### scroll_out_down 0x1C682 / scroll_in_up 0x1C700 / scroll_out_up 0x1C76A / scroll_in_down 0x1C7CC (verified)
```c
void scroll_out_down(View *v)                 /* 88 frames */
{
    ViewPort *vp = v->ViewPort; int h = vp->DHeight;          /* 0x58 */
    for (int i = 0; i < 0x58; i++) {
        vp->DyOffset = i; vp->DHeight = h - i;
        MakeVPort(v, vp); MrgCop(v); show_view(v); WaitTOF();
    }
    vp->DyOffset = 0; vp->DHeight = h;                         /* no MakeVPort afterwards */
}
void scroll_in_up(View *v)                    /* 88 frames */
{
    ViewPort *vp = v->ViewPort; int h = vp->DHeight;
    for (int i = 0x57; i >= 0; i--) {
        vp->DyOffset = i; vp->DHeight = h - i;
        MakeVPort(v, vp); MrgCop(v); show_view(v); WaitTOF();
    }
}
void scroll_out_up(View *v)                   /* 89 frames */
{
    ViewPort *vp = v->ViewPort;
    for (int i = 0; i < 0x59; i++) {
        vp->RasInfo->RyOffset = i;
        MakeVPort(v, vp); MrgCop(v); show_view(v); WaitTOF();
    }
    vp->RasInfo->RyOffset = 0;
}
void scroll_in_down(View *v)                  /* 89 frames */
{
    ViewPort *vp = v->ViewPort;
    for (int i = 0x58; i >= 0; i--) {
        vp->RasInfo->RyOffset = i;
        MakeVPort(v, vp); MrgCop(v); show_view(v); WaitTOF();
    }
}
```
Only the top ViewPort changes; `MrgCop` rebuilds the whole view, so the hires sheet stays where it is. Note
that the sheet of the old car stays visible during the scroll-out (it is in the shown view) and the new sheet
appears at the first frame of the scroll-in.

### sb_load_ilbm 0x1BF40 / sb_parse_ilbm 0x1BF8E / sb_decode_body 0x1C068 (verified)
```c
void sb_load_ilbm(long *d, View *view)
{
    if (d[0] == 'FORM' && d[2] == 'ILBM') sb_parse_ilbm((char *)d, view);
}
void sb_parse_ilbm(char *f, View *view)       /* same walk as root 0x106BE, minus CMP2 */
{
    BMHD *bmhd = 0; char *body = 0; uint colors[32]; long off = 0xC;
    long end = *(long *)(f + 4) + 8;
    while (off < end) {
        long id = *(long *)(f + off);
        if (id == 'BMHD') bmhd = (BMHD *)(f + off + 8);
        else if (id == 'BODY') body = f + off + 8;
        else if (id == 'CMAP') cmap_to_rgb4(f + off, colors);          /* 0x107B4 */
        iff_next_chunk(f, &off);                                          /* off = (off + len + 9) & ~1 */
        if (off >= 0x9C40 || off <= 0) break;
    }
    if (bmhd && body) sb_decode_body(bmhd, colors, body, view);
}
void sb_decode_body(BMHD *bmhd, uint colors[32], char *body, View *view)
{
    ViewPort *sheet = view->ViewPort->Next;                 /* the hires ViewPort */
    char *planes[8]; char scratch[100];
    for (uint p = 0; p < bmhd->nPlanes; p++) planes[p] = sheet->RasInfo->BitMap->Planes[p];
    uint rowBytes = (uint)(bmhd->w + 7) >> 3;              /* 80 */
    for (uint row = 0; row < bmhd->h; row++)
        for (uint p = 0; p < bmhd->nPlanes; p++) {
            if ((int)row < 0x59) { char *s = scratch; unpack_byterun1_row(&body, &s, rowBytes); }
            else unpack_byterun1_row(&body, &planes[p], rowBytes);   /* planes[p] advances */
        }
    WaitTOF();
    LoadRGB4(sheet, colors, 0x20);
}
```
BMHD `compression` and `masking` are not checked (ByteRun1 is assumed). `cmap_to_rgb4` pre-fills entries
0–2, 4–6, … 28–30 with the three words at D:0358 and leaves entries 3, 7, …, 31 uninitialised before copying
the CMAP (4 colours in the `.SB` files); only entries 0–3 matter for a 2-plane ViewPort.

### fade_plate_colours — 0x1C190 (verified)
```c
void fade_plate_colours(void)
{
    uint *ct = g_frontView->ViewPort->ColorMap->ColorTable;   /* top ViewPort of the shown view */
    uint any;
    do {
        any = 0;
        for (int i = 0x1D; i < 0x20; i++) {                    /* colours 29, 30, 31 */
            uint b = ct[i] & 0xF;
            any |= b;
            if (b) ct[i] = b - 1;       /* clears red and green, blue - 1; a colour with blue 0 is left alone */
        }
        LoadRGB4(g_frontView->ViewPort, ct, 0x20);
        wait_frames(0xC);
    } while (any);
}
```
At most 16 passes × 12 VBL (3.2 s). Which parts of the `.ST` pictures use colours 29–31 was not checked
(the name plate is a guess).

### wait_frames — 0x1C22A (verified)
`while (n-- > 0) WaitTOF();` (the test is on the value before the decrement, signed).

### showroom_drive_away — 0x1C244 (verified)
The `.SS` format and the motion are in FORMATS.md ("Showroom script"); this is the complete control flow.
```c
void showroom_drive_away(int idx)
{
    char name[40]; Shape *ent[50]; int n, m; char *p; long nameLong;
    fade_plate_colours();
    view_copy(g_frontView, g_backView);                  /* 0x1580C: palettes + both bitmaps */
    MakeVPort(g_backView, g_backView->ViewPort); MrgCop(g_backView);
    poll_input();
    sprintf(name, "%s.ST.Shp", g_carNames[idx]); Archive *shp = load_file_chip(name); poll_input();
    sprintf(name, "%s.SS", g_carNames[idx]);     char *ss = load_file(name);       poll_input();
    void *starter = load_file_chip("sfx/Starter");                                  poll_input();
    sscanf(ss, "%d %d", &n, &m);
    p = ss; skip_line(&p); skip_line(&p);
    for (int i = 0; i < n; i++) {                        /* no bound: n > 50 overflows ent[] */
        ((char *)&nameLong)[0..3] = p[0..3]; p += 4;
        ent[i] = find_shape(shp, nameLong);
        p++;                                             /* one separator byte */
    }
    set_clip_full();
    show_view(g_frontView);
    int moving = 0, k = 6, x = 0, done = 0; long vel = 0; long delay; ulong t0 = tick_count;
    if (g_sfxOn) play_sample(starter, 3, 0x40);
    do {
        OwnBlitter(); blit_begin();
        blit_set_dest(g_backView->ViewPort->RasInfo->BitMap->Planes);
        if (moving == 1) {
            int w = ((x + 4) / 5) % 3;                   /* 16-bit signed divs */
            g_backView->ViewPort->DxOffset = -x;
            blit_shape_word(ent[w],     NULL, ent[w]->x,     ent[w]->y);       /* front wheel */
            blit_shape_word(ent[w + 3], NULL, ent[w + 3]->x, ent[w + 3]->y);   /* rear wheel, same phase */
            MakeVPort(g_backView, g_backView->ViewPort); MrgCop(g_backView);
            x += (int)(vel >> 16);
            vel += 0x2EE0;                               /* 12000 */
            done = (x >= 0x140);
            delay = 2;
        }
        if (moving == 0 || k < n) {
            blit_shape_word(ent[k], NULL, ent[k]->x, ent[k]->y);
            k++;
            if (k < m) delay = 9; else moving = 1;
        }
        blit_wait(); DisownBlitter();
        show_view(g_backView);
        WaitTOF();
        while (tick_count < t0 + delay) ;
        t0 = tick_count;
        poll_input();
        if (g_abortKey) done = 1;
    } while (!done);
    g_vpA.DxOffset = 0; g_vpB.DxOffset = 0;
    view_clear(&g_viewA); view_clear(&g_viewB);
    MakeVPort(&g_viewA, &g_vpA); MakeVPort(&g_viewB, &g_vpB); MrgCop(&g_viewA); MrgCop(&g_viewB);
    free_mem(shp); free_mem(ss);
    wait_frames(10);
    stop_channel(3);                                     /* unconditional */
    free_mem(starter);
}
```
`show_view(g_backView)` swaps front and back each frame, so the double buffering is implicit in the globals.
With the shipped scripts (M ≥ 29) `delay` is always set before its first use; with M ≤ 7 the first wait would
use an uninitialised value. Only the top ViewPort moves; the spec sheet stays. The pictures are not
restored afterwards: `car_select` clears view A and removes the showroom layout.

---

## 5. Hardware / OS dependencies → SDL3

| Dependency | Where | SDL3 port |
|---|---|---|
| graphics.library Views/ViewPorts: `MakeVPort`, `MrgCop`, `LoadView`, `InitVPort`, `InitBitMap`, `GetColorMap`, `LoadRGB4`, `FreeVPortCopLists`, `FreeColorMap` | everywhere | An emulated display list per View: ordered ViewPorts with DxOffset, DyOffset, DHeight, DWidth, HIRES flag, RasInfo Rx/RyOffset, a 32-entry 12-bit palette, a planar bitmap. `show_view` selects the list shown at the next 60 Hz frame. Compose into a 640×200 (or larger) RGB texture: lowres pixels doubled horizontally, hires 1:1. Areas not covered by a ViewPort (negative DxOffset, the line-88 gap, the region below a shrunken ViewPort) show the background colour (colour 0 of the view's first ViewPort; see Open questions). `MakeVPort`/`MrgCop` become no-ops that snapshot the ViewPort fields. |
| Blitter via root helpers (0x10D14, 0x10E26, 0x10E3A, 0x10E58, 0x10E78), `OwnBlitter`/`DisownBlitter` | 1B2B2, 1B396, 1B62E, 1C244 | Software planar copies into the 5-plane bitmaps (opaque rectangle copy; x & ~15 for 0x10E3A). The ownership calls vanish. |
| `ScrollRaster(rp, 0, −160, 0, 0, 319, 199)`, BltClear, BltBitMap | 1B62E, view_clear, view_copy | memmove/memset on the planar bitmap. |
| 8-step dissolve 0x109D0 (CPU, no frame sync) | 1AED0, 1B62E | Run each step on the emulated bitmaps and present; pace it (see Timing / Open questions). |
| exec `AddTask` "TDScroller" (pri 5, 2000-byte stack) | 1C83C | Run the scroll-out loop synchronously before loading the next car (file loads are instant in the port), then the scroll-in. This keeps the visible sequence: out (88/89 frames), then in. |
| dos.library `Delay(n)` (1/50 s) | 1B62E (60), 1B8E6 (5) | Sleep n × 20 ms while pumping SDL events. |
| `WaitTOF`, VBL tick D:03D8 | all loops | One 60 Hz frame clock (NTSC): present + increment `tick_count`. Busy waits on `tick_count` become frame waits. |
| CIAA PRA bit 7 (fire), JOY1DAT (direction) | 153E4, 153EC | SDL keyboard/gamepad → fire flag and the 0..8 direction code (1 up … 5 down). |
| exec SetSignal Ctrl-C (`quit_requested`) | 1AED0, 1B62E, 1B8E6 | Window close / quit event. |
| Paula samples (Accolade, Starter), song volume | 1AED0, 1C244 | platform_audio. |
| Overlay manager stubs (0x17E94…) | calls into 0x1AED0, 0x1B8E6, 0x1C62E | Plain C calls. |

---

## 6. Timing

All timing is in vertical blanks (`tick_count`, D:03D8), except the two dos `Delay` calls (1/50 s, not
VBL-based). The code has no PAL/NTSC case; the port runs the NTSC 60 Hz VBL (port/amiga/README.md, *Decisions*
1), so the seconds below are VBL counts / 60.

| Place | Rate |
|---|---|
| `intro_accolade_bull` | 1 step per VBL (+4 px), 62 frames ≈ 1.03 s |
| Accolade sample | 13122 bytes at 10 kHz ≈ 1.31 s; busy wait until channel 3 is idle |
| Title2 → Title4 | the dissolve to black starts once 200 VBL have passed since the Accolade sample started (Title4 is loaded meanwhile) |
| Title4 hold | 80 VBL (1.33 s), then Starter starts |
| `intro_testdrive_car` | 113 VBL (1.88 s) pre-delay; window frames 9 VBL each (26 frames); moving frames 2 VBL |
| after the car | 5 VBL |
| `intro_testdrive_logo` | 1 physics step per VBL; then `Delay(60)` = 1.2 s; then the KEYS dissolve |
| logo hold | 300 VBL (5 s), then dissolve to black |
| `car_select` | poll loop at 10 Hz (`Delay(5)`); timeout 6000 VBL (100 s), attract 540 VBL (9 s) per car |
| scroll out / in | 88 or 89 frames each, 1 per VBL (TDScroller in parallel with loading) |
| `showroom_drive_away` | colour fade up to 16 × 12 VBL (3.2 s); standing frames 9 VBL; driving frames 2 VBL; then 10 VBL |
| `view_dissolve` | 8 passes, CPU-bound with no WaitTOF (see Open questions) |

Frame pacing pattern: most loops draw, `show_view`, `WaitTOF`, then busy-wait until `tick_count ≥ t0 + delay`,
so a frame lasts `delay` VBLs (at least one). `MakeVPort`/`MrgCop` for a full view can take more than one frame
on a 7 MHz 68000; the port should use the nominal rates above.

---

## 7. Differences from DOS

Intro (DOS `run_intro` 0x037A and its three parts, game_flow §4):

* **Pictures are ILBMs, not sprite compositions.** DOS composes `acc`/`pres`/`copy`, `car `, `tdrv`, `fob `,
  `tmar` from ACCOLADE.PES/TESTDRV.PES. The Amiga shows whole pictures (`title2`, `Title4`, `Title3`) plus a few
  shapes from `TitleCar.Shp` (`bull`, `frm0-4`, `rrm0-4`, `wnd*`, `KEYS`). There is no "CTRL-(J)OYSTICK OR
  CTRL-(K)EYBOARD" text; the `KEYS` shape takes the place of fob + ™ mark.
* **Transitions** use the bitplane dissolve 0x109D0 (8 passes, one bit per byte per pass, bit pattern table at
  0x10A82 = 01,08,40,02,10,80,04,20 indexed by `(pass + r) & 7`, rows visited in the order `7r mod 200`), both to
  a picture and to black. DOS uses `gfx_dissolve` 0x768B only to reveal. The Amiga fades Title2 and Title3 to
  black; DOS just moves on.
* **Sound:** the Amiga plays `sfx/Accolade` after the bull and `sfx/Starter` before the car drives off, and ducks
  the title song (`song_volume` 7/0x7000, 7/0x3500, back to 0x20/0x9000, fade to 0/0x7000 when interrupted). DOS
  only plays and stops the intro song.
* **Interruption:** DOS stops at any key on every animation frame and returns that key. The Amiga checks fire and
  Ctrl-C only at the start, between segments and in the hold loops. The bull and car animations cannot be
  interrupted, and the logo drop stops only on Ctrl-C. It returns 1 (interrupted) or −1 (complete); there is no
  "key pressed" value and no Esc.
* **Bull:** 48×3 px bar to x = 240, +4 px per VBL (16.7 ms), drawn once more at the end. DOS: 32×3 bar to x < 256,
  +2 px per 10 ms tick.
* **Car drive-off:** 113 VBL pre-delay with no reveal wipe (DOS: 8-step wipe at 100 ms per step). Frames 9 VBL
  (150 ms) and 2 VBL (33 ms) vs DOS 20 and 4 ticks (200 and 40 ms). Motion `vel += 15000; x += vel >> 16` (16.16)
  vs DOS `vel += 10; dist += vel >> 4`. The picture moves by `DxOffset` on double-buffered views; DOS redraws
  the page shifted and clears a ≤32-px strip. Wheel shapes are `frm0–4`/`rrm0–4` (DOS `frm1–5`/`rrm1–5`), same
  index formulas (`((x+4)/5)%5` front, `x%5` rear), front wheel drawn first (DOS rear first). The window list
  D:0A7A (`wnd1..wndK wndS wndT wndS wndL..wndR wndR×4`, 33 entries) differs from DOS DS:0148; the 33/26 counts
  are the same.
* **Logo:** identical physics, but it moves the whole Title3 ViewPort (`DyOffset = y + 160`) at one step per VBL
  (16.7 ms) instead of drawing `tdrv` at `ly + y` every 100 ms, so the drop runs 6× faster. The display lags the
  physics by one step. Afterwards: B gets a copy of A scrolled down 160 lines, the KEYS shape is dissolved in
  after 1.2 s (`Delay(60)`), and the hold is 5 s (DOS: 10 s `wait_input`).

Car selection and showroom (DOS 0x098C, 0x0AB2, 0x0D75):

* **Controls:** joystick only. Stick **down = next car** (dir +1), **up = previous car** (dir −1); DOS Up = next
  (show_car dir −1), Down = previous (dir +1). Fire selects, and must first be seen released. No Esc: Ctrl-C
  quits the program, D:0346 (key 0x12) goes back to the intro.
* **Timeouts:** 6000 VBL = 100 s (DOS 12000 × 10 ms = 120 s). In attract mode the Amiga shows each car for 540
  VBL (9 s) in order and returns −1 after the last one; main then picks `rand16() % g_numCars`. DOS shows a random
  run of 5–8 cars at 4 s each, then plays the drive-away of the current car and returns −1 with that car
  selected. On a normal timeout the Amiga returns −1 **without** a drive-away (DOS plays it). Holding the stick
  restarts the timeout (DOS has no such rule).
* **Screen layout:** two ViewPorts (320×88×5 car band, 640×111×2 hires spec sheet from line 89) built from two
  ILBM files, `<car>.ST` and `<car>.SB`. DOS uses one PES (`<car>SB.PES`) with `car `, `name`, `stat` sprites,
  88 + 112 lines, all lowres.
* **Scrolling:** by ViewPort offsets (DyOffset/DHeight or RasInfo RyOffset) one line per VBL, with the scroll-out
  in a separate task while the next car loads. DOS scrolls with `gfx_scroll_window` 0x91CF, one line per 10 ms
  tick, out then in. Directions: dir −1 moves both pictures up, dir +1 both down.
* **Caching:** `.ST`/`.SB` stay loaded per car index (20 slots) until `car_select` exits or a load fails; DOS
  reloads through `load_archive`'s name cache.
* **Drive-away** (FORMATS.md lists the script and motion differences): the Amiga first fades colours 29–31 to
  black, copies the shown view to the hidden one, and plays `sfx/Starter`. Both wheels use the same phase
  `((x+4)/5)%3` (DOS rear wheel `dist % 3`). Frames 9/2 VBL (150/33 ms) vs DOS 30/6 ticks (300/60 ms); motion
  `vel += 12000; x += vel >> 16` vs `vel += 10; dist += vel >> 4`. D:0346 ends it early (DOS: not
  interruptible). It ends with 10 VBL (0.17 s) and stops channel 3 (DOS `delay_ticks(100)` = 1 s).
* **Shape lists:** `res_find_list` 0x10B22 takes a 0-terminated list of longs with mode codes 0–5 (1 = store the
  shape, 2 = store a generated mask) and stores 0 for a missing name. DOS `res_find_list` 0x94C7 takes a string
  of 4-character names and `res_find` is fatal on a missing name.

---

## 8. Open questions

1. **Dissolve speed.** 0x109D0 runs its 8 passes back to back with no frame wait (each pass touches
   200 × 10 longs × 5 planes, with read-modify-write, while the display is live). Estimated at roughly 0.1–0.2 s
   per pass on a 7 MHz A500 with 5-plane DMA contention, so about 1 s in total, but this is not measured. The
   port needs a fixed pace (for example one pass per 1–2 frames); what the real machine does should be checked
   in an emulator. Owned by platform_video.
2. **Negative and off-screen ViewPort offsets.** The logo starts at DyOffset −35, and `DxOffset` reaches about
   −330 in both drive-offs. How graphics.library 1.x `MakeVPort` clips these (and what fills the vacated area:
   COLOR00 of that ViewPort, or the background) is assumed, not verified.
3. **D:0346 key.** `poll_input` sets it for converted key code 0x12, which is Ctrl-R with the default keymap
   (likely). platform_video / game_flow should confirm through 0x1563A/0x17BF0.
4. **TDScroller race.** `show_car` frees the task's stack and Task structure as soon as D:2824 = 1, before the task
   has executed its final `rts`. This is safe only because the task (priority 5) runs to its end without being
   pre-empted by the priority-0 main task. Irrelevant for the port if the scroll runs synchronously.
5. **Overlay residency.** *Settled in the merge:* the overlay manager patches stubs and never unloads, but
   `main` unloads overlay 1 before each game and overlay 2 after it (0x162E0). Overlay 2's calls to 0x1C62E load
   overlay 1 again, so both can be resident together. README corrected. Irrelevant to the port, which links
   everything.
6. **Buffer limits.** `showroom_drive_away` has room for 50 script entries; `g_stCache`/`g_sbCache` have 20 slots
   (Cars.txt allows up to 29 cars). The shipped data stays within both.
7. **`view_copy` 0x1580C** (palette + `BltBitMap` per ViewPort pair) is assumed to copy the whole bitmap; the
   BltBitMap arguments were not decoded here (platform_video).
8. **Frame pacing with `MrgCop`.** Loops that call `MakeVPort` + `MrgCop` + `LoadView` every VBL (logo drop,
   scrolls) may take two VBLs per step on real hardware; the nominal rate is used above.
9. **PAL/NTSC.** *Resolved*: the port uses the NTSC 60 Hz VBL (port/amiga/README.md, *Decisions* 1); the
   `Delay` waits stay 1/50 s.
