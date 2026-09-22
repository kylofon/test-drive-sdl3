# Platform layer: display, input, timing, files, runtime (Amiga `td`, root hunk)

Scope: the root-hunk platform code of the Amiga release that is not audio (see `platform_audio`) and not game
logic (see `game_flow`, `drive_sim`, `drive_scene`, `title_select`). That covers the display set-up (two
graphics.library Views), the ILBM loader, the bitplane dissolve, the hand-written blitter routines, text through
graphics.library, the `Ticks VBLInt` server and the timing helpers, keyboard (input.device handler + console.device
`RawKeyConvert`) and joystick, the `Pckd` file loader and memory allocator, the overlay manager, the fixed-point math
helpers, the Aztec C runtime (identified only), the copy protection, and the few intuition calls.

Conventions: functions by image address (`0x10E3A`), globals `D:xxxx` (offset in the data hunk; A4-relative
displacement d is `D:(0x7FFE + d)`). `int` is 16-bit (Aztec C), `long` 32-bit, all data big-endian. Constants are
kept in hex. Confidence: **verified** = read in the disassembly (`tools/amigaidx.py dis`), **likely**, **guess**.
The Ghidra decompile (`port/amiga/decomp/td.c`) drops stack arguments of many calls, so every call and argument
below was re-read from the disassembly. Throwaway files: `work/amiga/scratch/platform_video/` (`root.dis`, `ov.dis`,
`glue.txt`, `unp/`).

The DOS counterpart is `port/spec/platform.md` (TDEGA.EXE 0x4941–0xC99F). The column "DOS" in the function table
gives the DOS address/name from `port/symbols.csv` when the function does the same job; "≈" marks a counterpart
with different internals.

---------------------------------------------------------------------------------------------------------------

## 1. Overview

### 1.1 What the platform layer does

* **Start-up and shut-down** (`main` 0x10018, owned by game_flow, calls these in this order): save
  `pr_WindowPtr` and set it to −1 (no DOS requesters), lower the task priority to 0 (0x117E8), open intuition and
  graphics (0x11554); with the command-line argument `p` (the Startup-Sequence runs `td >nil: p`) close the CLI
  window and the Workbench screen (0x1032C) and let the input handler swallow every key; build the two Views
  (0x115BC); install the `Ticks VBLInt` server (0x1180E); install the input handler (0x154E4); sfx init; run the copy
  protection (0x10588); song init; `WaitTOF`; turn sprite DMA off and blank sprites 0/1; make the CIA-A fire bit an
  input (0x153CC); the no-op BLTPRI write (0x1042E). Exit reverses it (0x1044C, sprite DMA back on, 0x155C4,
  0x1185C, 0x11756, 0x115A0, free all memory, restore `pr_WindowPtr` and the task priority).
* **Display.** No intuition screens. Two graphics.library Views A (`D:293E`) and B (`D:2950`), each one 320×200
  5-plane lowres ViewPort with its own BitMap (5 × 8000 bytes of chip RAM) and 32-colour ColorMap, are built once by
  `display_init` 0x115BC. `show_view` 0x1C62E (overlay 1, title_select) `LoadView`s one of them and records which is
  front/back. Everything draws into the back View's planes and flips. Screens are loaded with `ilbm_to_view`
  0x1063A (clears the view, decodes BMHD/CMAP/BODY and the custom `CMP2` chunk), copied with `view_copy` 0x1580C
  (palette + `BltBitMap`), and changed with the CPU-driven bitplane dissolve 0x109D0.
* **Shapes** are drawn by the hand-written blitter routines 0x10D14–0x11552 that program the custom chips
  directly: word-aligned cookie-cut/copy (0x10E88), pixel-shifted cookie-cut/copy (0x110C4), shifted XOR
  (0x111E6), word-aligned XOR (0x11432), rectangle clear/fill of one plane (0x10D72/0x10DBE). All clip against
  `D:0380..D:0386` and write the five planes listed in `D:0BEC`. Masks for cookie-cut are built at load time by
  OR-ing the planes (0x10C5A) into an arena (0x10BA8/0x10BDC).
* **Text** uses graphics.library `Text` with ROM `topaz.font` 8 in one RastPort `D:2876` (0x13250).
* **Timing.** `Ticks VBLInt` 0x118B2 (priority −80) counts `tick_count D:03D8` (u32, 60 Hz: the port runs NTSC) and, in the
  drive, implements the `O` option (joystick+fire gear selection, see drive_sim). Waits use dos `Delay` (1/50 s),
  graphics `WaitTOF`, or loops on `D:03D8`.
* **Input.** An input.device handler (priority 127) queues up to 10 raw key-down events (code + qualifier) and
  swallows them; `get_key` pops one, `key_to_ascii` converts it with console.device `RawKeyConvert`.
  `poll_input` 0x10462 handles the global hot keys (P, M, S, D, O, Ctrl-R). The joystick is read directly
  (`JOY1DAT`, CIA-A PRA bit 7).
* **Files and memory.** `load_file` / `load_file_chip` 0x149D2/0x149E8 → 0x149FE loads a whole file, unpacking
  `Pckd` containers (ARC methods 2/3/4/8, same decoder as DOS). All memory comes from `mem_alloc` 0x15930
  (`AllocMem` with `MEMF_CLEAR`, guard words, one global list freed at exit).
* **Overlays.** The Aztec overlay manager 0x168A4 loads a node on the first call through one of its stubs;
  `ovl_unload` 0x162E0 **does unload** it again. `main` unloads overlay 1 after the car selection and overlay 2
  after each drive (settles the question in `prior_results.md`, see §4.14).

### 1.2 Call graph (main functions)

```
_start 0x163B0 ─ _main 0x1642A ─ main 0x10018 [game_flow]
  ├─ set_task_pri 0x117E8            ├─ open_libraries 0x11554
  ├─ close_workbench 0x1032C ('p')   ├─ display_init 0x115BC ─ InitView/InitVPort/InitBitMap/InitRastPort,
  │                                  │                          GetColorMap, alloc_chip ×10, MakeVPort, MrgCop
  ├─ vbl_install 0x1180E ─ AddIntServer(5) → vbl_server 0x118B2 ─ read_fire_raw 0x11872, read_joy_raw 0x11886,
  │                                                              [drive_sim 0x1EE76, 0x20826 via overlay stubs]
  ├─ input_init 0x154E4 ─ CreatePort/CreateStdIO/OpenDevice input.device, IND_ADDHANDLER → input_handler 0x15698
  │                     └ OpenDevice console.device (unit −1) → ConsoleDevice D:28EE
  ├─ protection_check 0x10588 ─ prot_measure_setup 0x11954, prot_read_track 0x11A0A, prot_crc 0x11D8E
  ├─ fire_port_init 0x153CC          ├─ blit_priority_on/off 0x1042E/0x1044C (write nowhere)
  └─ exit: input_shutdown 0x155C4, vbl_remove 0x1185C, display_shutdown 0x11756, close_libraries 0x115A0,
           free_mem(−1)

screens (game_flow, title_select, drive_scene):
  load_file 0x149D2 / load_file_chip 0x149E8 ─ load_file_flags 0x149FE ─ Lock/Examine/Open/Read
        └ pckd_unpack 0x14C9C ─ pack_getc 0x14ED6 / pack_putc 0x14EF2 / rle90_out 0x14E6C
                               huff_read_tree 0x14D64 / huff_decode 0x14DE0 / lzw_decompress 0x14F0E
  ilbm_to_view 0x1063A ─ view_clear 0x1574E ─ ilbm_parse 0x106BE ─ iff_next_chunk 0x10692
        ├ cmap_to_rgb4 0x107B4   ├ cmp2_to_rgb4 0x1086E
        └ ilbm_decode_body 0x10906 ─ unpack_byterun1_row 0x15344 ; WaitTOF ; LoadRGB4
  view_copy 0x1580C ─ view_copy_palette 0x1582C (LoadRGB4) ; view_copy_bitmaps 0x1587C (BltBitMap)
  view_dissolve 0x109D0 ─ dissolve_pass 0x10AA2 ×8
  show_view 0x1C62E [title_select] ─ LoadView

shapes:
  OwnBlitter ─ set_clip_full 0x10FA4 / set_clip 0x10FBC ─ blit_set_dest 0x10E26
     ─ blit_shape_word 0x10E3A → 0x10E88 ─ blit_prep_word 0x10FDA ─ blit_wait_hw 0x10D44
     ─ blit_shape 0x10E58 → 0x110C4 ─ blit_prep_shift 0x112E4
     ─ blit_shape_xor 0x111E6 (0x112E4) ; blit_shape_xor_word 0x11432 (0x10FDA)
     ─ blit_clear_rect 0x10D72 / blit_fill_rect 0x10DBE
  ─ blit_wait 0x10E78 ─ DisownBlitter
  find_shape 0x15472 ─ 0x15490 ; make_mask 0x10C5A ─ arena_alloc 0x10BDC

input:  poll_input 0x10462 ─ key_available 0x156EC, get_key 0x156F8, key_to_ascii 0x1563A (RawKeyConvert), toupper
        joy_fire 0x153E4 / joy_dir 0x153EC ─ read_fire 0x15402 / read_joy 0x15416
        quit_requested 0x1544E ─ Chk_Abort 0x17418
text:   text_init 0x13250 ─ text_print 0x13306, text_move 0x13330, text_set_pen 0x13354, draw_box_outline 0x1336E,
        erase_rect 0x1343A, text_cursor 0x134F2
overlays: stub → ovl_load 0x168A4 ─ ovl_loadseg 0x1691C (Seek, LoadSeg) ; ovl_unload 0x162E0 (FreeMem, re-stub)
```

---------------------------------------------------------------------------------------------------------------

## 2. Function table

Columns: address | name | signature | purpose | DOS | confidence. `asm:` = register interface (called from
assembly-style callers in overlay 2).

### 2.1 Start-up, system, protection

| Addr | Name | Signature | Purpose | DOS | Conf. |
|---|---|---|---|---|---|
| 0x10018 | main | `int main(int argc, char **argv)` | see game_flow | 0x0010 main | — |
| 0x1032C | close_workbench | `void (void)` | `CloseWindow(IntuitionBase->ActiveWindow)` (+0x34), `CloseWorkBench()`; only with argument `p` | — | verified |
| 0x10346 / 0x10402 | read_cars_txt / skip_line | | see game_flow | 0x0243 | — |
| 0x1042E | blit_priority_on | `void (void)` | `D:281C = *(u16*)0xBFF002 & 0x400; *(u16*)0xBFF096 = 0x8400` — meant DMACONR/DMACON BLTPRI, hits no chip (§5) | — | verified |
| 0x1044C | blit_priority_off | `void (void)` | if `D:281C == 0`: `*(u16*)0xBFF096 = 0x0400` (no effect) | — | verified |
| 0x10588 | protection_check | `void (void)` | Long-track check on cyl 0 heads 1/0 and self-CRC; on failure sets `D:1E94` and corrupts code (§4.16) | 0x8DC7 copy_protection_check | verified |
| 0x10632 | nop_10632 | `void (void)` | empty (`link/unlk`), no callers | — | verified |
| 0x11554 | open_libraries | `void (void)` | `OpenLibrary("intuition.library",0)` → D:03D0, `("graphics.library",0)` → D:03D4 (no failure check) | — | verified |
| 0x115A0 | close_libraries | `void (void)` | `CloseLibrary(GfxBase)`, `CloseLibrary(IntuitionBase)` | — | verified |
| 0x117E8 | set_task_pri | `int (int pri)` | `SetTaskPri(FindTask(0), pri)`, returns old priority | — | verified |
| 0x11954 | prot_measure_setup | `int (char *volname)` | Protection module entry: own data block, `Lock`/`Info` of "TEST DRIVE:", trackdisk + disk.resource, returns CRC-16/0x8005 of 0x11954..0x11E00 | — | verified |
| 0x119A8–0x11DD3 | prot_* | asm | Protection internals: trackdisk ETD_* commands, disk.resource `GetUnit`/`GiveUnit`, own DSKBLK interrupt 0x11D1E, raw MFM track read (DSKSYNC 0x4489), header decode 0x11D3A, CRC 0x11DB0 (§4.16) | 0x8DF1–0x91CF | verified |
| 0x119B6 | prot_code_len | `long (void)` | `min(max(−*(long*)0x11E00, …), 0x5000)`: byte length of the protection module for the CRC | — | verified |
| 0x119D0 | prot_code_start | `void *(void)` | returns 0x11954 | — | verified |
| 0x119D8 | prot_cleanup | `void (void)` | motor off, `CloseDevice`, free signal, `FreeEntry` | — | verified |
| 0x11A0A | prot_read_track | `int (long cyl, long head)` | Seeks, DMA-reads 0x3690 bytes raw, returns the measured gap length (patched to a constant on this disk) | — | verified |
| 0x11D8E | prot_crc | `u16 (void *p, long nwords, long init, long poly)` | CRC-16, MSB first (0x11DB0 core) | — | verified |
| 0x1530E | rand16 | `int (void)` | LCG `s = s*0x1AFB + 0x1FCCD` stirred with `VHPOSR` | ≈ 0xA90E rand / 0x8BAF rand8 | verified |
| 0x1544E | quit_requested | `int (void)` | Sticky Ctrl-C flag `D:1BDA` from `Chk_Abort` (SIGBREAKF_CTRL_C); disables Aztec's abort | — | verified |
| 0x10CEC, 0x10CF4, 0x10D04 | nop_10cec … | `void (void)` | empty functions (0x10CEC called once by 0x1C900) | — | verified |

### 2.2 Display, pictures, dissolve

| Addr | Name | Signature | Purpose | DOS | Conf. |
|---|---|---|---|---|---|
| 0x115BC | display_init | `void (void)` | Build View/ViewPort/BitMap/RasInfo/RastPort/ColorMap A and B, 2×5 planes of 8000 bytes chip, `MakeVPort`+`MrgCop`; saves `ActiView` | ≈ 0x4D96 gfx_init_ega | verified |
| 0x11756 | display_shutdown | `void (void)` | `show_view(saved ActiView)`, free planes, `FreeColorMap`×2, `FreeVPortCopLists`×2, `FreeCprList`×2, `DMACON = 0x8020` | ≈ 0x50FE gfx_shutdown | verified |
| 0x1C62E | show_view | `void (View *v)` | see title_select | — | — |
| 0x1063A | ilbm_to_view | `void (u8 *iff, View *v)` | `view_clear(v)`; if `FORM`…`ILBM` → `ilbm_parse` | — | verified |
| 0x10692 | iff_next_chunk | `void (u8 *base, long *off)` | `*off = (*off + len(base+*off) + 9) & ~1` | — | verified |
| 0x106BE | ilbm_parse | `void (u8 *form, View *v)` | Walk chunks (BMHD, BODY, CMAP, CMP2) up to FORM size / 40000 bytes, then decode | — | verified |
| 0x107B4 | cmap_to_rgb4 | `void (u8 *chunk, u16 pal[32])` | Default fill from D:0358, then ≤32 RGB triplets → 12-bit | — | verified |
| 0x1086E | cmp2_to_rgb4 | `void (u8 *chunk)` | Custom `CMP2`: first word → D:281E (split line), ≤32 triplets from +0xC → D:2FCE | — | verified |
| 0x10906 | ilbm_decode_body | `void (BMHD *h, u16 pal[32], u8 *body, View *v)` | ByteRun1 rows into the first ViewPort's planes; `WaitTOF`; `LoadRGB4(vp, pal, 32)` | — | verified |
| 0x109D0 | view_dissolve | `void (View *src_or_NULL, View *dst)` | 8 CPU passes, one bit column per byte each; NULL = to black | ≈ 0x768B gfx_dissolve | verified |
| 0x10AA2 | dissolve_pass | `void (int k, int depth, u8 **srcpl, u8 **dstpl, int clear)` | One pass over 200 rows in order 7r mod 200 | ≈ 0x768B | verified |
| 0x1574E | view_clear | `void (View *v)` | For every ViewPort: `LoadRGB4` zeros (1 << Depth), `BltClear` every plane | ≈ 0x4B98 gfx_clear_screen | verified |
| 0x1580C | view_copy | `void (View *src, View *dst)` | `view_copy_palette` + `view_copy_bitmaps` | — | verified |
| 0x1582C | view_copy_palette | `void (View *src, View *dst)` | Per ViewPort pair: `LoadRGB4(dstvp, srcvp->ColorMap->ColorTable, srcvp->ColorMap->Count)` | — | verified |
| 0x1587C | view_copy_bitmaps | `void (View *src, View *dst)` | Per ViewPort pair: `BltBitMap(src,0,0,dst,0,0,BytesPerRow*8,Rows,0xCC,0xFF,NULL)` | ≈ 0x8B08 gfx_grab_screen | verified |
| 0x15344 | unpack_byterun1_row | `void (u8 **src, u8 **dst, int n)` | ByteRun1 decode until n bytes produced; advances both | — | verified |
| 0x14984 | draw_shape_on_view | `void (Shape *s, View *v)` | `set_clip_full`, `OwnBlitter`, dest = v's planes, `blit_shape_word(s, NULL, s->x, s->y)`, wait, `DisownBlitter` | ≈ 0x5DE2 blit_copy_clip_own | verified |

### 2.3 Blitter and shapes

| Addr | Name | Signature | Purpose | DOS | Conf. |
|---|---|---|---|---|---|
| 0x10D14 | blit_begin | `void (void)` | wait; BLTAMOD=BLTDMOD=0, BLTCON0=0x09F0, BLTCON1=0, FWM=LWM=0xFFFF (call-table slots 0x17C4C and 0x17C52 both point here) | — | verified |
| 0x10D3C | blit_nasty_off | asm | `DMACON = 0x0400` (BLTPRI off); no callers | — | verified |
| 0x10D44 | blit_wait_hw | asm (A6=$DFF000) | Poll DMACONR bit 14 until 10 consecutive not-busy reads; counts in D:034C/D:0348 | — | verified |
| 0x10D66 | read_dmaconr | `u16 (void)` | returns DMACONR; no callers | — | verified |
| 0x10D72 | blit_clear_rect | asm: a0 plane, d0 x, d1 y, d2 width bytes, d3 h | Clear a word-aligned rectangle of one plane (BLTCON0 0x0100) | ≈ 0x97D4 rect_clear_plane | verified |
| 0x10DBE | blit_fill_rect | asm: same | Set a rectangle of one plane to 1s (BLTCON0 0x01FF) | ≈ 0x981E rect_set_plane | verified |
| 0x10E12 | shape_pos | asm: a0 shape → d0 = +8, d1 = +0xA | Shape's own x, y | ≈ `*_own` variants | verified |
| 0x10E1C | shape_sub_hot | asm: d0 −= +4, d1 −= +6 | Hot-spot adjust | ≈ `*_hot` variants | verified |
| 0x10E26 | blit_set_dest | `void (u8 *planes[5])` | Copy 5 plane pointers to D:0BEC | ≈ 0x5128 gfx_select_target | verified |
| 0x10E3A | blit_shape_word | `void (Shape *s, Shape *mask, int x, int y)` | C wrapper → 0x10E88 (A6=$DFF000) | ≈ 0x4E05 blit_or_clip_raw / 0x5DB6 blit_copy_clip_raw | verified |
| 0x10E58 | blit_shape | `void (Shape *s, Shape *mask, int x, int y)` | C wrapper → 0x110C4 | ≈ 0x4E05 / 0x5DB6 | verified |
| 0x10E78 | blit_wait | `void (void)` | C wrapper → 0x10D44 | — | verified |
| 0x10E88 | blit_shape_word_asm | asm: a0 s, a1 mask, d0 x, d1 y | x & ~15, cookie-cut 0x0FCA with mask, plain copy 0x05CC without | ≈ 0x5DE2 | verified |
| 0x10F9C | blit_params_ptr | asm → a0 = d0 = &D:0362 | not in the index; no callers found | — | verified |
| 0x10FA4 | set_clip_full | `void (void)` | clip y 0..200, x 0..320 | ≈ 0x50A1 gfx_set_clip | verified |
| 0x10FBC | set_clip | asm: d0 top, d1 bottom, d2 left, d3 right | store to D:0380..D:0386, x values & 0xFFF0 | 0x50A1 gfx_set_clip | verified |
| 0x10FDA | blit_prep_word | asm: a0 s, a1 mask, d0 x, d1 y, a2 params → C set = nothing to draw | Clip, word-aligned parameters | ≈ 0x5DE2 | verified |
| 0x110C4 | blit_shape_asm | asm: a0 s, a1 mask, d0 x, d1 y | Shifted cookie-cut 0x0FCA or masked copy 0x07CA (BLTADAT=0xFFFF) | ≈ 0x4E05 | verified |
| 0x111E6 | blit_shape_xor | asm: a0 s, d0 x, d1 y (a1 passed through) | Shifted XOR: 0x076A, BLTADAT=0xFFFF (D = C ^ B inside the edge masks) | 0x806C blit_xor_clip_raw | verified |
| 0x112E4 | blit_prep_shift | asm: like 0x10FDA | Clip, shifted parameters (extra word, FWM/LWM, modulo −2) | — | verified |
| 0x11432 | blit_shape_xor_word | asm: a0 s, d0 x, d1 y | Word-aligned XOR (0x0B5A, D = A ^ C) with the right edge masked to the true clip | 0x806C | verified |
| 0x10B22 | res_find_list | | see title_select | 0x94C7 | — |
| 0x10BA8 | arena_new | `Arena *(long size)` | `p = alloc_chip(size); p->size = size; p->used = 8` | — | verified |
| 0x10BDC | arena_alloc | `void *(Arena *a, long n)` | bump allocation if `size − used ≥ n`, else 0; clears D:0360 | — | verified |
| 0x10C28 | arena_free_bytes | `long (Arena *a)` | `size − used`; no callers | — | verified |
| 0x10C3E | mask_size | `long (Shape *s)` | `width_bytes * height + 0x10` | — | verified |
| 0x10C5A | make_mask | `Shape *(Arena *a, Shape *s)` | 1-plane shape = OR of all planes (header copied, planes = 1) | — | verified |
| 0x15472 | find_shape | `Shape *(Archive *a, long name4)` | see FORMATS.md; 0 when missing | ≈ 0x6762 res_find | verified |
| 0x15490 | find_shape_asm | asm: a0 archive, d0 name → a0 | body of 0x15472 | — | verified |

### 2.4 Text (graphics.library)

| Addr | Name | Signature | Purpose | DOS | Conf. |
|---|---|---|---|---|---|
| 0x13250 | text_init | `void (void)` | RastPort D:2876 (bitmap A), `OpenFont(topaz 8)` → D:2872, `SetFont`, APen 1, `SetDrMd(JAM1)` | — | verified |
| 0x132E6 | text_shutdown | `void (void)` | `CloseFont`, free the RastPort | — | verified |
| 0x13306 | text_print | `void (char *s)` | `Text(rp, s, strlen(s))` | ≈ 0x4BE7 gfx_draw_text_at_cursor | verified |
| 0x13330 | text_move | `void (int x, int y)` | `Move(rp, x, y)` (y = baseline) | ≈ 0x74E3 gfx_set_text_cursor | verified |
| 0x13354 | text_set_pen | `void (int c)` | `SetAPen(rp, c)` | ≈ 0x6C85 gfx_set_text_colours | verified |
| 0x1336E | draw_box_outline | `void (int x0, int y0, int x1, int y1)` | pen 1, JAM1, `Move`+4×`Draw`, pen restored | 0x9530 draw_rect_outline | verified |
| 0x1343A | erase_rect | `void (int x0, int y0, int x1, int y1)` | pen 0, JAM1, `RectFill`, pen/mode/cursor restored | ≈ 0x4941 gfx_fill_rect | verified |
| 0x134F2 | text_cursor | `void (void)` | pen 0x1F, COMPLEMENT: `RectFill(cx, cy−8, cx+8, cy+1)`; restore | ≈ 0x9A69 draw_glyph | verified |

### 2.5 Timing and interrupts

| Addr | Name | Signature | Purpose | DOS | Conf. |
|---|---|---|---|---|---|
| 0x1180E | vbl_install | `void (void)` | Interrupt D:2E12 {NT_INTERRUPT, pri −80, "Ticks VBLInt", data &D:03D8, code 0x118B2}; `AddIntServer(INTB_VERTB=5)`; stores A4 at 0x118AE | ≈ 0x699E timer_install_menu | verified |
| 0x1185C | vbl_remove | `void (void)` | `RemIntServer(5, &D:2E12)` | ≈ 0x694A timer_restore | verified |
| 0x118B2 | vbl_server | server (A1 = &D:03D8) | `tick_count++`; fire/`O`-mode joystick gear selection (§4.9); returns Z | ≈ 0x6A1F timer_isr | verified |
| 0x11872 | read_fire_raw | asm → d0 | `(~CIAA_PRA >> 7) & 1` | — | verified |
| 0x11886 | read_joy_raw | asm → d0 | direction 0–8 from JOY1DAT via D:03DC | — | verified |
| 0x175EA | dos_Delay | `void (long ticks)` | dos `Delay` (−198), 1/50 s | 0x6C3B delay_ticks | verified |
| 0x17B9A | gfx_WaitTOF | `void (void)` | graphics `WaitTOF` (−270) | — | verified |

### 2.6 Input

| Addr | Name | Signature | Purpose | DOS | Conf. |
|---|---|---|---|---|---|
| 0x10462 | poll_input | `void (void)` | One queued key: P pause (drive), M music, S sound, D and O toggles (drive), Ctrl-R → D:0346 | ≈ 0x5C24 input_poll_drive | verified |
| 0x153CC | fire_port_init | `void (void)` | CIA-A DDRA &= 0x7F (fire of port 2 = input) | — | verified |
| 0x153E4 | joy_fire | `int (void)` | `D:2858 = read_fire()`; returns it | ≈ 0xA12F joy_read | verified |
| 0x153EC | joy_dir | `int (void)` | `D:2512 = read_joy()`; returns it | ≈ 0xA12F joy_read | verified |
| 0x153F4 | joy_read_both | asm | both of the above; not in the index, no callers | — | verified |
| 0x15402 | read_fire | asm → d0 | same as 0x11872 | — | verified |
| 0x15416 | read_joy | asm → d0 | same as 0x11886 with its own table at 0x1543E | — | verified |
| 0x154E4 | input_init | `void (int passmask)` | Handler + console.device (§4.10) | ≈ 0x8AFD input_set_mode | verified |
| 0x155C4 | input_shutdown | `void (void)` | close console, `IND_REMHANDLER`, close input.device, delete ports/requests | — | verified |
| 0x15698 | input_handler | handler (A0 = event chain) | first event only: queue raw key-downs, swallow keys | — | verified |
| 0x156EC | key_available | asm → d0 | `D:240C ? −1 : 0` | — | verified |
| 0x156F8 | get_key | `long (void)` | `WaitTOF` until a key is queued; pop `(qualifier << 16) | code` under `Forbid` | 0x67DD getkey_wait | verified |
| 0x15628 | get_char | `int (void)` | `key_to_ascii(get_key())` | 0x67DD getkey_wait | verified |
| 0x1563A | key_to_ascii | `int (long qual_code)` | `RawKeyConvert` of one IECLASS_RAWKEY event, default keymap, 1-byte buffer; 0 if no single char | — | verified |
| 0x15D1C | toupper | `int (int c)` | a–z → A–Z | 0x95D9 toupper_c | verified |
| 0x15D34 | tolower | `int (int c)` | A–Z → a–z; no callers | — | verified |

### 2.7 Files, memory, overlays

| Addr | Name | Signature | Purpose | DOS | Conf. |
|---|---|---|---|---|---|
| 0x149D2 | load_file | `void *(char *name)` | `load_file_flags(name, 0x10001)` | ≈ 0x8A5B load_archive | verified |
| 0x149E8 | load_file_chip | `void *(char *name)` | `load_file_flags(name, 0x10003)` | ≈ 0x8A5B | verified |
| 0x149FE | load_file_flags | `void *(char *name, long memflags)` | Whole file, `Pckd` unpacked; result in D:24BC, size in D:2810; 0 on any error | ≈ 0x9A86 load_packed_archive | verified |
| 0x14C8C | pckd_unpacked_len | `long (u8 *hdr)` | `*(long*)(hdr+8)` | — | verified |
| 0x14C9C | pckd_unpack | `void (u8 *pckd, u8 *out)` | method 2 stored, 3 RLE90, 4 squeeze, 8 crunch; others: nothing | 0x9A86 (body) | verified |
| 0x14D64 | huff_read_tree | `void (void)` | method-4 tree | 0x9C1E huff_read_tree | likely |
| 0x14DC6 | huff_read_word | `int (void)` | two input bytes | 0x9C76 huff_read_word | likely |
| 0x14DE0 | huff_decode | `int (void)` | next symbol or −1 | 0x9C90 huff_decode | likely |
| 0x14E6C | rle90_out | `void (u8 c)` | RLE90 state machine (D:1FBC, last D:23EC) | 0x9CF9 rle90_out | verified |
| 0x14ED6 | pack_getc | `int (void)` | next input byte or −1 when D:1FBE is 0 | 0x9D64 pack_getc | verified |
| 0x14EF2 | pack_putc | `void (u8 c)` | `if (++out_count < unpacked_len) *out++ = c` — **drops the last byte** (README bug 3, fixed by default) | 0x9DD3 pack_putc | verified |
| 0x14F0E | lzw_decompress | `void (void)` | method 8 → rle90_out | 0x9E1D lzw_decompress | likely |
| 0x1506C | lzw_getcode | `int (void)` | code reader (9..12 bits) | 0x9FA2 lzw_getcode | likely |
| 0x15192 / 0x151D6 | lzw_alloc_tables / lzw_free_tables | `void (void)` | `alloc_public` / `free_mem` of D:1BD2 | 0xA0CF / 0xA111 | verified |
| 0x151F2 / 0x15208 / 0x1521E | load_raw / load_raw_chip / load_raw_flags | `void *(char *)` | Old loader without `Pckd`; **no callers** (0x151F2 is the protection's poke target) | ≈ 0x78A5 load_raw_archive | verified |
| 0x15930 | mem_alloc | `void *(long size, long flags)` | `AllocMem((size+0x17)&~3, flags|MEMF_CLEAR)`, 16-byte header, "MemB"/"MemE" guards, global list | ≈ 0xA340 buf_alloc | verified |
| 0x15904 | alloc_public | `void *(long size)` | `mem_alloc(size, 0x10001)` | ≈ 0xA730 malloc | verified |
| 0x1591A | alloc_chip | `void *(long size)` | `mem_alloc(size, 0x10003)` | — | verified |
| 0x159FA | free_mem | `int (void *p)` | 0: nothing; −1: free all; else validate guards/links, unlink, `FreeMem`; −1 on a bad block | ≈ 0xA37E buf_free | verified |
| 0x15B3E | mem_check | `int (void *p)` | Heap walker/validator (−1 all, −2 all quiet); only self-calls | ≈ 0xA3DF mem_debug_dump | verified |
| 0x15C60 | mem_size | `long (void *p)` | block size − 0x14; no callers | — | verified |
| 0x168A4 | ovl_load | overlay supervisor | Load node of the calling stub, patch its stubs to `jmp abs.l`, re-run the call | — | verified |
| 0x1691C | ovl_loadseg | asm | `OpenLibrary("dos.library")`, `Seek` until OK, `LoadSeg(0, seglist, fh)` until OK, append; `Alert(0x0700000C)` if dos fails | — | verified |
| 0x162E0 | ovl_unload | `void (void *stub)` | If the stub is loaded: `FreeMem` the node's hunks, unlink them from the seglist, rewrite its stubs as `bsr ovl_load` | — | verified |

### 2.8 Fixed-point math helpers (used by overlay 2; see drive_sim / drive_scene for use)

| Addr | Name | Signature | Purpose | DOS | Conf. |
|---|---|---|---|---|---|
| 0x11E08…0x11EA6 | c_fix_* | C wrappers (link/unlk) | stack → registers for 0x11F94, 0x11FD6, 0x1200E, 0x12056, 0x1205E, 0x11F52, 0x12066, 0x12108, 0x12146, 0x12224; none has a caller in the index (overlay code calls the cores through the call table) | — | verified |
| 0x11F52 | lmul_signed | asm d0,d1 → d0 | sign-magnitude 32×32 → low 31 bits (hi×hi term dropped), sign applied | ≈ 0xC91D _aNlmul | verified |
| 0x11F94 | fix_mul | asm d0,d1 → d0 | signed 16.16 × 16.16 → bits 16..47 of the 64-bit product (floor) | — | verified |
| 0x11FD6 | fix_div | asm d0.w a, d1.w b → d0 | `(a << 16) / b` as 16.16, signed; b = 0 → ±0x7FFFFFFF | — | verified |
| 0x1200E | isqrt | asm d0 → d0.w | Newton iteration on `|x|`, start `min(x>>1, 0xB505)` | — | verified |
| 0x12056 / 0x1205E | abs16 / abs32 | asm | absolute value | — | verified |
| 0x12066 | ltoa_dec | asm d0 → a0 | 10-digit BCD (abcd) to D:03F4, leading zeros skipped, '−' prefix; only caller has no callers | — | verified |
| 0x12108 | sin_deg_fix | asm d0 = deg 16.16 → d0 | table 0x1216C (sin(i°)·65535, 91 words) with linear interpolation of the fraction, 0..180° | — | verified |
| 0x12146 | cos_deg | asm d0.w → d0.w | table[90 − |deg|] (−90..90) | — | verified |
| 0x12224 | tan_deg_fix | asm d0.w → d0 | table 0x1224C of longs tan(2k°)·65536, index |deg|/2, sign of deg | — | verified |
| 0x11EB6, 0x11EC4, 0x11F0A | (vector helpers) | asm | not in the index, no callers; 0x11F0A reads the long at 0x11F52 (an instruction) as a constant | — | verified |

### 2.9 Debug helpers (dead)

| Addr | Name | Purpose | Conf. |
|---|---|---|---|
| 0x15CA6 / 0x15CAC | raw_putc | exec `RawPutChar` (−516) | verified |
| 0x15CBE / 0x15CCC / 0x15CD4 | raw_puts / raw_getc_wait / raw_maygetc | `RawMayGetChar` (−510) | verified |
| 0x15CE2 / 0x15CE8 / 0x15CFC / 0x15D0A | kprintf / kvprintf / raw_dofmt | exec `RawDoFmt` (−522) with 0x15CAC as PutChProc | verified |

### 2.10 Aztec C runtime (identification only)

| Addr | Name | DOS (MSC) | Notes |
|---|---|---|---|
| 0x163B0 | _start | 0xA50C _astart | save SP (D:27D8), SysBase (D:27DC), `OldOpenLibrary("dos.library")` → D:27E0 |
| 0x16422 | _stub_init | — | empty |
| 0x1642A | _main | 0xB165 _cinit | device table D:27E4 (D:1E92 × 6 bytes), CLI or Workbench start, calls `main(D:27F4, D:27F0)`, then `exit` |
| 0x16566 | _cli_parse | 0xC382 _setargv | command line → argv (D:27F0), argc (D:27F4) |
| 0x16A14 | _wb_parse | — | Workbench start: icon.library `GetDiskObject`, `FindToolType("WINDOW")`, opens that window spec as stdio (*likely*) |
| 0x1670C | strncpy | 0xAAD8 | pads with NULs |
| 0x16746 | open | 0xA776 | Aztec fd table, dos `Open`/`Lock`/`DeleteFile` |
| 0x1672E | creat | 0xB0DF | → open; no callers |
| 0x16986 / 0x1698C | strcat / strncat | 0xC4CD | 0x16986 enters 0x1698C with n = 0x7FFF |
| 0x169B0 / 0x169B6 | strcmp / strncmp | 0xAA88 | |
| 0x169E0 | strcpy | 0xC4FE | |
| 0x169F0 | _lmul | 0xC91D _aNlmul | 32×32 multiply |
| 0x16396 | strchr (index) | — | |
| 0x15D4C | sscanf | 0xAA51 | string source D:2494/D:2498 |
| 0x15D72 | _sscanf_getc | — | callback |
| 0x15DBC | _scanfmt | 0xB32F _input | scanf engine |
| 0x160E0 / 0x1611A | _scan_skipws / _scan_int | 0xB698 | |
| 0x1620C / 0x16236 | fopen / _openstream | 0xA6B1 / 0xAD3C | modes table D:1C10 |
| 0x162A8 / 0x162CA | fprintf / _fprintf_putc | 0xA6D7 | |
| 0x16AC8 / 0x16AF8 | sprintf / _sprintf_putc | 0xAA00 | |
| 0x16B14 / 0x16F92 | printf / _printf_putc | 0xA8C7 | stdout FILE at 0x19900 |
| 0x16B30 | _fmt_number | 0xBE03 | |
| 0x16BBE | _format | 0xBB73 _output | printf engine |
| 0x16ED8 | _divs32 | 0xC87A _aNldiv | signed long divide (truncates) |
| 0x16F1A / 0x16F26 / 0x16F30 | _modu32 / _divu32 / _udiv_core | 0xC87A | |
| 0x16F80 | strlen | 0xAABD | |
| 0x16FA8 / 0x16FEA | putc / _putc | — | |
| 0x17026 | _flushall | 0xC849 flushall | registered in D:27FC |
| 0x1704E | fclose | 0xA5B6 | |
| 0x170D4 | _flsbuf | 0xABE2 | |
| 0x171B6 | _getstream | 0xC523 | FILE table D:1CDA..D:1E92 (0x16 bytes each) |
| 0x171EE | _getbuf | 0xAE3F _stbuf | 0x400-byte buffer |
| 0x1724C / 0x1727E / 0x172BE / 0x172D2 | _freeall / malloc / _malloc16 / free | 0xA730 / 0xA722 | exec `AllocMem` list D:24A8 (separate from mem_alloc) |
| 0x1731E | isatty | 0xC644 | dos `IsInteractive` |
| 0x17376 | unlink | 0xC55A | dos `DeleteFile` |
| 0x1739A | write | 0xC70C | dos `Write` |
| 0x17418 | Chk_Abort | — | `SetSignal(0, 0x1000)` (reads and clears Ctrl-C); if set and `D:24AC` (Enable_Abort) → `_abort` |
| 0x17448 | _abort | 0xA4E3 abort | writes "^C\n" to `Output()`, `exit(1)` |
| 0x17474 / 0x17492 | exit / _exit | 0xB214 / 0xB22B | close fds, `D:2800` hook, `CloseLibrary`s, restore SP |
| 0x17580 | close | 0xA4F8 | |

### 2.11 Library glue (one stub per LVO; `D:27E0` DOSBase, `D:27DC` SysBase, `D:03D4` GfxBase, `D:03D0` IntuitionBase, `D:28F2` IconBase, `D:28EE` ConsoleDevice)

* dos: 0x175CE Close, 0x175DE CurrentDir, 0x175EA Delay, 0x175F6 DeleteFile, 0x17602 Examine, 0x17614 Input,
  0x1761C IoErr, 0x17624 IsInteractive, 0x17630 Lock, 0x17642 Open, 0x17654 Output, 0x1765C Read, 0x1766E Seek,
  0x1767C UnLock, 0x1768C Write.
* exec: 0x1769A AddIntServer, 0x176A8 Alert, 0x176C0 CloseDevice, 0x176CC CloseLibrary, 0x176DC CopyMemQuick,
  0x177C0 AddPort, 0x177CC AllocSignal, 0x17884 AllocMem, 0x17892 AddTask, 0x178AA DoIO, 0x178C0 FindTask,
  0x178D0 Forbid, 0x178DC FreeMem, 0x178F0 FreeSignal, 0x178FC GetMsg, 0x1791A OpenDevice, 0x17930 OpenLibrary,
  0x17944 Permit, 0x1794C RemIntServer, 0x1795A RemPort, 0x17966 RemTask, 0x17972 ReplyMsg, 0x1797E SetSignal,
  0x1798C SetTaskPri, 0x1799C WaitPort. amiga.lib-style C helpers: 0x176EE CreatePort, 0x1777A DeletePort,
  0x177D8 CreateStdIO, 0x177EE DeleteStdIO, 0x17800 CreateExtIO, 0x17844 DeleteExtIO, 0x17908 NewList.
* graphics: 0x179A8 BltBitMap, 0x179CA BltClear, 0x179DC CBump, 0x179E8 CloseFont, 0x179F4 CMove, 0x17A06 CWait,
  0x17A18 DisownBlitter, 0x17A20 Draw, 0x17A32 FreeColorMap, 0x17A3E FreeCprList, 0x17A4A FreeVPortCopLists,
  0x17A56 GetColorMap, 0x17A62 InitBitMap, 0x17A74 InitRastPort, 0x17A80 InitView, 0x17A8C InitVPort,
  0x17A98 LoadRGB4, 0x17AAA LoadView, 0x17AB6 MakeVPort, 0x17AC4 Move, 0x17AD6 MrgCop, 0x17AE2 OpenFont,
  0x17AEE OwnBlitter, 0x17AF6 RectFill, 0x17B08 ScrollRaster, 0x17B24 SetAPen, 0x17B34 SetBPen, 0x17B44 SetDrMd,
  0x17B54 SetFont, 0x17B64 Text, 0x17B7E TextLength, 0x17B92 WaitBlit, 0x17B9A WaitTOF.
* intuition: 0x17BC8 CloseWindow, 0x17BD4 CloseWorkBench, 0x17BDC DrawImage (used by game_flow 0x14388).
* icon: 0x17BA2 FindToolType (−96), 0x17BB0 FreeDiskObject (−90), 0x17BBC GetDiskObject (−78).
* console: 0x17BF0 RawKeyConvert (−48).

Names in the CSV use the prefixes `dos_`, `exec_`, `gfx_`, `int_`, `icon_`, `con_`.

---------------------------------------------------------------------------------------------------------------

## 3. Globals table

| D: | Name | Type | Meaning | Written by | Read by |
|---|---|---|---|---|---|
| 0344 | sfx_enabled | int | S key toggle (platform_audio) | 0x10462 | audio |
| 0346 | g_abortKey | int | Ctrl-R (converted key 0x12) seen → back to the intro | 0x10462, main | main, overlays |
| 0348 | blit_busy_spins | long | debug count of busy reads | 0x10D44 | — |
| 034C | blit_wait_calls | long | debug count of waits | 0x10D44 | — |
| 0358 | cmap_default | u16[3] | 0x02F2, 0x0F57, 0x022F: pre-fill of colours 4k..4k+2 | const | 0x107B4 |
| 0360 | arena_flag | int | cleared by every successful `arena_alloc`; no reader found | 0x10BDC | — |
| 0362 | blit_params | struct (0x1E) | +0 src, +4 mask, +8 dest offset, +A BLTSIZE, +C C/D modulo, +E B modulo (and A in the word path), +10 A modulo, +12 plane bytes, +14 left-clipped, +16 right-clipped, +18 shift, +1A FWM, +1C LWM | 0x10FDA, 0x112E4 | blitters |
| 0380 | clip_top | int | first visible row | 0x10FBC | 0x10FDA, 0x112E4 |
| 0382 | clip_bottom | int | row limit (exclusive) | 0x10FBC | same |
| 0384 | clip_left | int | x & 0xFFF0 | 0x10FBC | same |
| 0386 | clip_right | int | x & 0xFFF0 (exclusive); 0x11432 rounds it up temporarily | 0x10FBC, 0x11432 | same |
| 0388 | fwm_table | u16[17] | `0xFFFF >> n` | const | 0x112E4 |
| 03AA | lwm_table | u16[17] | `~(0xFFFF >> n)` (n leftmost bits) | const | 0x112E4, 0x11432 |
| 03D0 | IntuitionBase | ptr | | 0x11554 | 0x1032C, glue |
| 03D4 | GfxBase | ptr | | 0x11554 | glue, 0x115BC |
| 03D8 | tick_count | u32 | VBL counter (60 Hz, NTSC) | 0x118B2 | game_flow, title_select, audio waits |
| 03DC | joy_dir_table | u8[16] | JOY1DAT index → direction (§4.9) | const | 0x11886 |
| 03EC | vbl_last_dir | int | last stick direction seen in O mode | 0x118B2 | 0x118B2 |
| 03EE, 03F0 | (gear-gate position) | int | see drive_sim; init 0 / 1 | 0x1C900, 0x1EE76 | 0x118B2 |
| 03F2–0421 | ltoa_buf | | sign flag, 10 ASCII digits + NUL (03F4..03FE), BCD (041C..0421) | 0x12066 | — |
| 0B30 | gearbox_show (drive_sim; formerly fire_latch here) | u16 (bytes 0B30/0B31) | set 0xFFFF by the VBL in O mode while fire is down, or permanently by D mode; cleared by the VBL when fire is up unless D:24BA or D:0B34 | 0x10462, 0x118B2, overlay 2 | overlay 2 (drive_sim) |
| 0B34 | opt_d | int | D key toggle (drive only) | 0x10462 | 0x118B2, 0x1CEE2 |
| 0BEC | blit_dest | u8 *[5] | destination planes | 0x10E26 | blitters |
| 1942 | shift_table | u8 * | gear table for O mode (drive_sim) | 0x20DC0 | 0x118B2 |
| 1BC6–1BD4, 1FA8–1FC4, 23C6–23EC | pack_* | | decoder state: 1FA8 out_count, 1FB0 unpacked_len, 1FB4 in_ptr, 1FB8 out_ptr, 1FBC rle_state, 1FBE packed_left, 23EC rle_last, 1BD2 lzw_tables, 23C6.. huff/lzw state | 0x14C9C… | same |
| 1BD6 | rand_seed | u16 | | 0x1530E | 0x1530E |
| 1BD8 | rand_seeded | int | 0 → seed from VHPOSR on first call | 0x1530E | 0x1530E |
| 1BDA | quit_flag | int | sticky Ctrl-C | 0x1544E | 0x1544E |
| 1BDC | mem_list | ptr | head of the circular block list (header address) | 0x15930, 0x159FA | same |
| 1BE0 | mem_count | int | live blocks | same | 0x15B3E |
| 1C10 | _fopen_modes | table | "r", "w", … + open flags (6 bytes each) | const | 0x16236 |
| 1C58 | _ctype | u8[257] | | const | scanf |
| 1CDA–1E91 | _iob | FILE[0x16 bytes] | Aztec FILE table | runtime | runtime |
| 1E92 | _numdev | int | fd table size | const | runtime |
| 1E94 | g_startup_error | int | Cars.txt missing or protection failed → main quits | 0x10346, 0x10588 | main |
| 23EE | key_code | u8[10] | queued raw key codes | 0x15698 | 0x156F8 |
| 23F8 | key_qual | u16[10] | queued qualifiers | 0x15698 | 0x156F8 |
| 240C | key_count | int | queue length | 0x15698, 0x156F8 | 0x156EC |
| 240E | key_max | int | 10 | 0x154E4 | 0x15698 |
| 2410 / 2418 | input_port / input_io | ptr | input.device | 0x154E4 | 0x155C4 |
| 2414 / 2482 | con_port / con_io | ptr | console.device | 0x154E4 | 0x155C4 |
| 241C | input_irq | Interrupt | {pri 127, data &D:2432, code 0x15698} | 0x154E4 | input.device |
| 2486 | key_pass_qual | u16 | qualifier mask whose keys go to the system (0x5C, or 0 with `p`) | 0x154E4 | 0x15698 |
| 2488–2492 | memchk_* | | mem_check statistics | 0x15B3E | — |
| 2494, 2498 | sscanf_ptr / sscanf_eof | | | 0x15D4C | 0x15D72 |
| 249A, 249C | _scan_count / _scan_getc | | | scanf | scanf |
| 24A0 / 24A4 | _fprintf_fp / _sprintf_ptr | | | runtime | runtime |
| 24A8 | _malloc_list | ptr | Aztec malloc chain | 0x1727E | 0x1724C |
| 24AC | Enable_Abort | int | set 1 by `_main`, cleared by `main` and every `quit_requested` | 0x1642A, main, 0x1544E | 0x17418 |
| 24AE | g_paused | int | 1 while the P pause waits (and set by overlay 2) | 0x10462, overlay 2 | overlay 2 |
| 24B0 | opt_o | int | O key toggle: joystick+fire gear selection in the VBL | 0x10462 | 0x118B2, 0x20C3A |
| 24B2–24B8 | (drive_sim) | int ×4 | compared in pairs by the VBL (24B2≠24B4 or 24B6≠24B8 forces a gear update) | overlay 2 | 0x118B2 |
| 24BA | (drive_sim) | int | countdown; nonzero keeps D:0B30 | overlay 2 | 0x118B2 |
| 24BC | g_loadedBuf | ptr | last `load_file*` result | 0x149FE | callers |
| 2512 | g_joyDir | int | last `joy_dir` | 0x153EC | callers |
| 27D6 | errno | int | Aztec error | runtime | runtime |
| 27D8 | _initial_sp | ptr | | 0x163B0 | exit |
| 27DC | SysBase | ptr | | 0x163B0 | glue |
| 27E0 | DOSBase | ptr | | 0x163B0 | glue |
| 27E4 | _devtab | ptr | fd table | 0x1642A | runtime |
| 27EC / 27F0 / 27F4 | _WBenchMsg / argv / argc | | | 0x1642A, 0x16566 | main |
| 27FC / 2800 | _cln / _free_hook | fn ptr | exit hooks | runtime | 0x17474, 0x17492 |
| 2810 | g_loadedSize | long | size of the last load (unpacked size for `Pckd`) | 0x149FE | callers |
| 2814 | g_inDrive | int | 1 while overlay 2 runs (enables P, D, O) | main | 0x10462 |
| 2818 | saved_task_pri | int | | main | main |
| 281C | saved_bltpri | int | garbage read from $BFF002 & 0x400 | 0x1042E | 0x1044C |
| 281E | cmp2_line | int | line of the second palette (first word of CMP2) | 0x1086E | 0x147E4 → 0x1FB4A / 0x1FEAE |
| 2858 | g_joyFire | int | last `joy_fire` | 0x153E4 | callers |
| 285A | saved_windowptr | long | old `pr_WindowPtr` | main | main |
| 285E | this_task | ptr | `FindTask(0)` | main | main |
| 2862 | saved_task_2A | long | `task+0x2A` (tc_ExceptCode); saved, never restored | main | — |
| 2866 | saved_actiview | View * | `GfxBase->ActiView` at start | 0x115BC | 0x11756 |
| 286A / 286E | colormapA / colormapB | ColorMap * | `GetColorMap(32)` | 0x115BC | 0x11756 |
| 2872 | text_font | TextFont * | topaz 8 | 0x13250 | 0x132E6 |
| 2876 | g_tmpRastPort | RastPort * | text RastPort (BitMap = A at init) | 0x13250 | text functions, game_flow |
| 28EE | ConsoleDevice | ptr | for `RawKeyConvert` | 0x154E4 | 0x17BF0 |
| 28F2 | IconBase | ptr | Workbench start only | 0x16A14 | glue |
| 28FE / 290A | rasinfoA / rasinfoB | RasInfo | {Next 0, BitMap, RxOffset 0, RyOffset 0} | 0x115BC | graphics |
| 293E / 2950 | g_viewA / g_viewB | View | (title_select) | 0x115BC | all |
| 2942 / 2954 | viewA.LOFCprList / viewB.LOFCprList | ptr | freed at exit | graphics | 0x11756 |
| 2E12 | vbl_irq | Interrupt | "Ticks VBLInt", pri −80 | 0x1180E | exec |
| 2E8E / 2EB6 | g_vpA / g_vpB | ViewPort | DWidth 320 (2EA6/2ECE), DHeight 200, Modes 0, RasInfo | 0x115BC | title_select, drive_scene |
| 2EDE / 2F06 | g_bitmapA / g_bitmapB | BitMap | 5 planes, planes at 2EE6.. / 2F0E.. | 0x115BC | all |
| 2FCE | cmp2_palette | u16[32] | second palette of a CMP2 picture | 0x1086E | gas station, drive_scene |
| 30AE / 3112 | g_rpA / g_rpB | RastPort | BitMap A / B | 0x115BC | title_select, game_flow |

---------------------------------------------------------------------------------------------------------------

## 4. Pseudocode

Types: `s16`/`u16` = Aztec `int`/`unsigned`, `s32`/`u32` = `long`. `chip(x)` means the address is in the port's
68000 memory image (`mem[]`). `g_original_bugs` is the port's `--original-bugs` flag (not an Amiga global): its
branch is the original behaviour, the other the default fix (port/amiga/README.md, *Original bugs*; this spec
owns bug 3).

### 4.1 Start-up pieces (verified)

```c
/* in main 0x10018 (game_flow owns main; order shown for the platform calls) */
D_1E94 = 0; ...; *(u8*)0xBFD200 = 0xC0; *(u8*)0xBFD000 = 0x00;   /* CIA-B DDRA: DTR/RTS outputs, both low */
D_2818 = set_task_pri(0);
D_285E = FindTask(0); D_2862 = task->tc_ExceptCode /* +0x2A */;
D_285A = proc->pr_WindowPtr /* +0xB8 */; proc->pr_WindowPtr = (APTR)-1;  /* no "insert volume" requesters */
open_libraries();
passmask = 0x5C;                                      /* CAPS | CTRL | LALT | LAMIGA */
if (argc == 2 && argv[1][0] == 'p') { close_workbench(); passmask = 0; }
display_init(); vbl_install(); input_init(passmask);
sfx_init(); protection_check(); song_init();
WaitTOF();
DMACON = 0x0020;                                      /* sprite DMA off */
Delay(3);
*(u32*)0xDFF144 = 0; *(u32*)0xDFF14C = 0;             /* SPR0DATA/B, SPR1DATA/B = 0: pointer gone */
fire_port_init(); blit_priority_on();
... game loop ...
song_stop(); read_cars_txt(0); blit_priority_off();
DMACON = 0x8020;                                      /* sprite DMA back on */
song_stop(); song_shutdown(); sfx_shutdown(); input_shutdown(); vbl_remove();
display_shutdown(); close_libraries(); free_mem((void*)-1);
proc->pr_WindowPtr = D_285A; set_task_pri(D_2818);

void close_workbench(void)  /* 0x1032C */ { CloseWindow(IntuitionBase->ActiveWindow); CloseWorkBench(); }
s16  set_task_pri(s16 p)    /* 0x117E8 */ { return SetTaskPri(FindTask(0), (long)p); }
```

### 4.2 display_init 0x115BC / display_shutdown 0x11756 (verified)

```c
void display_init(void) {
    WaitTOF(); WaitTOF();
    D_2866 = GfxBase->ActiView;                        /* +0x22 */
    InitView(&viewA); InitView(&viewB); InitVPort(&vpA); InitVPort(&vpB);
    viewA.ViewPort = &vpA; viewB.ViewPort = &vpB;
    InitBitMap(&bmA, 5, 0x140, 0xC8); InitBitMap(&bmB, 5, 0x140, 0xC8);
    rasA = (RasInfo){0, &bmA, 0, 0}; rasB = (RasInfo){0, &bmB, 0, 0};
    vpA.DWidth = 0x140; vpA.DHeight = 0xC8; vpA.RasInfo = &rasA; vpA.Modes = 0;
    vpB.DWidth = 0x140; vpB.DHeight = 0xC8; vpB.RasInfo = &rasB; vpB.Modes = 0;
    InitRastPort(&rpA); rpA.BitMap = &bmA; InitRastPort(&rpB); rpB.BitMap = &bmB;
    D_286A = GetColorMap(0x20); D_286E = GetColorMap(0x20);
    vpA.ColorMap = D_286A; vpB.ColorMap = D_286E;
    for (s16 i = 0; i < 5; i++) { bmA.Planes[i] = alloc_chip(0x1F40); bmB.Planes[i] = alloc_chip(0x1F40); }
    MakeVPort(&viewA, &vpA); MakeVPort(&viewB, &vpB); MrgCop(&viewA); MrgCop(&viewB);
    /* no LoadView here: the first show_view() puts a View on screen */
}
void display_shutdown(void) {
    show_view(D_2866);                                 /* overlay-1 function: reloads overlay 1 if needed */
    for (i = 0; i < 5; i++) { free_mem(bmA.Planes[i]); free_mem(bmB.Planes[i]); }
    FreeColorMap(D_286A); FreeColorMap(D_286E);
    FreeVPortCopLists(&vpA); FreeVPortCopLists(&vpB);
    FreeCprList(viewA.LOFCprList); FreeCprList(viewB.LOFCprList);
    DMACON = 0x8020;
}
```
The planes are `MEMF_CLEAR` (black); ColorMaps start as the graphics.library defaults until the first `LoadRGB4`.

### 4.3 ILBM loading (verified)

```c
void ilbm_to_view(u8 *buf, View *v) {                  /* 0x1063A */
    s32 off = 0;
    view_clear(v);                                     /* palette black, planes 0 — visible if v is in front */
    if (*(u32*)(buf+off) == 'FORM' && *(u32*)(buf+off+8) == 'ILBM') ilbm_parse(buf+off, v);
}
void iff_next_chunk(u8 *base, s32 *off) {              /* 0x10692 */
    *off = (*(u32*)(base + *off + 4) + *off + 9) & ~1;  /* bclr #0: pad to even */
}
void ilbm_parse(u8 *form, View *v) {                   /* 0x106BE */
    u8 *bmhd = 0, *body = 0; u16 pal[32]; s32 off = 0xC, end = *(u32*)(form+4) + 8;
    while (off < end) {
        switch (*(u32*)(form+off)) {
        case 'CMAP': cmap_to_rgb4(form+off, pal); break;
        case 'CMP2': cmp2_to_rgb4(form+off);      break;
        case 'BMHD': bmhd = form+off+8;           break;
        case 'BODY': body = form+off+8;           break;
        }
        iff_next_chunk(form, &off);
        if (off >= 0x9C40 || off <= 0) break;          /* 40000-byte safety limit */
    }
    if (bmhd && body) ilbm_decode_body(bmhd, pal, body, v);
    /* no CMAP → pal[] is uninitialised stack */
}
void cmap_to_rgb4(u8 *ch, u16 *pal) {                  /* 0x107B4 */
    for (s16 k = 0; k < 0x20; k += 4) for (s16 j = 0; j < 3; j++) pal[k+j] = D_0358[j];  /* 02F2 0F57 022F */
    s16 n = (s16)(*(s32*)(ch+4) / 3); if (n > 0x20) n = 0x20;
    u8 *p = ch + 8;
    for (s16 i = 0; i < n; i++, p += 3)
        pal[i] = ((p[0] << 4) & 0xF00) | ((p[2] >> 4) & 0x0F) | (p[1] & 0xF0);
}
void cmp2_to_rgb4(u8 *ch) {                            /* 0x1086E, custom chunk */
    s16 n = (s16)(*(s32*)(ch+4) / 3); if (n > 0x20) n = 0x20;   /* the 4 header bytes are counted too */
    D_281E = *(u16*)(ch+8);                            /* copper split line, e.g. 0x006E = 110 in <car>Gas */
    u8 *p = ch + 0xC;
    for (i = 0; i < n; i++, p += 3) D_2FCE[i] = same conversion as above;
}
void ilbm_decode_body(u8 *bmhd, u16 *pal, u8 *body, View *v) {   /* 0x10906 */
    u8 *pl[8]; BitMap *bm = v->ViewPort->RasInfo->BitMap;
    for (u16 i = 0; i < bmhd[8] /* nPlanes */; i++) pl[i] = bm->Planes[i];
    u16 rowbytes = (*(u16*)bmhd /* w */ + 7) >> 3;
    for (u16 r = 0; r < *(u16*)(bmhd+2) /* h */; r++)
        for (u16 i = 0; i < bmhd[8]; i++) unpack_byterun1_row(&body, &pl[i], rowbytes);
    WaitTOF();
    LoadRGB4(v->ViewPort, pal, 0x20);
}
void unpack_byterun1_row(s8 **src, u8 **dst, s16 n) {  /* 0x15344 */
    s16 done = 0;
    while (done < n) {
        s16 c = *(*src)++;                             /* signed byte */
        if (c >= 0)            for (s16 k = 0; k <= c; k++) { done++; *(*dst)++ = *(*src)++; }
        else if (c != -0x80) { u8 b = *(*src)++; for (k = 0; k < 1 - c; k++) { done++; *(*dst)++ = b; } }
    }
}
```
Notes: compression and masking fields of BMHD are ignored (always ByteRun1), the plane stride is assumed to
equal `rowbytes` (all pictures are 320 wide), and a run may overshoot `n` into the next row (as in the original).

### 4.4 view_clear / view_copy (verified)

```c
void view_clear(View *v) {                             /* 0x1574E */
    u16 zero[32] = {0};
    for (ViewPort *vp = v->ViewPort; vp; vp = vp->Next) {
        BitMap *bm = vp->RasInfo->BitMap;
        u32 n = (u16)(bm->Rows * bm->BytesPerRow);
        LoadRGB4(vp, zero, 1L << bm->Depth);
        for (u16 i = 0; i < bm->Depth; i++) BltClear(bm->Planes[i], n, 1);
    }
}
void view_copy_palette(View *src, View *dst) {         /* 0x1582C */
    ViewPort *s = src->ViewPort, *d = dst->ViewPort;
    for (;;) {
        LoadRGB4(d, s->ColorMap->ColorTable, (s32)s->ColorMap->Count);
        if (!s->Next || !d->Next) break; s = s->Next; d = d->Next;
    }
}
void view_copy_bitmaps(View *src, View *dst) {         /* 0x1587C */
    ViewPort *s = src->ViewPort, *d = dst->ViewPort;
    for (;;) {
        BitMap *a = s->RasInfo->BitMap, *b = d->RasInfo->BitMap;
        BltBitMap(a, 0, 0, b, 0, 0, a->BytesPerRow * 8, a->Rows, 0xCC, 0xFF, NULL);
        if (!s->Next || !d->Next) break; s = s->Next; d = d->Next;
    }
}
void view_copy(View *src, View *dst) { view_copy_palette(src, dst); view_copy_bitmaps(src, dst); }  /* 0x1580C */
```
`BltBitMap` with minterm 0xCC copies all planes (mask 0xFF), full width and height of the source bitmap.

### 4.5 view_dissolve 0x109D0 (verified)

```c
static const u32 dissolve_bits[8] = { 0x01010101, 0x08080808, 0x40404040, 0x02020202,
                                      0x10101010, 0x80808080, 0x04040404, 0x20202020 };   /* 0x10A82 */
void view_dissolve(View *src, View *dst) {
    if (!dst) return;
    BitMap *db = dst->ViewPort->RasInfo->BitMap; u16 depth = db->Depth;
    u8 *d[8], *s[8];
    for (i = 0; i < depth; i++) { d[i] = db->Planes[i]; if (src) s[i] = src->ViewPort->RasInfo->BitMap->Planes[i]; }
    for (s16 k = 7; k >= 0; k--) dissolve_pass(k, depth, s, d, src == NULL);
}
void dissolve_pass(s16 k, s16 depth, u8 **s, u8 **d, s16 clear) {   /* 0x10AA2 */
    u16 off = 0;                                       /* byte offset of the row */
    for (s16 r = 0; r < 0xC8; r++) {
        u32 m = dissolve_bits[(r + k) & 7];
        for (s16 l = 0; l < 10; l++)                   /* 10 longs = 40 bytes */
            for (s16 p = 0; p < depth; p++) {
                u32 *dp = (u32*)(d[p] + off + 4*l);
                *dp &= ~m;
                if (!clear) *dp |= *(u32*)(s[p] + off + 4*l) & m;
            }
        off = (u16)((off + 0x118) % 0x1F40);           /* next row = (7 × r) mod 200 */
    }
}
```
One pass sets one bit column of every byte in every row; after the 8 passes the destination equals the source
(or is 0). There is no frame sync: the dissolve runs as fast as the CPU does and the display shows the planes being
modified (usually `dst` is the front View). Only the planes are changed; palettes are copied by the callers.

### 4.6 Blitter model and shape blits (verified)

Every blitter routine writes the custom-chip registers directly (A6 = $DFF000) between the callers'
`OwnBlitter` / `DisownBlitter`. Destination bitmaps are always 40 bytes per row (`dest offset = y*40 + byte`) and
all five planes in `D:0BEC` are written, whatever the shape's `planes` field says: shape plane p is at
`data + p*plane_bytes`. A mask is a 1-plane shape (0x10C5A); "no mask" is detected as `mask + 16 < 0x7D0`
(i.e. a NULL mask).

```c
void blit_wait_hw(void) {                              /* 0x10D44 */
    D_034C++;
    for (s16 ok = 0; ok < 10; ) { if (DMACONR & 0x4000) { D_0348++; ok = 0; } else ok++; }
}
void blit_begin(void) {                                /* 0x10D14 */
    blit_wait_hw(); BLTAMOD = 0; BLTDMOD = 0; BLTCON0 = 0x09F0; BLTCON1 = 0; BLTAFWM = BLTALWM = 0xFFFF;
}
void blit_clear_rect(u8 *plane, s16 x, s16 y, s16 wbytes, s16 h) {   /* 0x10D72 (0x10DBE: BLTCON0 0x01FF) */
    u8 *a = plane + y*0x28 + ((x >> 3) & 0xFE);        /* lsr.w: x unsigned */
    blit_wait_hw(); BLTAFWM = BLTALWM = 0xFFFF;
    BLTDPT = a; BLTCON0 = 0x0100; BLTDMOD = 0x28 - wbytes; BLTSIZE = (h << 6) | (wbytes >> 1);
    blit_wait_hw();
}
void set_clip(s16 top, s16 bottom, s16 left, s16 right) {            /* 0x10FBC */
    D_0380 = top; D_0382 = bottom; D_0384 = left & 0xFFF0; D_0386 = right & 0xFFF0;
}
void set_clip_full(void) { set_clip(0, 0xC8, 0, 0x140); }             /* 0x10FA4 */
```

**Word-aligned prep 0x10FDA** (x is rounded down to a multiple of 16; shape header: +0 width bytes, +2 height,
+0xE plane bytes):

```c
bool blit_prep_word(Shape *s, Shape *m, s16 x, s16 y, BlitParams *P) {
    if ((s32)s <= 0x32) return false;
    P->src = s->data; P->msk = m->data;  /* m + 16, even when m is NULL */
    P->lflag = P->rflag = 0; P->fwm = P->lwm = 0xFFFF;
    s16 h = s->h;
    if (y < D_0380) { h += y - D_0380; if (h <= 0) return false;
                      u32 skip = (u16)(D_0380 - y) * s->wb; P->src += skip; P->msk += skip; y = D_0380; }
    s16 t = y + h - D_0382; if (t > 0) { h -= t; if (h <= 0) return false; }
    P->smod = 0; x &= 0xFFF0; s16 w = s->wb;
    if (x < D_0384) { s16 d = (x - D_0384) >> 3;       /* negative, even */
                      w += d; if (w <= 0) return false;
                      P->smod -= d; P->src -= d; P->msk -= d; x = D_0384; P->lflag = 0xFFFF; }
    t = (w << 3) + x - D_0386;
    if (t > 0) { t >>= 3; w -= t; if (w <= 0) return false; P->smod += t; P->rflag = 0xFFFF; }
    P->dmod = 0x28 - w; P->size = (h << 6) | (w >> 1);
    P->doff = ((x >> 3) & 0xFE) + y * 0x28; P->pbytes = s->pbytes;
    return true;
}
void blit_shape_word_asm(Shape *s, Shape *m, s16 x, s16 y) {         /* 0x10E88 */
    if (!blit_prep_word(s, m, x, y, &D_0362)) return;
    bool masked = (u32)P.msk >= 0x7D0;
    for (p = 0; p < 5; p++) {                          /* waits before each plane and after the last */
        BLTAFWM = BLTALWM = 0xFFFF; BLTAMOD = BLTBMOD = P.smod; BLTCMOD = BLTDMOD = P.dmod; BLTCON1 = 0;
        BLTCON0 = masked ? 0x0FCA : 0x05CC;           /* D = A·B + ¬A·C  |  D = B */
        BLTAPT = P.msk; BLTBPT = P.src + p*P.pbytes; BLTCPT = BLTDPT = D_0BEC[p] + P.doff; BLTSIZE = P.size;
    }
}
```

**Shifted prep 0x112E4** (one extra source word per row, modulo −2, shift = x & 15):

```c
bool blit_prep_shift(Shape *s, Shape *m, s16 x, s16 y, BlitParams *P) {
    if ((s32)s <= 0x32) return false;
    P->src = s->data; P->msk = m->data; P->lflag = P->rflag = 0; P->pbytes = s->pbytes;
    /* y clipping exactly as in blit_prep_word */
    P->fwm = 0xFFFF; P->lwm = 0x0000; P->bmod = -2; P->amod = -2; P->shift = x & 0xF;
    s16 w = s->wb + 2;
    if (x < D_0384) {
        s16 d4 = x - D_0384;                           /* negative */
        s16 d0 = (d4 + 0xF) >> 3; d0 = (d0 & 0xFF00) | (d0 & 0xFE);   /* and.b #$FE */
        if (d0 != 0) { w += d0; if (w <= 0) return false;
                       P->bmod -= d0; P->amod -= d0; P->src -= d0; P->msk -= d0; }
        P->lflag = 0xFFFF; P->fwm = fwm_table[(-d4) & 0xF];
        x = D_0384; if (P->shift) x -= 0x10;
    }
    x &= 0xFFF0;
    s16 t = (w << 3) + x - D_0386;
    if (t > 0) { t >>= 3; w -= t; if (w <= 0) return false;
                 P->bmod += t; P->amod += t; P->rflag = 0xFFFF; P->lwm = lwm_table[0x10 - P->shift]; }
    P->dmod = 0x28 - w; P->size = (h << 6) | (w >> 1);
    P->doff = ((x >> 3) & 0xFE) + y * 0x28;
    if ((u32)m + 0x10 < 0x7D0) P->msk = 0;
    return true;
}
void blit_shape_asm(Shape *s, Shape *m, s16 x, s16 y) {              /* 0x110C4 */
    if (!blit_prep_shift(s, m, x, y, &P)) return;
    u16 sh = P.shift << 12;
    for (p = 0; p < 5; p++) {
        BLTAFWM = P.fwm; BLTALWM = P.lwm; BLTCON1 = sh;               /* BSH */
        if ((u32)m + 0x10 >= 0x7D0) BLTCON0 = sh | 0x0FCA;            /* ASH, A B C D, D = A·B + ¬A·C */
        else { BLTCON0 = sh | 0x07CA; BLTADAT = 0xFFFF; }             /* B C D, A = constant 1s */
        BLTAMOD = P.amod; BLTBMOD = P.bmod; BLTCMOD = BLTDMOD = P.dmod;
        BLTAPT = P.msk; BLTBPT = P.src + p*P.pbytes; BLTCPT = BLTDPT = D_0BEC[p] + P.doff; BLTSIZE = P.size;
    }
}
/* 0x111E6 blit_shape_xor: same prep; BLTCON0 = sh | 0x076A, BLTADAT = 0xFFFF → D = C ^ (A·B):
   the shape planes are XORed into the destination inside the FWM/LWM edge masks. */
/* 0x11432 blit_shape_xor_word: saves D_0386, rounds it up to a multiple of 16, blit_prep_word(s, NULL, x, y);
   if (x + s->wb*8 > saved_right) P.lwm = lwm_table[saved_right & 0xF ? saved_right & 0xF : 16];
   per plane: BLTAFWM = 0xFFFF, BLTALWM = P.lwm, BLTAMOD = P.smod, BLTCMOD = BLTDMOD = P.dmod, BLTCON1 = 0,
   BLTCON0 = 0x0B5A (A C D, D = A ^ C), A = shape plane, C = D = dest; finally restores D_0386. */
```

What the port must reproduce is the effect of the blitter on the planes, including the edge cases the masks and
the −2 modulo produce at clipped edges. The simplest faithful way is a small blitter emulator over `mem[]`
(A/B/C/D channels, ASH/BSH barrel shift carrying the previous word of the same channel, FWM on the first and LWM on
the last word of each row applied to A, modulos, minterm), run synchronously when `BLTSIZE` is written. With that,
0x10D14–0x11552 port one-to-one. `blit_wait_hw` then returns at once.

**Masks and arena** (verified):
```c
Arena *arena_new(s32 size) { u32 *p = alloc_chip(size); if (p) { p[0] = size; p[1] = 8; } return p; }  /* 0x10BA8 */
void  *arena_alloc(Arena *a, s32 n) {                  /* 0x10BDC */
    if (!a) return 0; if ((s32)(a->size - a->used) < n) return 0;
    void *r = (u8*)a + a->used; a->used += n; D_0360 = 0; return r;
}
Shape *make_mask(Arena *a, Shape *s) {                 /* 0x10C5A */
    if (!s) return 0;
    Shape *m = arena_alloc(a, s->wb * s->h + 0x10); if (!m) return 0;
    memcpy(m, s, 16); m->planes = 1;
    u16 pb = s->pbytes;
    for (u16 i = 0; i < pb/2; i++) { u16 v = 0; for (u16 p = 0; p < s->planes; p++) v |= s->w16[p*pb/2 + i]; m->w16[i] = v; }
    return m;
}
void draw_shape_on_view(Shape *s, View *v) {           /* 0x14984 */
    set_clip_full(); OwnBlitter();
    blit_set_dest(v->ViewPort->RasInfo->BitMap->Planes);
    blit_shape_word(s, NULL, s->x, s->y); blit_wait(); DisownBlitter();
}
```
`make_mask` treats colour 0 as transparent. `blit_shape_word` needs x on a 16-pixel boundary to be exact: the
`.ST`/dash/logo shapes store such positions.

### 4.7 Text (verified)

```c
void text_init(void) {                                 /* 0x13250 */
    struct TextAttr *ta = alloc_public(8); ta->ta_Name = "topaz.font"; ta->ta_YSize = 8;
    D_2876 = alloc_public(0x64); InitRastPort(D_2876); D_2876->BitMap = &bmA;
    D_2872 = OpenFont(ta); SetFont(D_2876, D_2872); free_mem(ta);
    text_set_pen(1); SetDrMd(D_2876, JAM1 /*0*/);
}
void text_shutdown(void) { CloseFont(D_2872); free_mem(D_2876); D_2876 = 0; }                  /* 0x132E6 */
void text_print(char *s) { Text(D_2876, s, strlen(s)); }                                        /* 0x13306 */
void text_move(s16 x, s16 y) { Move(D_2876, x, y); }                                            /* 0x13330 */
void text_set_pen(s16 c) { SetAPen(D_2876, c); }                                                /* 0x13354 */
void draw_box_outline(s16 x0, s16 y0, s16 x1, s16 y1) {                                       /* 0x1336E */
    u8 fg = D_2876->FgPen; SetAPen(D_2876, 1); SetDrMd(D_2876, 0);
    Move(x0,y0); Draw(x1,y0); Draw(x1,y1); Draw(x0,y1); Draw(x0,y0); SetAPen(D_2876, fg);
}
void erase_rect(s16 x0, s16 y0, s16 x1, s16 y1) {                                             /* 0x1343A */
    save FgPen, DrawMode, cp_x, cp_y; SetAPen(0); SetDrMd(0); RectFill(x0, y0, x1, y1);
    SetAPen(fg); SetDrMd(mode); Move(cp_x, cp_y);
}
void text_cursor(void) {                                                                       /* 0x134F2 */
    save FgPen, DrawMode, cp_x, cp_y; SetAPen(0x1F); SetDrMd(2 /*COMPLEMENT*/);
    RectFill(cp_x, cp_y - 8, cp_x + 8, cp_y + 1); restore; Move(cp_x, cp_y);
}
```
Callers point `D_2876->BitMap` at the bitmap they draw into (game_flow). Port: topaz 8 is the Kickstart ROM font
(8×8, baseline 6); JAM1 draws only set pixels in APen; `Move` y is the baseline; `Text` advances cp_x by 8 per
character. The port needs a copy of the topaz 8 glyphs (a `font8x8`-style table) and these three draw modes.

### 4.8 Ticks VBLInt 0x1180E / 0x118B2 (verified)

```c
void vbl_install(void) {                               /* 0x1180E */
    *(u32*)0x118AE = A4;                               /* server reloads A4 from here */
    vbl_irq.ln_Type = NT_INTERRUPT /*2*/; vbl_irq.ln_Pri = (s8)0xB0 /*-80*/; vbl_irq.ln_Name = "Ticks VBLInt";
    vbl_irq.is_Data = &tick_count /*D:03D8*/; vbl_irq.is_Code = vbl_server;
    AddIntServer(INTB_VERTB /*5*/, &vbl_irq);
}
long vbl_server(u32 *data /*A1*/) {                    /* 0x118B2, runs in the level-3 interrupt */
    (*data)++;                                         /* tick_count */
    if (!read_fire_raw()) {
        if (D_24BA == 0 && D_0B34 == 0) D_0B30 = 0;
    } else if (D_24B0 == 1) {                          /* O mode */
        D_0B30 = 0xFFFF;
        s16 dir = read_joy_raw(), old = D_03EC; D_03EC = dir;
        if ((old != dir || D_24B2 != D_24B4 || D_24B6 != D_24B8) && dir != 0) {
            s16 i = (dir << 4) + D_03EE*4 + D_03F0;
            gear_select(D_1942[i]);                    /* 0x1EE76 via overlay stub 0x17EBC (drive_sim) */
            fn_20826();                                /* via overlay stub 0x17ED4 (drive_sim) */
        }
    }
    return 0;                                          /* Z set: continue the server chain */
}
```
`D:24B0` is never cleared outside the O-key toggle: if the player leaves O on and then presses fire and moves the
stick outside the drive (overlay 2 unloaded), the interrupt calls an overlay stub, which would run the overlay
manager (dos.library) inside an interrupt. Not reproduced by the port (§7).

### 4.9 Joystick and fire (verified)

```c
s16 read_fire(void) { return (~CIAA_PRA >> 7) & 1; }  /* 0x15402, 0x11872: /FIR1, 1 = pressed */
static const u8 joy_dir_table[16] = { 0,5,4,3, 1,0,0,2, 8,0,0,0, 7,6,0,0 };   /* 0x1543E and D:03DC */
s16 read_joy(void) {                                   /* 0x15416, 0x11886 */
    u16 j = JOY1DAT;
    return joy_dir_table[(j & 3) | ((j >> 6) & 0xC)];  /* bits 1,0 = right/down xor; bits 9,8 = left/up xor */
}
s16 joy_fire(void) { return D_2858 = read_fire(); }   /* 0x153E4 */
s16 joy_dir(void)  { return D_2512 = read_joy();  }   /* 0x153EC */
void fire_port_init(void) { CIAA_DDRA &= 0x7F; }      /* 0x153CC */
```
Direction codes: 0 centre, 1 up, 2 up-right, 3 right, 4 down-right, 5 down, 6 down-left, 7 left, 8 up-left (the
same clockwise code as DOS `input_poll_drive`). JOY1DAT decoding: right = bit 1, left = bit 9, down = bit 1 ^
bit 0, up = bit 9 ^ bit 8; impossible combinations give 0.

### 4.10 Keyboard (verified)

```c
void input_init(s16 passmask) {                        /* 0x154E4 */
    *(u32*)0x15694 = A4; D_2486 = passmask; D_240E = 0xA; D_240C = 0;
    D_2410 = CreatePort(0, 0); D_2418 = CreateStdIO(D_2410);
    input_irq.is_Data = &D_2432; input_irq.is_Code = input_handler; input_irq.ln_Pri = 0x7F;
    OpenDevice("input.device", 0, D_2418, 0);
    D_2418->io_Command = IND_ADDHANDLER /*9*/; D_2418->io_Data = &input_irq; DoIO(D_2418);
    D_2414 = CreatePort(0, 0); D_2482 = CreateExtIO(D_2414, 0x20);
    OpenDevice("console.device", -1, D_2482, 0); D_28EE = D_2482->io_Device;
}
InputEvent *input_handler(InputEvent *ev /*A0*/) {     /* 0x15698; only the FIRST event of the chain */
    if (ev->ie_Class == IECLASS_RAWKEY /*1*/) {
        if (ev->ie_Code & 0x80) goto swallow;          /* key up */
        if (ev->ie_Qualifier & D_2486) return ev;      /* pass to the system */
        if (D_240C < D_240E) { D_23EE[D_240C] = ev->ie_Code; D_23F8[D_240C] = ev->ie_Qualifier; D_240C++; }
    swallow: *(u16*)&ev->ie_Class = 0;                 /* IECLASS_NULL: consumed (also when the queue is full) */
    }
    return ev;
}
s16  key_available(void) { return D_240C ? -1 : 0; }  /* 0x156EC */
u32  get_key(void) {                                   /* 0x156F8 */
    while (!key_available()) WaitTOF();
    Forbid();
    u32 k = ((u32)D_23F8[0] << 16) | D_23EE[0];
    D_240C--;
    for (s16 i = 0; i <= D_240C; i++) { D_23EE[i] = D_23EE[i+1]; D_23F8[i] = D_23F8[i+1]; }
    Permit(); return k;
}
s16 key_to_ascii(u32 k) {                              /* 0x1563A */
    struct InputEvent ie; char c; ie.ie_NextEvent = 0; ie.ie_Class = IECLASS_RAWKEY; ie.ie_SubClass = 0;
    ie.ie_Code = (u16)k; ie.ie_Qualifier = k >> 16;   /* ie_EventAddress left uninitialised */
    return RawKeyConvert(&ie, &c, 1, NULL) == 1 ? (u8)c : 0;
}
s16 get_char(void) { return key_to_ascii(get_key()); }   /* 0x15628 */

void poll_input(void) {                                /* 0x10462 */
    if (!key_available()) return;
    u8 c = toupper(key_to_ascii(get_key()));
    if (c == 'P' && D_2814) {                          /* pause, drive only */
        s16 old = D_24AE; D_24AE = 1;
        while (!key_available()) Delay(1);
        get_key();                                     /* the resume key is thrown away */
        D_24AE = old;
    } else if (c == 'M') { D_04CC = !D_04CC; if (!D_04CC) song_stop(); }
    else if (c == 'S') { D_0344 = !D_0344; if (!D_0344) snd_stop_all(); }
    else if (c == 'D' && D_2814) { D_0B34 = !D_0B34; D_0B31 = D_0B30 = (u8)(D_0B34 * 0xFF); }
    else if (c == 'O' && D_2814) { D_24B0 = !D_24B0; }
    else if (c == 0x12) D_0346 = 1;                    /* Ctrl-R */
}
s16 quit_requested(void) {                             /* 0x1544E */
    D_24AC = 0;                                        /* keep Chk_Abort from exiting */
    if (D_1BDA == 0 && Chk_Abort() != 0) D_1BDA = -1;
    return D_1BDA;
}
```
With `p` (the shipped Startup-Sequence) every key-down is queued and swallowed, so Ctrl-C never reaches the shell
and `quit_requested` stays 0; Ctrl-R works. Without `p`, keys with CapsLock, Ctrl, left Alt or left Amiga held go
to the system instead (Ctrl-C then breaks the game cleanly through `quit_requested`, but Ctrl-R never arrives, and
with CapsLock on the game gets no keys at all).

### 4.11 rand16 0x1530E (verified)

```c
s16 rand16(void) {
    if (!D_1BD8) { D_1BD6 = VHPOSR; D_1BD8 = -1; }
    D_1BD6 = (u16)((s32)(s16)D_1BD6 * 0x1AFB + 0x1FCCD);
    D_1BD6 ^= VHPOSR;                                  /* beam position: not reproducible */
    return D_1BD6;                                     /* callers use the 16-bit value */
}
```
Port: VHPOSR has no deterministic equivalent; use a counter derived from the emulated beam (ticks since VBL) or a
host random source. Callers: main (random attract car), 0x1444C, 0x1AED0, 0x1B8E6 and overlay 2 (0x1DB36,
0x1E7D2); none of them needs a reproducible sequence.

### 4.12 Files 0x149FE and the `Pckd` decoder (verified; decoder internals as FORMATS.md)

```c
void *load_file_flags(char *name, u32 flags) {        /* 0x149FE */
    BPTR lock = Lock(name, ACCESS_READ /*-2*/); if (!lock) goto fail;
    struct FileInfoBlock *fib = alloc_public(0x104); if (!fib) goto fail;
    if (!Examine(lock, fib)) goto fail; UnLock(lock); lock = 0;
    s32 size = fib->fib_Size /*+0x7C*/; free_mem(fib); fib = 0;
    if (size <= 0) goto fail;
    BPTR fh = Open(name, MODE_OLDFILE /*1005*/); if (!fh) goto fail;
    u8 hdr[16]; if (Read(fh, hdr, 16) != 16) goto fail;
    if (*(u32*)hdr == 'Pckd') {
        s32 ulen = pckd_unpacked_len(hdr);
        u8 *out = mem_alloc(ulen, flags); if (!out) goto fail;
        u8 *tmp = alloc_public(size); if (!tmp) goto fail;
        memcpy(tmp, hdr, 16); s32 got = Read(fh, tmp + 16, size - 16); Close(fh); fh = 0;
        if (size - 16 != got) goto fail;
        pckd_unpack(tmp, out); free_mem(tmp);
        D_24BC = out; D_2810 = ulen;                   /* no size or CRC check */
    } else {
        u8 *buf = mem_alloc(size, flags); if (!buf) goto fail;
        memcpy(buf, hdr, 16); s32 got = Read(fh, buf + 16, size - 16); Close(fh);
        if (size - 16 != got) goto fail;
        D_24BC = buf; D_2810 = size;
    }
    return D_24BC;
fail: free everything allocated, Close/UnLock; D_24BC = 0; D_2810 = 0; return 0;
}
void pckd_unpack(u8 *p, u8 *out) {                     /* 0x14C9C */
    D_1FAC = 0; D_1FA8 = 0 /*out_count*/; D_1FBE = *(u32*)(p+4) /*packed_left*/;
    D_1FB0 = *(u32*)(p+8) /*unpacked_len*/; D_1FB4 = p + 16; D_1FB8 = out; D_1FBC = 0 /*rle state*/;
    switch (*(u16*)(p+0xC)) {                          /* table 0x14D3C, index method-2 */
    case 2: while ((c = pack_getc()) != -1) pack_putc(c); break;
    case 3: while ((c = pack_getc()) != -1) rle90_out(c); break;
    case 4: huff_read_tree(); while ((c = huff_decode()) != -1) rle90_out(c); break;
    case 8: lzw_decompress(); break;
    default: break;                                    /* output stays zero (MEMF_CLEAR) */
    }
}
s16 pack_getc(void) { if (!D_1FBE) return -1; D_1FBE--; return *D_1FB4++; }     /* 0x14ED6 */
void pack_putc(u8 c) {                                 /* 0x14EF2 */
    D_1FA8++;
    if (g_original_bugs ? (s32)D_1FA8 <  (s32)D_1FB0   /* bug 3: bge skips, the LAST byte is never written */
                        : (s32)D_1FA8 <= (s32)D_1FB0)  /* fixed: all unpacked_len bytes, as DOS 0x9DD3 */
        *D_1FB8++ = c;
}
void rle90_out(u8 c) {                                 /* 0x14E6C */
    if (D_1FBC == 0) { if (c == 0x90) D_1FBC = 1; else { D_23EC = c; pack_putc(c); } }
    else { if (c == 0) pack_putc(0x90); else while (--c) pack_putc((u8)D_23EC); D_1FBC = 0; }
}
```
**Last-byte bug (README bug 3):** DOS `pack_putc` writes while `++count <= len`; the Amiga writes while
`++count < len` (0x14EFA `cmp.l; bge`), so the last unpacked byte of every `Pckd` file stays 0 (`MEMF_CLEAR`).
Checked on the disk: the last unpacked byte is nonzero in `Cars/VetteDash.Shp` (0x1F), `Pics/Endgame.Shp` (0xFF)
and `Pics/Gas.Shp` (0xFF); in the original it is 0, which clears the last 8 pixels of the last plane of the last
shape in those archives. The buffer holds `unpacked_len` bytes, so writing the last one stays in bounds. Fixed by
default: write it (the compare becomes `<=`, i.e. `bgt`); with `g_original_bugs` the port applies the same
truncation (unpack normally, then zero byte `len − 1`).

### 4.13 Memory 0x15930 / 0x159FA (verified)

```c
/* block: +0 alloc size, +4 next, +8 prev (circular), +0xC "MemB", user data at +0x10, "MemE" in the last long */
void *mem_alloc(u32 size, u32 flags) {
    size = (size + 0x17) & ~3;
    u8 *b = AllocMem(size, flags | MEMF_CLEAR /*0x10000*/); if (!b) return 0;
    D_1BE0++; *(u32*)b = size;
    if (!D_1BDC) { D_1BDC = b; b->next = b->prev = b; }
    else { b->next = D_1BDC; b->prev = D_1BDC->prev; D_1BDC->prev->next = b; D_1BDC->prev = b; }
    *(u32*)(b + 0xC) = 'MemB'; *(u32*)(b + (size & ~3) - 4) = 'MemE';
    return b + 0x10;
}
s16 free_mem(void *p) {
    if (!p) return 0;
    if (p == (void*)-1) { while (D_1BDC && free_mem(D_1BDC + 0x10) == 0) ; return 0; }
    u8 *b = (u8*)p - 0x10;
    if ((u32)b & 3 || b->magic != 'MemB' || b->next->magic != 'MemB' || b->prev->magic != 'MemB') return -1;
    /* the 'MemE' comparison is made but its result is not used; the `bcs` after `tst.l` never branches */
    if (b == D_1BDC) D_1BDC = b->next;  if (b == b->next) D_1BDC = 0;
    b->magic = 0; end guard = 0; unlink; FreeMem(b, b->size); D_1BE0--; return 0;
}
```
Port: host `calloc` in the 68000 memory image with the same 16-byte header is only needed if some code reads
`ptr − 0x10` (the SMUS player does: platform_audio). Chip vs public memory makes no difference to the port.

### 4.14 Overlays (verified)

The root hunk starts with `bra _start; dc.l 0x0000ABCD` and at 0x10008 the overlay header: +0 file handle, +4
(0x1000C) pointer to the overlay table, +8 (0x10010) seglist BPTR. Each of the 23 stubs (8 bytes, 0x17E94..0x17F4B)
is `bsr.w 0x17F4C (jmp ovl_load); dc.b node; dc.b ?; dc.w offset`.

```c
/* 0x168A4 ovl_load (entered by the stub's bsr): */
    a1 = return address (points at the stub's data); return address −= 4 (re-execute the stub);
    node = *(u8*)a1; entry = ov_table + 4 + (node − 1)*8;
    ovl_loadseg(entry);                                /* 0x1691C */
    for each (hunk, count) pair of the node: patch count stubs from 0x17C10 + entry.stub_off as
        `jmp abs.l hunk_base + 4 + offset` (0x4EF9);
/* 0x1691C ovl_loadseg */
    dos = OpenLibrary("dos.library", 0); if (!dos) Alert(0x0700000C);   /* never closed */
    do r = Seek(fh, entry.file_offset, OFFSET_BEGINNING); while (r < 0);
    do seg = LoadSeg(0, seglist, fh); while (!seg);    /* overlay form of LoadSeg: d1 = 0, d2 = table, d3 = fh */
    append seg to the seglist chain;
/* 0x162E0 ovl_unload(stub) */
    if (*(u16*)stub != 0x4EF9) return;                 /* not loaded */
    find the table entry whose stub range contains stub (search from the end);
    for each hunk of the node: FreeMem it and unlink it from the seglist;
    rewrite the node's stubs as `bsr.w ovl_load` (0x6100 disp, node byte);
```
`main` calls `ovl_unload(stub of 0x1AED0)` after the car selection, before the drive, and `ovl_unload(stub of
0x1C900)` after each drive. **So the overlays are unloaded.** They can still be resident together: `show_view`
0x1C62E is in overlay 1 but is called by root and overlay 2, so the first `show_view` of a drive reloads overlay 1
from disk while overlay 2 is loaded, and `display_shutdown` reloads it at exit. The README ("not resident at the
same time") and title_select ("never unloads") are both wrong in part. For the port the overlays are irrelevant
(all code resident); only the disk reads at those points cost time on the real machine.

### 4.15 Fixed-point helpers (verified; semantics only)

```c
s32 fix_mul(s32 a, s32 b) { return (s32)(((s64)a * b) >> 16); }             /* 0x11F94, floor */
s32 fix_div(s16 a, s16 b) {                                                /* 0x11FD6 */
    if (b == 0) return (a < 0) ? -0x7FFFFFFF : 0x7FFFFFFF;
    u32 q = ((u32)abs(a) << 16) / (u16)abs(b);  /* computed as divs then divu of the remainder */
    return ((a < 0) != (b < 0)) ? -(s32)q : (s32)q;
}
u16 isqrt(s32 x) {                                                           /* 0x1200E */
    x = labs(x); if (x <= 1) return (u16)x;
    u32 r = x >> 1; if (r >= 0xB505) r = 0xB505;
    for (;;) { u32 q = (u16)divu(x, r); if (q >= r) return r; r = (r + q) >> 1; }   /* divu overflow keeps x */
}
u16 sin_deg_fix(u32 d16) {                                                   /* 0x12108, 0..180° in 16.16 */
    u8 i = d16 >> 16; if ((s8)i > 0x5A) i = (u8)(0xB4 - i); i &= 0x7F;
    u16 lo = sin_tab[i], hi = sin_tab[i+1];
    return lo + (u16)(((u32)(u16)d16 * (u16)(hi - lo)) >> 16);
}
u16 cos_deg(s16 d) { return sin_tab[(d >= 0 ? 0x5A - d : d + 0x5A) & 0x7F]; }  /* 0x12146 */
s32 tan_deg_fix(s16 d) { s32 t = tan_tab[(abs(d) & 0x7E) >> 1]; return d < 0 ? -t : t; }   /* 0x12224 */
```
`sin_tab` (0x1216C) = round(sin(i°)·65535) for i = 0..90 (0x0000, 0x0478, …, 0xFFFF); `tan_tab` (0x1224C) =
tan(2k°)·65536 as longs. Keep the tables bit-exact in the port (dump them from `td.bin`).

### 4.16 Copy protection (brief, verified)

The module 0x11954–0x11E00 is hand-written assembly with its own data block (A4 points at it; the index's
`D:800E..D:802E` are fields of that block, not globals). `protection_check` 0x10588:

```c
crc0 = prot_measure_setup("TEST DRIVE:");  /* AllocEntry, Lock+Info (−114) the volume to get its drive unit,
                                              OpenDevice trackdisk (that unit),
                                              OpenResource disk.resource; returns CRC16(0x11954.., poly 0x8005) */
d = prot_read_track(0, 1); e = prot_read_track(0, 0); prot_cleanup();
if (d - e > 0x1E0 || prot_crc(0x11954, prot_code_len(), 0, 0x8005) != crc0 || d < 0x38E || d > 0x44C) {
    *(u16*)0x151F2 = d;                    /* first word of the unused load_raw */
    *(u16*)0x17D48 = e;                    /* first word of the load_file call-table slot (jmp abs.l) */
    D_1E94 = 1;                            /* main quits — but main first loads Cars.Txt through that slot */
}
```
`prot_read_track(cyl, head)`: trackdisk `ETD_CLEAR`, `ETD_MOTOR` on, `ETD_SEEK` to the neighbour cylinder then
`ETD_READ` one sector of the wanted track (to position the head); then it takes the drive from disk.resource
(`GetUnit`), selects it through CIA-B PRB ($BFD100 = 0x7F, then select/side bits), sets ADKCON 0x9500
(MFMPREC|WORDSYNC|FAST) and clears MSBSYNC, DMACON 0x8210 (DSKEN), DSKSYNC 0x4489, DSKPT = buffer, and writes
DSKLEN = 0x8000 | 0x1B48 twice (a raw read of 0x3690 bytes, more than one track), waiting on its own DSKBLK
interrupt (0x11D1E: DSKLEN = 0x4000, INTREQ, `Signal`). 0x11D3A MFM-decodes the first sector header, checks the
track number (`cyl*2 + head`, retries on mismatch), and jumps `sectors-until-gap × 0x440 − 8` bytes ahead to the
gap. **On this cracked disk the measuring code after that point is replaced**: it loads the constants 0x3E8 or
0x3E0 (`move.w #$3E8,d0` … `move.l #$3E0,d0; rts`, with a branch into the middle of that `move.l` at 0x11D8A that
executes `bset d1,-(a0); rts` and returns 0x3E8). Both values lie in 0x38E..0x44C and differ by at most 8, so the
check always passes. (The original presumably counted the words of the gap of a long track.) *likely* for the
"what the original did" part; the constants and the pass are verified.

**Port:** drop 0x10588 and the whole module, as the DOS port does.

---------------------------------------------------------------------------------------------------------------

## 5. Hardware / OS dependencies and the SDL3 replacement

| Access | Where | Effect on the real machine | Port |
|---|---|---|---|
| Views, ViewPorts, RasInfo, `MakeVPort`/`MrgCop`/`LoadView` | 0x115BC, show_view, title_select, drive_scene | graphics.library builds the copper list: display window, bitplane pointers from RasInfo (Rx/RyOffset), DxOffset/DyOffset/DHeight position, Modes (HIRES in the showroom), colours from the ColorMap | Keep the View/ViewPort/RasInfo/BitMap/ColorMap structs in `mem[]` at their `D:` addresses. At each emulated VBL, compose the frame from the **front View** (last `LoadView`): for each ViewPort in the chain draw its bitmap rows `RyOffset..` at screen row `DyOffset`, `DHeight` lines, horizontal `DxOffset`/`RxOffset`, lowres or hires, with the ViewPort's 32 colours, then apply the user copper lists. Present 320×200 (hires ViewPorts scaled ×½ or the frame rendered 640 wide) |
| `LoadRGB4` / ColorMap | many | colours of a ViewPort, visible at the next frame | write the ViewPort's ColorMap (12-bit 0RGB, expand ×17) |
| User copper lists (`CWait`/`CMove`/`CBump`, `vp->UCopIns`) | game_flow 0x13F32 (logo palettes per row), drive_scene 0x1EF14/0x1FB4A (split palette at `D:281E`, sprite pointers/positions) | per-scanline register changes | interpret the list during composition: at line `v`, apply `COLORxx` (0xDFF180+2i), `SPRxPT` (0xDFF120+4i), `SPRxPOS/CTL` (0xDFF140+8i / 0xDFF142+8i) |
| Hardware sprites | main: DMACON 0x0020 + SPR0/1DATA=0 at start; drive_scene enables DMA 0x8020 at 0x1F98E and off at 0x1F9A2 | pointer hidden; dashboard needle boxes as sprites during the drive | no mouse pointer; implement the 8 sprites (16 px, 3 colours from COLOR16-31) only as drive_scene needs them |
| Blitter registers `$DFF040–$DFF074`, DMACONR bit 14 | 0x10D14–0x11552 | shape drawing into planes | blitter emulator run synchronously on the BLTSIZE write (§4.6); busy bit always 0 |
| `BltBitMap`, `BltClear` | 0x1587C, 0x1574E | plane copy / clear | memcpy / memset of the planes |
| `DMACON = 0x8400`/`0x0400` written to **$BFF096**, read of **$BFF002** | 0x1042E, 0x1044C | nothing: with A12 and A13 both high neither CIA is selected; the value read into D:281C is bus noise. Meant DMACONR/DMACON BLTPRI ("blitter nasty") | ignore |
| `DMACON = 0x0400` (real address) | 0x10D3C | BLTPRI off; no callers | ignore |
| CIA-B `$BFD200 = 0xC0`, `$BFD000 = 0` | main | serial DTR/RTS as outputs, driven low | ignore |
| CIA-A PRA bit 7 (`$BFE001`), DDRA bit 7 (`$BFE201`) | 0x11872, 0x15402, 0x153CC | joystick-port fire button (active low) | SDL gamepad A button / keyboard key → 1 = pressed |
| `JOY1DAT` (`$DFF00C`) | 0x11886, 0x15416 | joystick port 2 directions | SDL gamepad d-pad/stick or arrow keys → the 0..8 code of §4.9 |
| `VHPOSR` (`$DFF006`) | 0x1530E | beam position as entropy | any varying value (§4.11) |
| VBL interrupt server (`AddIntServer(5)`) | 0x1180E | 60 Hz (NTSC) call of 0x118B2 after the sfx/song servers | call `vbl_server` once per 1/60 s host tick (host.c tick), before the game code resumes |
| input.device handler, console.device `RawKeyConvert` | 0x154E4, 0x15698, 0x1563A | raw key-down queue; conversion with the default (USA) keymap | SDL key-down events → Amiga raw key code (+ qualifier bits from modifiers) into the 10-entry queue; convert with a table equivalent to the USA keymap (letters, digits, punctuation, Return 0x0D, Backspace 0x08, Ctrl+letter = letter & 0x1F). Behave as with `p`: swallow everything |
| dos `Delay`, graphics `WaitTOF` | everywhere | 1/50 s sleep (timer-based on both standards); wait for the next vertical blank | `Delay(n)`: sleep n/50 s of host time, running the 60 Hz ticks that fall into it; `WaitTOF`: advance the emulated clock to the next tick and present |
| dos `Lock/Examine/Open/Read/Close`, `LoadSeg` | 0x149FE, 0x168A4 | disk files, overlays | host file I/O relative to the extracted disk; overlays not emulated |
| exec `AllocMem/FreeMem`, tasks, signals | runtime | memory, TDScroller task | allocations in `mem[]`; tasks see title_select |
| intuition `CloseWindow`/`CloseWorkBench`, `DrawImage` | 0x1032C, game_flow 0x14388 | free memory, draw an Image | nothing / game_flow |
| trackdisk.device, disk.resource, DSKLEN/DSKSYNC/ADKCON/INTENA/INTREQ, CIA-B PRB | protection | raw track read | dropped |
| `Alert` | 0x1642A, 0x1691C | guru on out-of-memory / no dos | fatal error message |

---------------------------------------------------------------------------------------------------------------

## 6. Timing

* **Clock:** the only periodic source is the vertical blank: 60 Hz on NTSC, 50 Hz on PAL. The port runs the NTSC
  rate, **60 Hz** (port/amiga/README.md, *Decisions* 1: the drive's frame and "second" constants and the Paula
  constant were designed for NTSC). `tick_count D:03D8` increments at the VBL rate. dos `Delay` is in 1/50 s on
  both systems (timer.device, not the VBL), so the port keeps `Delay(n)` = n/50 s while every `D:03D8`/`WaitTOF`
  count is 1/60 s.
* **Order within one VBL:** exec calls the servers by priority: the Song server (pri 0x20), the Sfx server
  (pri 0x1E), any system servers of higher priority than −80, then `Ticks VBLInt` (pri −80). The main program
  resumes afterwards. A `LoadView` takes effect at the next frame (the copper list is reloaded by the hardware at
  the vertical blank).
* **Per-frame vs per-tick:** nothing in the platform layer runs per frame on its own; the game's loops call
  `WaitTOF`/`Delay`/`get_key` or poll `D:03D8`. `get_key` polls once per VBL (`WaitTOF`), the P pause once per
  `Delay(1)`.
* **CPU-bound operations** (no sync; the time depends on the 68000 clock, 7.16 MHz NTSC / 7.09 MHz PAL, and
  chip-RAM contention): `view_dissolve` — about 150 cycles per plane-long in reveal mode, 80 in to-black mode: ≈
  0.22 s per pass ×8 ≈ **1.8 s** for a reveal and ≈ 0.9 s to black, before DMA contention (*guess* from instruction
  timings, 1 % apart between the two clocks; the title_select estimate of ~1 s is probably low). ILBM decoding,
  `Pckd` unpacking and the blits also take real time but are hidden behind the back buffer or a loading screen.
* **Overlay loads** (disk reads of 6.7 KB / 42.5 KB) occur at the first call into an unloaded overlay: at the
  start of the title sequence, at the start of each drive (overlay 2, then overlay 1 again through `show_view`), at
  exit.
* The `O`-mode gear selection runs inside the VBL (60 Hz), independent of the drive frame rate.

---------------------------------------------------------------------------------------------------------------

## 7. Differences from DOS

* **Display model.** DOS draws into EGA mode 0Dh video memory plus RAM planar buffers with a descriptor pool
  (0x5128/0x5150) and blits sprites by CPU (OR/AND/XOR/REPLACE families, x in 4-pixel steps for the `own`
  variants). The Amiga has two complete 5-plane 320×200 Views that are drawn off-screen and flipped with
  `LoadView`, 32 colours per ViewPort instead of the fixed 16-colour EGA palette, and graphics.library ViewPort
  offsets for scrolling (title_select) instead of `gfx_scroll_window`.
* **Pictures.** DOS screens are sprite archives (`.PES`) composed by code; the Amiga loads whole IFF ILBM
  pictures (`ilbm_to_view`), including a custom `CMP2` chunk that gives a second 32-colour palette from a given
  line (the gas-station screens, via a user copper list).
* **Shape drawing.** Cookie-cut with a precomputed OR-of-planes mask (colour 0 transparent) replaces DOS's OR
  blits; the no-mask paths copy the whole rectangle (colour 0 opaque). Two positioning modes: word-aligned
  (`x & ~15`) and pixel-exact (shift); DOS has byte/4-pixel-aligned `own` positions and pixel `raw` positions.
  XOR blits exist in both. Clipping is in 16-pixel columns (`D:0384/0386 & 0xFFF0`) instead of byte columns.
  Missing shapes are skipped (pointer ≤ 0x32) instead of DOS `res_find` being fatal.
* **Dissolve.** DOS `gfx_dissolve` 0x768B: 12 interlaced row passes, one pixel per byte, screen only, reveal only.
  Amiga 0x109D0: 8 passes, one bit per byte from the table 01,08,40,02,10,80,04,20 indexed `(k + r) & 7` with k =
  7..0, rows in the order 7r mod 200, into any View, and also used to fade to black (src = NULL).
* **Text.** ROM topaz 8 through graphics `Text` (JAM1, pen colours per call) instead of the built-in 8×8 font drawn
  opaque with fg/bg (DS:690E/6910). Cursor: COMPLEMENT-mode rectangle 9×10 instead of a glyph sprite.
* **Timer.** 60 Hz (NTSC) VBL `tick_count` (u32) instead of the 100.04 Hz PIT `tick_count` DS:642A (u16). No
  deadline helpers (DOS 0x7864–0x7894); the game waits with `Delay`, `WaitTOF` or explicit tick loops.
* **Keyboard.** A 10-key queue of raw key-downs converted with the keymap, instead of the BIOS buffer (where DOS
  keeps only the *last* key of a burst). Keys: P pause (drive only on the Amiga; DOS also Ctrl-P), M music and S
  effects are separate toggles (DOS Ctrl-Q/Ctrl-S = one sound flag), D and O toggles in the drive as in DOS,
  **Ctrl-R** returns to the intro (no DOS equivalent), **no ESC**, no A/Z/digit/cursor-key driving (the drive is
  joystick only), no Ctrl-J/Ctrl-K joystick switching or calibration screen. The pause swallows the resume key in
  both versions.
* **O option.** DOS sets the gear node from a table when `o` is on (sim 0x3BC3, per sim tick); the Amiga does the
  lookup in the VBL interrupt from stick direction + fire (`D:1942[(dir<<4) + D:03EE*4 + D:03F0]`), 50 times a
  second, and the flag survives the drive (latent interrupt-time overlay call).
* **Joystick.** Digital JOY1DAT + CIA fire bit instead of the analogue game port with adaptive calibration
  (0xA12F). Same 0..8 clockwise direction code.
* **Random numbers.** LCG ×0x1AFB + 0x1FCCD XORed with the beam position (not reproducible) instead of MSC `rand`
  and the `rand8` table.
* **Files.** Whole-file loads into individually allocated blocks (no 30-slot archive cache, no LIFO eviction);
  `Pckd` = DOS `.PES` big-endian with the same four methods, but: no unpacked-size check, no fatal errors (0 is
  returned), unknown methods produce a zeroed buffer, and **the last unpacked byte is dropped** (DOS keeps it; the
  port keeps it too unless `--original-bugs`, README bug 3).
  Text files end in zeros because every allocation is `MEMF_CLEAR`.
* **Memory.** `AllocMem` blocks with MemB/MemE guards in one list, freed all at once at exit, instead of one grabbed
  DOS block split into a low-end cache and 8 high-end buffers.
* **Protection.** DOS reads deliberately bad sectors (CRC error) on track 39 or a hard-disk signature and makes
  `main` exit; the Amiga measures a long track on cylinder 0 with raw DMA plus a self-CRC and, on failure, corrupts
  the `load_file` call slot so the game crashes at the next load. This dump is cracked by replacing the
  measurement with constants.
* **Start-up.** `p` argument (close Workbench, capture all keys) instead of the DOS launcher password and `herc`
  switch. No video-adapter detection.
* **Overlays.** DOS is one executable; the Amiga loads/unloads two overlays (§4.14).
* **Unused code differs:** Amiga dead code includes the raw loader 0x151F2, heap checker 0x15B3E, debug
  `RawPutChar`/`RawDoFmt` output, `ltoa_dec`, vector helpers 0x11EB6..0x11F0A, `blit_nasty_off`; DOS dead code
  includes the Hercules path, `grab_into_sprite_*`, `mem_debug_dump`.

---------------------------------------------------------------------------------------------------------------

## 8. Open questions

1. **ViewPort placement.** How graphics.library 1.2/1.3 positions a ViewPort for negative `DyOffset` / large
   negative `DxOffset` and what shows outside it (COLOR00 of the View's first ViewPort, likely) — needed for the
   title/showroom animations (title_select). Needs an emulator check.
2. **Dissolve duration**: ≈ 1.8 s reveal / 0.9 s to black by instruction count; DMA contention (5-plane lowres,
   all RAM is chip RAM on an A500) will add to it. Measure in an emulator before fixing the port's pacing.
3. **Blitter edge cases at the left clip** of the shifted path (`fwm_table[(−d4)&15]` with `x = clip_left − 16`)
   were transcribed, not exercised; a blitter emulator reproduces whatever they do. Which callers ever clip on the
   left (drive_scene) is for that spec.
4. **`D:0B30`, `D:24BA`, `D:24B2..24B8`, `D:03EE/03F0`, `D:1942` and the two overlay-2 routines called by the
   VBL (0x1EE76, 0x20826)** belong to drive_sim; only their use by the interrupt is documented here. *Resolved
   by drive_sim:* D:0B30 = gearbox shown (per view buffer), D:24BA = gearbox hide delay, D:24B2..24B8 = knob
   target y / y / target x / x, 0x1EE76 = gate-shift gear select, 0x20826 = engine_update.
5. **`D:0360`** is cleared by `arena_alloc` and never read in the index; possibly a leftover.
6. **Input handler looks only at the first event** of each chain (no `ie_NextEvent` walk). If input.device
   batches a key with other events (e.g. a timer event first), that key reaches the system or is lost. Probably
   invisible in practice; the port can ignore it.
7. **`RawKeyConvert` with an uninitialised `ie_EventAddress`** could produce dead-key effects with non-US keymaps;
   the port assumes the USA keymap.
8. **Original protection measurement**: the code after the gap jump was replaced by the crack; what it counted
   (gap words until the next sync) is a guess.
9. **PAL vs NTSC**: *resolved*: nothing in the platform layer checks the display standard; the port runs 60 Hz
   NTSC (port/amiga/README.md, *Decisions* 1). `Delay` stays 1/50 s.
10. **Last-byte bug** of `pack_putc` (README bug 3, fixed by default): verified in code; whether any *visible*
    pixel changes with `--original-bugs` (last plane of the shape stored last in VetteDash.Shp, Endgame.Shp
    `note`, and probably `tony` in Gas.Shp — data order not checked) was not checked in the rendered game.
