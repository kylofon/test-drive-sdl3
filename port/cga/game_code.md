# TDCGA game code: differences from TDEGA and how the port handles them

Scope: `tdport/src/game/*.c`, the port of the game code (TDEGA image 0x0010–0x4941, TDCGA 0x0010–0x4857).
The sources were compared function by function using `game_diffs.txt` (all 176 stretches), `xmap.json` →
`imm_diff` (every entry below EGA 0x4941), `call_swaps.txt` and the disassembly of both executables.

Build switches: `EGA_CGA(ega, cga)` for values, `#if TD_CGA` for statements, `#if TD_HERC` for the Hercules
start. The EGA objects are unchanged: all ten game `.o` files built at `-O2` are byte-identical before and
after this change, in both code and data. All three variants (EGA, `TD_CGA=1`, `TD_HERC=1`) pass the
`-Wall -Wextra` syntax check with no warnings.

Addresses: "E" is the TDEGA image offset, "C" is the TDCGA image offset. DS offsets are DGROUP offsets.

## 1. Structural differences (`#if TD_CGA`)

| E | C | Function | Difference in TDCGA | Port |
|---|---|---|---|---|
| 0x0036 | 0x0036 | main | With `herc`, main calls herc_init (C 0x7587) and sets DS:0096 = 1. That happens before mem_init. | `#if TD_HERC`: `gfx_herc_init(); DSW(DS_herc_mode) = 1;` Other CGA builds leave the flag at 0, as when `tdcga` runs with no argument. |
| 0x003F | – | main | No TD.EXE launcher-password check. | Already dropped in the port. |
| 0x0059 | – | main | No `gfx_set_palette(DS:00CC)`. | `#if !TD_CGA` |
| – | 0x00C0 | main | Loads `xroada.cmp` with C 0x73EA into the DGROUP buffer DS:73AA and stores the result in g_xroadA (DS:CF8A). | Calls the new `load_packed_near(DSTR(0x63), 0x73AA, &len)`, declared in `flow.h`. |
| 0x022A | 0x0225 | main | When DS:0096 != 0, calls herc_shutdown (C 0x75D7) instead of gfx_shutdown. | `#if TD_CGA`: `if (DSW(DS_herc_mode)) gfx_herc_shutdown(); else gfx_shutdown();` |
| 0x0B03, 0x0B5A | 0x0AFE, 0x0B4D | show_car | Outgoing car: `blit_copy_clip_raw(page, 0, i+0x57)` / `(page, 0, i-0x57)` replaces `gfx_scroll_window` (call_swaps 0x0B1B, 0x0B6F). | `#if TD_CGA` |
| 0x0C99, 0x0CF7 | 0x0C87, 0x0CD2 | show_car | Incoming car: `blit_copy_clip_raw(page, 0, i)` in both directions (call_swaps 0x0CB8, 0x0D14). | `#if TD_CGA`. The unused `none` FarPtr is also compiled out. |
| 0x106C | 0x1036 | run_game | Loads one traffic archive only: `xroadb.cmp` (DS:027A, reserve 0x908) into g_xroadC (DS:CF8E). There is no xroada/xroadb/xroadc.pes load. | `#if TD_CGA` |
| 0x1DDB–0x1E19 | 0x1D7B–0x1DAF | run_stage | Draws the dash and the roof before `gfx_set_clip(screen, 0, 0x50, 0x13, 200)`. There is no `clear_clip(8)`. | `#if TD_CGA` |
| 0x1E2E | – | run_stage | No `clear_clip(8)` after select_road_buffer in the frame loop. | `#if !TD_CGA` |
| 0x1EDA | – | run_stage | Game over draws only `blit_or_own(govr)`. There is no `gvrm` mask (the sprite does not exist in TDCGA). | `#if !TD_CGA` |
| 0x38EB | 0x3836 | dealership_ending | Draws into the road buffer and presents it: `select_road_buffer; copy_clip_own(deal); draw_buffer_overlays; present_road_buffer; wait_fire; select_road_buffer; copy_own(note); present_road_buffer; ...` (call_swaps 0x38F0, 0x390F, 0x3920). | `#if TD_CGA` |
| 0x392F | – | crash_windscreen_sequence | No `clear_clip(8)`. | `#if !TD_CGA` |
| 0x3B02 | – | present_road_buffer | Does not set clip_y1 = 0x6F. | `#if !TD_CGA` |
| 0x3827 | 0x3785 | draw_dashboard_dynamic (digital tach) | Draws one bar sprite (DS:13E6), always clipped to `inst_wbytes + (rpm/800) - 9`. There is no tac1..tac3 selection. | `#if TD_CGA` |
| 0x36A1 | 0x35FF | wheel-marker save-under | `and dx, 0xFFFC` (align to 4 px, one CGA byte) instead of 0xFFF8. | `EGA_CGA` |
| 0x28C5.. | 0x2843.. | draw_road_main | Cut clip: `(cut_x+0x20) >> 2`, clamped to 0x50 bytes, `px = bytes << 2`. clip_x1 and xclip_bytes are 0x50. | `#if` / `EGA_CGA` |
| 0x298B | 0x28ED | draw_road_main dash | Sets one 2bpp pixel: `ES:[row + x>>2] \|= DS:1430[x&3]` in the road buffer. EGA sets three plane bytes. | `plot_dash` `#if TD_CGA`, shared with the mirror (0x2FB5). |
| 0x2A49 | 0x29AD | draw_road_main roadside scenery | Calls 0x4C0C, `blit_or_clip_hot`. TDCGA has no clipped XOR blitter, and the symbol map points `blit_xor_clip_hot` at the same routine. | `#if TD_CGA` → `blit_or_clip_hot` |
| – | 0x2C31, 0x3206 | main and mirror horizon cliff | `or dx,1; or ax,1` before pushing the clfo/clfa and mcfo/mcfa frames. | `#if TD_CGA` |
| 0x2DEE / 0x3306 | 0x2D58 / 0x3259 | fill_road_scanlines main/mirror | 2bpp word spans in ES = DS:[0896] (the road buffer sprite segment). Each row starts with `word [di] = 0`. Patterns per span: min_ol 0x5555; ol 0x5555, or grass after min_ol; l 0xAAAA; r 0 (filled, not skipped); or 0xAAAA; rest grass. Grass is 0x8888, or 0x2222 on odd rows. The mirror starts at byte 0x3C with DX = 0x1E words. | New `fill_road_scanlines_cga` |
| 0x2E8B / 0x339E | 0x2DF2 / 0x32EF | fill_span_to | Word-based. Uses mask tables DS:1410 (left, u16[8]) and DS:1420 (right, u16[8]) ANDed with the pattern word DS:1434, and span_bit DS:1436. Clears the next word after a full run and when a word is completed. The main routine ORs the last word; the mirror routine assigns it. | New `fill_span_to_cga`. The EGA versions are `#if !TD_CGA`. |
| 0x2EDC | 0x2E5C | fill_scenery_above_road | `(cut_x+0x20) >> 3` words of 0x5555, then grass, 0x28 words per row. There is no mirror hole: draw_mirror_background overwrites that area. | `#if TD_CGA` block |
| 0x2F7A | 0x2EE1 | draw_road_mirror | clip_x0 0x3C, clip_x1 0x50; cut clip `>> 2` / 0x50 / `<< 2`. | `#if` / `EGA_CGA` |
| 0x33FB | 0x3365 | draw_mirror_background | Does not call select_road_buffer, set the clip or call `clear_clip(8)`. Rows are written at byte 0x3C: 10 words of 0x5555 and grass. | `#if TD_CGA` block |
| 0x4792 | 0x46CA | stage_enter_install_isr | Road buffer `create_buffer(0x50, 0x70)` is called with 2 arguments. The inst and gbox buffers also get 2 arguments (TDCGA create_buffer, C 0x4EA5, reads only w and h). | `EGA_CGA(0x28,0x50)`; the third argument is passed as 0 in CGA builds. |
| 0x47C3 | 0x46F7 | stage_enter_install_isr | Name lists: xroada DS:0AFE (116 names, no `gvrm`). Then `res_find_list(g_xroadC = xroadb.cmp, DS:0CCF, DS:1146)`: one list of 132 names (the EGA xroadb and xroadc lists merged), so there is no separate xroadc handle table. car DS:0EE0; digits DS:0F45 (0-9, spdo, tach). | `#if TD_CGA` |

## 2. Value differences (`EGA_CGA`)

- Colours, 9 sites: text colour 0x0F becomes 3 (play-again menu, logo footer, credits body, scores body,
  results text) or 2 (BACK TO DOS, credits headings). The score-table heading 0x0C becomes 1.
- Row width 0x28 → 0x50 bytes, 23 sites: page buffer (main, run_game), every `gfx_set_clip(screen, 0, 0x28, ...)`
  (intro car, show_car ×7, showroom ×2, stage_results ×2, results_scroll, run_stage), select_road_buffer,
  draw_road_main/mirror clip_x1 and xclip_bytes (×4), and the road buffer in stage setup.
- Archive reserve sizes, 12 sites: tdsnd 0x26D1→0x153D; ACCOLADE/TESTDRV 2000→1000; `<car>sb` 0x109A→0x908 (×2);
  llogo/slogo/gas 2000→1000; car archive 0x7D0→0x3E8.
- File names: the literal format strings `"%ssb.pes"`/`"%s.pes"` become `.cmp`. DGROUP names are handled by
  the string offsets below.
- DGROUP string offsets, 55 sites: +0x0B/+0x0C in `flow.c` (0x63→0x6E, 0x8C→0x98, …, 0x1F5→0x201) and
  `flow_screens.c` show_car (0x235→0x241, …); −0x0A in credits and scores (0x2BE→0x2B4, …, 0x4CE→0x4C4);
  stage_results 0x768/0x770/0x775 → 0x75E/0x766/0x76B; results 0x865→0x85B; scene overlays 0x1FF7/0x2019 →
  0x1FCA/0x1FEC. The results-message tables are now written as `DS_MSG_TABLES + k`, so the EGA build is
  unchanged.
- Other raw DS offsets:
  - `flow_stage.c` / `scene.c`: `DS_STAGE_START` 0x6361→0x6331; `note_div` source 0x208F→0x2062.
  - `scene_cockpit.c`, 16 offsets, car sprite handles and car data, −0x2D: 0x138F→0x1362, 0x1393, 0x1397,
    0x139B, 0x139F, 0x13A3, 0x13B7, 0x13BF, 0x13C3, 0x13D7, 0x13DF, 0x140F, 0x1387, 0x138B; 0x269B/0x269D,
    0x27FB, 0x2809, 0x29B7. Radar song 0x0B0F→0x0AF7.
  - `scene_draw.c`, as local `H_*` / `DS_*` macros: poles 0xFA7→0xF7E, scenery 0xFC7→0xF9E,
    clfa/clfo 0xF9F/0xFA3→0xF76/0xF7A, mcfa/mcfo 0x1027/0x102B→0xFFE/0x1002, signs 0x1043→0x1016,
    posts 0x1123→0x10F6, hazard 0x1133→0x1106, traffic 0x1173/0x1177→0x1146/0x114A,
    cop 0x132B/0x134B/0x137B/0x137F→0x12FE/0x131E/0x134E/0x1352, mirror cop 0x1303→0x12D6,
    cop_row_smooth 0x1447→0x140E, far-car lists 0x9AD/0x9D5→0x995/0x9BD, row_sy[39] 0x1BC1→0x1B94.
  - `scene_project.c`: road record table 0x2B70→0x2B40.
  - `sim.c`: SINQ jump tables 0x205F/0x206B→0x2032/0x203E; road record 0x2B70→0x2B40; traffic list moves
    0x963/0x96B→0x94B/0x953, 0x98B/0x993→0x973/0x97B, 0x975→0x95D.
  - `sim_setup.c`: car data 0x27FB/0x27FD/0x27FE/0x27FF/0x2800→0x27CE/0x27D0/0x27D1/0x27D2/0x27D3;
    `car_data_ptr` 0x268F→0x2662.
- Code addresses stored in DGROUP jump tables, 12 sites (SINQ interpolation targets and the cop FSM table
  DS:0A36→0A1E): the TDCGA ISR is the TDEGA ISR moved down by 0xC8. `SIM_CS(a)` handles this, and the
  values were checked against both images.
- Handled by existing symbols or the memory model: DGROUP 0x0C9A→0x0A8A, the screen descriptor 0x5A7C→0x5750,
  CS clip offsets, `add sp` argument counts of the replaced calls, and every symbol-mapped `mov`/`add`
  immediate in the list.

## 3. Symbol overrides added (`tools/xmap.py` → `DS_OVERRIDES`)

These symbols were unmapped for one of two reasons: they are referenced only inside differing stretches, or
only as `ds:[bp+disp]`, which xmap does not vote on. The CGA addresses were read from the listings and are
consistent with the −0x2D shift of the neighbouring row arrays.

| Symbol | EGA | CGA | Evidence |
|---|---|---|---|
| marker_save_sprite | 0x08C0 | 0x08C0 | C 0x3606 `mov cx, 0x8c0` |
| spr_roof | 0x13DB | 0x13AE | C 0x1D89 (car_handles + 0x58) |
| row_cx | 0x1B23 | 0x1AF6 | C 0x28E2 |
| row_obj | 0x1D03 | 0x1CD6 | C 0x205E |
| row_cx_mirror | 0x1E43 | 0x1E16 | C 0x2F8E |
| row_obj_mirror | 0x1FAB | 0x1F7E | C 0x2491 |
| road_halfwidth_q4 | 0x21A5 | 0x2178 | C 0x218A (+4 at C 0x2F25) |
| row_depth_Z | 0x2247 | 0x221A | C 0x211F |

After regenerating the files, `symbols.h` gained exactly these 8 CGA defines and nothing else changed.
Symbols that do not exist in TDCGA stay unmapped and are compiled out: `g_xroadB`, `xroadc_handles`,
`spr_gvrm`, `pal_game`, and `mask_left_from_bit` / `mask_right_to_bit` / `mask_single_pixel`. The CGA mask
tables have a different layout (u16 at DS:1410/1420, u8[4] at DS:1430), so `scene_draw.c` uses local defines.

## 4. What the graphics and platform layer must provide for CGA builds

- **`FarPtr load_packed_near(const char *fname, u16 ds_buf, u16 *len)`** (TDCGA 0x73EA, unmatched,
  declared in `game/flow.h`). It opens `fname` and reads the 4-byte header, keeping its first word for `*len`.
  It unpacks the data (0x83 RLE escape) to DGROUP:ds_buf+4, then relocates the offset table there the same
  way load_archive does: count word, then count × 4 far pointers made absolute and normalised. It returns
  DGROUP:ds_buf. main calls it with "xroada.cmp" and DS:73AA.
- `gfx_create_buffer`: TDCGA's version (0x4EA5) ignores the third argument, and the game passes 0 or 0x0F.
  Rows are addressed as `CS:[rowtab + 2y]` offsets inside the sprite segment. The descriptor's `+0x0A` is
  copied to DS:0898, and `+0x00`/`+0x02` are copied to DS:0894/0896. The road code writes 2bpp words
  directly at `DS:[0896]:CS:[rowtab+2y]`, 80 bytes per row, so the CGA layer must build that row table.
- `gfx_herc_init` / `gfx_herc_shutdown` (declared). Game code uses no other herc routine.
- Game code no longer calls these in CGA builds: `gfx_set_palette`, `gfx_scroll_window`, `blit_xor_clip_hot`.

## 5. Open doubts

- DS:73AA buffer size: how much of DGROUP the unpacked `xroada.cmp` occupies, and whether it overlaps later
  globals. That is the original's layout; the platform implementation should check it.
- `symbols.h` (CGA section) also maps `FN_blit_xor_clip_hot` → 0x4C0C (= `blit_or_clip_hot`),
  `FN_gfx_scroll_window` → 0x5A54 (= `blit_copy_clip_raw`), and `FN_gfx_set_palette` / `FN_gfx_set_border`
  → 0x4BCE / 0x4BC2. These are artefacts of the call alignment, not real TDCGA equivalents. They are harmless
  to game code but should not be trusted by the graphics layer.
- In `stage_enter_install_isr`, the port passes 0 for the missing third create_buffer argument. The original
  leaves whatever is on the stack there, and TDCGA's create_buffer never reads it.
- The existing EGA TODO(verify) notes (top_sy wrap in the span and scenery loops) apply to the CGA versions
  unchanged.
