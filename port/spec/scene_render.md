# scene_render — Test Drive (1987) TDEGA.EXE, image 0x1F4E–0x3AFF

Porting spec for stage start, per-frame scene composition, road projection (main view and mirror),
road-side objects, traffic, police, hazards, cockpit overlay and buffer-to-screen copy.
Address conventions follow `port/RE_GUIDE.md`. Road data format: `FORMATS.md` §Road data.
Tables: `port/spec/tables/*.json` (names listed in §4.0).

Most routines in this range are hand-written assembly with register calling conventions. The
Ghidra decompile loses those arguments (BX/CX/DX/DI inputs) and gets a few flag tests wrong.
Everything below was re-derived from disassembly (`tools/x86dis.py … dis 1dc0 0x1d58`) unless
marked otherwise.

---------------------------------------------------------------------------------------------

## 1. Overview

### 1.1 What the subsystem does

The driving screen has three vertical parts:

* Rows 0–18: the car roof (`roof`), drawn once.
* Rows 19–110 (0x13–0x6E): the road window, full 320 px wide. The **rear-view mirror** sits inside it
  at x 240–319, rows 27–44 (0x1B–0x2C).
* Rows 111–199: the dashboard (`dash`, instruments, radar detector, steering wheel, gear box).

The road window is **composed off-screen**. At stage start, 0x4792 allocates a RAM bitmap of
40 bytes × 112 rows with 3 bit planes (colours 0–7, plane map `01 02 04 00`). Each frame it is
cleared, drawn and copied to VRAM with one replace-blit (`0x3AF7` → `0x5DE2`). There is **no CRTC
page flipping and no dirty-rectangle tracking** for the road window; it is repainted every frame.
Dashboard items are drawn directly on screen:

* The radar detector and steering-wheel graphics are redrawn every frame; the wheel uses XOR toggles and a save-under.
* The instrument cluster is rebuilt in a second RAM buffer and copied only when `DS:0923` is set.
* The gear box uses a third RAM buffer and is copied only when `DS:0922` is set or its visibility changes.

The simulation (speed, steering, road pointer advance, traffic AI) runs inside the **timer interrupt**
(int 8 handler at CS:0x3B1F, simulation spec). The render loop is free-running. At the start of each
frame, `0x2013` snapshots the ISR-owned state (road pointer, sub-unit position, traffic slots, police
state) into render copies, so a frame is internally consistent.

Projection works on 40 road "rows" (one road unit each) ahead of the car, or 25 behind it for the mirror:

* The road byte stream is walked from the car position. Curvature integrates into a heading and pitch
  into a slope. `sin()` of each gives lateral X and vertical Y accumulators.
* Each row has a fixed depth `Z[i]` and a fixed road half-width `W[i]` (tables).
* Screen x = 150·X/Z (quarter-pixel precision, `600·X/Z`). Screen y = 180·Y/√(X²+Z²), computed with a
  tan/sin table trick (§4.3).
* Rows hidden behind a crest are culled by keeping a running "highest scanline so far". Scanline spans
  are interpolated between visible rows into per-scanline edge arrays.
* Objects are pushed onto the stack **near→far** while walking the rows, then popped and drawn **far→near**
  (painter's order). Each object is clipped to the current crest scanline, so it disappears behind hills.

### 1.2 Call graph (per frame)

```
0x1DC0 drive_stage (game_flow range; composition loop documented here)
 ├─ once: 0x1F4E stage_init_road_ptr, 0x1F93 reset_car_state, 0x4792 load_stage_resources (sim range)
 │        0x3AC2 select_screen, 0x50A1 set_clip(screen,0,40,0x13,200), 0x74F4 fill(8)
 │        0x6D1C blit_replace_own(dash), 0x6D1C(roof)
 └─ loop:
     0x2013 snapshot_sim_state
     0x2054 project_road_main ──► 0x39EB sin_deg, 0x2421 proj_y_main ─► 0x3A18 atan_lookup
     │                             0x23F2 proj_x_main, 0x3A37 interp_edge_span
     0x2478 project_road_mirror ─► 0x39EB, 0x285B proj_y_mirror ─► 0x3A18, 0x282C proj_x_mirror, 0x3A37
     0x3ACE select_road_buffer
     0x74F4 fill_clip(8)                       ; clear road window
     0x2EDC fill_scenery_above_road
     0x28C5 draw_road_main ─► 0x2DEE fill_road_scanlines_main ─► 0x2E8B fill_span_to
     │                        0x8058 XOR blit, 0x4DF1 OR blit, 0x8308 AND blit
     0x33FB draw_mirror_background ─► 0x3ACE, 0x74F4
     0x2F7A draw_road_mirror ─► 0x3306 fill_road_scanlines_mirror ─► 0x339E fill_span_to_mirror
     0x349D draw_buffer_overlays (mirror frame mask, ticket, "Pulling into…" text)
     0x3AF7 present_road_buffer ─► 0x5DE2 (replace blit of buffer to VRAM)
     0x35C6 draw_dashboard_dynamic (radar lights, wheel, marker, gauges) ─► 0x38CD draw_digit
     0x351A draw_gear_box
     0x8BAF rng_stir (platform)
     exit/crash/finish handling:
       0x392C crash_windscreen_sequence (0x929>=3) ; 0x38EB dealership_ending (stage 5)
       0x1F7B wait_fire_button
```

---------------------------------------------------------------------------------------------

## 2. Function table

| image addr | proposed name | signature | purpose | confidence |
|---|---|---|---|---|
| 0x1DC0 | drive_stage | `int drive_stage(void)` → BX: -1 abort/demo timeout, 1 stage finished, 0 game over | Stage driving loop, frame composition order (game_flow range; see game_flow for the result handling) | verified |
| 0x1F4E | stage_init_road_ptr | `void(void)` | road ptr = stage start + 45, zero sub-unit and tick counter, wheel state = centre | verified |
| 0x1F7B | wait_fire_button | `void(void)` | Poll 0x5C24 until bit 0x10 (fire/Enter) or no input device; returns at once in demo mode (DS:0084≠0) | verified |
| 0x1F93 | reset_car_state | `void(void)` | Per-life reset of car, traffic, police, redraw flags | verified |
| 0x2013 | snapshot_sim_state | `void(void)` | Copy ISR-owned state to render copies | verified |
| 0x2054 | project_road_main | `void(void)` | 39-row projection, change detection, crest culling, scanline edge arrays | verified |
| 0x23F2 | proj_x_main | `AX = f(BX=X, DX=Z)` | 600·X/Z clamped ±3200, + 480 (1/4 px) | verified |
| 0x2421 | proj_y_main | `AX = f(BX=X, DX=Z, CX=Y)`, BX/DX preserved | perspective y, see §4.3 | verified |
| 0x2478 | project_road_mirror | `void(void)` | Same for 24 rows behind, mirror window | verified |
| 0x282C | proj_x_mirror | `AX = f(BX=X, DX=Z)` | 150·X/Z clamped ±800, + 1120 | verified |
| 0x285B | proj_y_mirror | `AX = f(BX,DX,CX)` | proj_y then `sar 2`, clamp 0..17, + 10 | verified |
| 0x28C5 | draw_road_main | `void(void)` | Road fill, centre line, poles, rocks, signs, traffic, police, hazards, horizon cliff | verified |
| 0x2DEE | fill_road_scanlines_main | `void(void)` | Per scanline: cliff/grass/shoulder/road spans into buffer planes | verified |
| 0x2E8B | fill_span_to | `ZF = f(AX=x_end, DX=byte pos, DI=ptr, ES=plane, [1463]=bit)` | Set bits from current position to pixel x_end-1 | verified |
| 0x2EDC | fill_scenery_above_road | `void(void)` | Rows 0x13..top of road: left colour 4 / right colour 2 split | verified |
| 0x2F7A | draw_road_mirror | `void(void)` | Mirror version of 0x28C5 | verified |
| 0x3306 | fill_road_scanlines_mirror | `void(void)` | Mirror version of 0x2DEE | verified |
| 0x339E | fill_span_to_mirror | as 0x2E8B, clamps x ≥ 240 | | verified |
| 0x33FB | draw_mirror_background | `void(void)` | Clear mirror rect, scenery split | verified |
| 0x349D | draw_buffer_overlays | `void(void)` | `mirr` AND mask, `tick` sprite, status text | verified |
| 0x351A | draw_gear_box | `void(void)` | Gear gate + knob via RAM buffer | verified |
| 0x35C6 | draw_dashboard_dynamic | `void(void)` | Radar lights, wheel XOR, wheel marker, needles/digital gauges | verified |
| 0x38CD | draw_digit | `(BL=digit, DX=screen x)` | OR-blit digit sprite at (x − inst_x, 0x20) into instrument buffer | verified |
| 0x38EB | dealership_ending | `void(void)` | Stage-5 finish: `deal`, `note`, wait for keys | verified |
| 0x392C | crash_windscreen_sequence | `void(void)` | Redraw scene, then 7 steps of windscreen crack lines | verified |
| 0x39EB | sin_deg | `AX = sin15(AX signed deg)`, clobbers BH,CX,SI | 15·sin via 91-entry table | verified |
| 0x3A18 | atan_lookup | `AX = deg(AX=ratio·256)`, 45..90 | search tan256 table | verified |
| 0x3A37 | interp_edge_span | `(AX=a, BX=b, CL=n, DL=n, DI=dest)` writes n words | Bresenham-like span interpolation with clamp (§4.5) | verified |
| 0x3AC2 | select_screen | `void(void)` | 0x5128(CS:5A7C) — target VRAM | verified |
| 0x3ACE | select_road_buffer | `void(void)` | 0x5128(CS:[0890]) + clip x 0..40 bytes, y 0x13..0x6F | verified |
| 0x3AF7 | present_road_buffer | `void(void)` | Select screen, clip y1=0x6F, 0x5DE2(buffer sprite) | verified |

Called functions owned by other specs:

| addr | name used here | args as called | notes |
|---|---|---|---|
| 0x4792 | load_stage_resources | – | simulation/platform: allocs buffers, loads sprite tables (§3.3), hooks int 0/int 8 |
| 0x5128 | select_target(far ptr desc) | 12-word target descriptor copied to CS:5A64 | platform |
| 0x50A1 | set_target_clip(desc,x0b,x1b,y0,y1) | (CS:5A7C,0,0x28,0x13,200) | clip x in **bytes** (8 px) |
| 0x74F4 | fill_clip_rect(colour) | 8 | fills current clip rect |
| 0x4DF1 / 0x8308 / 0x8058 | blit_or / blit_and / blit_xor (sprite far, x, y) | position minus hotspot | EGA func select 0x10 / 0x08 / 0x18 |
| 0x6CBE / 0x7A37 / 0x7C3B | replace / OR / AND at (x,y) minus hotspot | | |
| 0x6D1C / 0x7A5F / 0x7C63 / 0x7E7C | replace / OR / AND / XOR at sprite's own (x&~3, y) | | |
| 0x4E19, 0x5DE2 | OR / replace at sprite's own position | | |
| 0x8C00 | grab_screen(save sprite, x, y) | (DS:08C0, x, y) | save-under |
| 0x85D5 | draw_line(x1,y1,x2,y2,colour) | colour 0xFFFF | clipped to current clip |
| 0x6C85 / 0x9507 | set_text_attr(a,b) / print_centered(str,y) | (3,0) / (str, 0x50) | x = 160 − 4·len |
| 0x5C24 | read_input | returns AL bits (0x10 = fire) | 0x5C24 did not decompile |
| 0x8A3E / 0x8A0E / 0x8A08 | sound tick / queue song / stop | radar beep song DS:0B0F | |
| 0x8BAF | rng_stir | – | rotates a byte of DS:6522 table |

---------------------------------------------------------------------------------------------

## 3. Globals

### 3.1 Inputs from simulation (read here; update logic in simulation spec)

| DS | name | type | meaning | written by | read by |
|---|---|---|---|---|---|
| 0906 | road_ptr | u16 DS-pointer into road stream | car's current road unit | 0x1F4E, sim 0x41FC | 0x2013, 0x2478, 0x1DC0 |
| 0912 | road_subpos | s16 | sub-unit counter (drops with speed, +90 per unit) | 0x1F4E, sim | 0x2013 |
| 0910 | car_lateral | s16 | lateral position, init −117 (0xFF8B); edge ±0x264 | 0x1F93, sim | 0x2054/0x2478 (`sar 3`) |
| 090C | car_heading | s16 (deg·256) | heading relative to road | 0x1F93, sim | 0x2054 (+), 0x2478 (−) |
| 0914 | steer | s16 | steering input/wheel angle | 0x1F93, sim | 0x35C6 |
| 0927 | speed_w | u16 | speed; high byte DS:0928 = mph shown | 0x1F93, sim | 0x35C6, 0x1DC0 |
| 091B | rpm | u16 | engine rpm, init 800 | 0x1F93, sim | 0x35C6 |
| 0929 | drive_state | u8 | 0 driving, 1 quit, 2 end of road (gas station/dealer), ≥3 crash | 0x1F93, sim | 0x2054, 0x2478, 0x349D, 0x1DC0 |
| 092A | road_end_ptr | u16 | when state≠0, stream at ≥ this ptr reads as record 0 | sim 0x427B | 0x2054, 0x2478 |
| 1433 | dash_phase | u8 | +1 per road unit advanced | sim 0x4236 | 0x28C5, 0x2F7A |
| 0941/0942 | traffic_count_left/right | u8 | used slots in each lane list | sim | 0x2013 |
| 0945 | traffic_slots | 13×8 bytes | slot: +0 road unit (0 = empty), +2 sub-pos, +4 ?, +6 sprite group offset (lo) / hazard lane (hi) | sim | 0x2013 (copy) |
| 0A23 | cop_state | u8 | 0 none … 6 ticket, 7 hidden | 0x1F93, sim | 0x2013, 0x349D |
| 0A2D/0A2B/0A29 | cop_pos/cop_sub/cop_lane | s16 | police unit, sub-pos, lateral 0..16 | sim | 0x2013 |
| 0A27 | ticket_flag | u8 | 0 ⇒ show `tick` while state 6 | sim | 0x349D |
| 80A4 | tick_count | u16 | incremented in timer ISR; bit 3 flashes lights | 0x1F4E, ISR | 0x28C5, 0x2F7A, 0x35C6, 0x1DC0 |
| 08BE/08BF | gearbox_visible / _prev | u8 | 1 = shift gate shown | input/sim / 0x351A | 0x351A |
| 091F | gearbox_hide_delay | u8 | frames until gate closes (init 13) | 0x1F93, 0x351A | 0x351A |
| 0920/0922/0923 | redraw flags | u8 | 0922 gear box, 0923 instruments need redraw | 0x1F93, sim | 0x351A, 0x35C6 |
| 0A7D/0A7F | knob_x/knob_y | s16 | gear knob screen pos (init car+0x20/+0x22) | 0x1F93, sim | 0x351A |
| 7B16 | stage_index | u16 | 0..4 | game_flow | 0x1F4E, 0x1DC0, 0x349D |
| 0084 | demo_mode | u16 | nonzero in attract demo | game_flow | 0x1F7B, 0x1DC0 |
| 790A | units_mode | u16 | ==2 subtracts 18 from needle speed index | game_flow | 0x35C6 |
| 268F.. | car_bin | 0x4D6 bytes | 269B/269D wheel centre x,y (+0C/+0E); 2693 rev limit; 27FB needle gauges; 27FD..2800 needle pivots; 2809 speedo tips; 29B7 tach tips | 0x10E2 | 0x35C6, 0x4792 |

### 3.2 Render state (owned here)

| DS | name | type | meaning | written by | read by |
|---|---|---|---|---|---|
| 186D | walk_ptr | u16 | stream ptr during projection | 0x2013/0x2054/0x2478 | same |
| 186F | r_road_ptr | u16 | frame snapshot of 0906 | 0x2013 | 0x28C5, 0x2F7A, 0x35C6 |
| 1871 | r_subpos | s16 | snapshot of 0912 | 0x2013 | 0x28C5, 0x2F7A |
| 09AD | r_traffic_slots | 13×8 | snapshot of 0945 (slots 0–4 left lane 09AD, 5–9 right lane 09D5, 10 09FD, 11 radar/cop-ahead 0A05, 12 hazard 0A0D) | 0x2013 | 0x28C5, 0x2F7A, 0x35C6 |
| 0A30/0A34/0A32/0A24 | r_cop_pos/sub/lane/state | | snapshots | 0x2013 | 0x28C5, 0x2F7A |
| 0943/0944 | r_traffic_count_l/r | u8 | snapshots | 0x2013 | 0x28C5 |
| 1873 | heading_acc | s16 | curve integrator (deg·256) | 0x2054/0x2478 | |
| 1875 | slope_acc | s16 | pitch integrator (deg·256) | 0x2054/0x2478 | |
| 1877+2i | X[i] main | s16 ×40 | lateral accumulator, X[0] = 0910 sar 3 | 0x2054 | 0x2054 |
| 18C7+2i | Y[i] main | s16 ×40 | vertical accumulator, Y[0] = −12 | 0x2054 | |
| 1917+2i / 1967+2i | X[i] / Y[i] mirror | s16 ×25 | same for mirror | 0x2478 | |
| 1B73+2i | sy[i] | u8 at even offsets (odd bytes stay 0) | screen scanline of row i | 0x2054 | 0x28C5 |
| 1B23+2i | cx[i] | s16 | centre x (px) | 0x2054 | 0x28C5 |
| 19E3/1A33/1A83/1AD3 +2i | ol/l/r/or[i] | s16 | outer-left (shoulder), left edge, right edge, outer-right (px) | 0x2054 | 0x28C5 |
| 1D03+2i | obj[i] | u8 | record object byte of row i | 0x2054 | 0x28C5 |
| 1E7F,1E43,1D53,1D8F,1DCB,1E07,1FAB (+2i) | mirror sy,cx,ol,l,r,or,obj | | | 0x2478 | 0x2F7A |
| 1465/1543/1621/16FF +2y | span_ol/l/r/or[y] | s16 ×111 | per-scanline edges, main | 0x2054 | 0x2DEE |
| 17DD/1801/1825/1849 +2y | mirror span arrays | s16 ×18 | | 0x2478 | 0x3306 |
| 19C7 | first_changed_row | u16 (bp) | 0 = no change so far | 0x2054/0x2478 | |
| 19C9 | prev_row_limit | u16 | last frame's 19CB / 19DD | 0x2054/0x2478 | |
| 19CB / 19DD | row_limit_main / _mirror | u16 (bp) | rows drawn: bp < limit | 0x2054/0x2478, 0x1F93 (0) | 0x28C5 / 0x2F7A |
| 19CD / 19DF | top_sy_main / _mirror | u8 | smallest sy (init 0x6F / 0x11) | | 0x2DEE, 0x2EDC / 0x3306, 0x33FB |
| 19CF / 19E1 | top_row | u16 (bp) | row of top_sy | | 0x28C5 |
| 1439/143B, 1443 | cached_top_sy / cached_top_row | u8/u16 | | 0x2054/0x2478 | same |
| 19B7 / 19D5 | cut_x | s16 | leftmost outer-right edge (init 0x141; −33 / 0xE6 if the road leaves the screen left) | | 0x28C5, 0x2EDC / 0x2F7A, 0x33FB |
| 19B9 / 19D7 | cut_sy | u16 | sy at cut_x | | cliff sprite y |
| 19BB / 19BD | cut_row | u16 (bp) | row at cut_x | | x-clip switch row |
| 19BF / 19C1 | cut_top_sy | u8 | top_sy when cut recorded (unused) | | – |
| 19C3 / 19D9 | min_ol | s16 | smallest outer-left seen on a descending run | | 0x2DEE / 0x3306 |
| 19C5 / 19DB | min_ol_sy | u8 (doubled in place by 0x2DEE/0x3306) | | | |
| 19D1 / 19D3 | span_clamp_min / max | s16 | 0 or 0xF0 / 0x141 → cut_x+6 | | 0x3A37 |
| 1435 | mirror_rows_done | u16 | bp while mirror loop runs (unused) | 0x2478 | – |
| 1434 | dash_counter | u8 | 1433 (+1 per row) main; 1433−2 (−1 per row) mirror | | |
| 1437 | crest_sy | u8/u16 | current clip bottom (highest visible scanline so far) | | |
| 143D | obj_scale | u16 | s = min(W[i]>>4, 31) main; min(W[i+1]>>5, 31) mirror | | |
| 143F / 1441 | xclip_px / xclip_bytes | u16 | 320/40, narrowed at cut_row | | |
| 1447 | cop_row_smooth | u16 | last row the cop was drawn on (shared by main and mirror) | | |
| 1445 | wheel_state | u8 | 0 right, 1 centre, 2 left | 0x1F4E, 0x35C6 | 0x35C6 |
| 1446 | marker_saved | u8 | save-under valid | 0x1F4E, 0x35C6 | 0x35C6 |
| 08F0/08F2 | marker_save_x/y | s16 | save-under position | 0x35C6 | 0x35C6 |
| 08C0 | marker_save_sprite | sprite hdr (16×4 px, 4 planes) | save-under buffer | static | 0x35C6 |
| 1463 | span_bit | u16 | bit position inside current byte during fills | 0x2DEE.. | |
| 203B | cur_curve | u8 | temp: record curve byte | 0x2054 | |
| 0890/0892 | road_buf_desc | far ptr (CS seg) | 12-word target descriptor of road buffer | 0x4792 | 0x3ACE |
| 0894/0896 | road_buf_sprite | far ptr | sprite header of road buffer | 0x4792 | 0x3AF7 |
| 0898 | road_buf_rowtab | u16 (CS offset) | row-offset table, 112 entries (row·40) | 0x4792 | fills |
| 089A,089E/08A0 | inst_buf desc / sprite | far | instrument buffer (size of `inst`) | 0x4792 | 0x35C6 |
| 08A2/08A4/08A6/08A8 | inst_x, inst_y, inst_h, inst_wbytes | u16 | from `inst` header +8,+A,+2,+0 | 0x4792 | 0x35C6 |
| 08AA/08AC, 08AE/08B0 | speedo / tach pivot (buffer coords) | u16 | car+0x16E.. minus inst_x/y | 0x4792 | 0x35C6 |
| 08B2,08B6/08B8,08BA/08BC | gbox_buf desc / sprite / screen x,y | | | 0x4792 | 0x351A |
| 092C/092E/0930/0932 | proj constants | s16 | 480, 70, 1120, 10 (static) | – | proj fns |
| CS:5A64–5A7B | cur_target | 12 words | +2..+8 plane segs (5A66 plane0, 5A68 plane1, 5A6A plane2, 5A6C plane3), +A row table, 5A70/5A72 clip x0/x1 **bytes**, 5A74/5A76 clip y0/y1 (y1 exclusive), 5A78 bytes/row | 0x5128 | blitters |
| CS:5A7C | screen_desc | 12 words | VRAM target (planes A000) | static | |

### 3.3 Sprite handle tables (filled by 0x4792; full list in `tables/sprite_handle_tables.json`)

Each entry is a 4-byte far pointer. Base and index: `DS:base + 4·k`.

* **XROADA @0F9F:**
  * k0 `clfa`, k1 `clfo` (horizon cliff mask/image)
  * k2–5 `pal0-3`, k6–9 `pol0-3` (poles: mask/image, 4 scales)
  * k10–33 scenery groups: `rcka-d`, `rcke-h`, `wed0-3`, `lina-d`, `line-h`, `lini-l`
  * k34/35 `mcfa/mcfo` (mirror cliff), k36/37 `govr/gvrm`, k38 `deal`, k39 `note`, k40 `tick`
  * k41–96 signs: 7 types × 8 entries, laid out `[sp30,sa30, X2,Xa2, X3,Xa3, X4,Xa4]`
  * k97–100 `pst0-3` (posts)
  * k101–116 hazards: `rcka-d`, `oil0-3`, `pot0-3`, `gra0-3`
* **XROADB @1173:** 5 front-view groups (`rig`, `rx7`, `vnf`, `sed`, `sed`) × 5 scale pairs in the order
  `*0,*4,*1,*2,*3`, each pair (image, mask). The group offset is 0x28 bytes.
* **XROADC @123B:** rear-view groups `trk`, `x7r`, `vnr`, `sdr`, `sdr` (offset 0x00–0xA0).
  * k50–59 `cop0 cp0m cop1 cp1m cop2 cp2m cop2…` (cop front)
  * k60–69 `cpr0,cr0m,cpr4,…,cpr3` (cop rear), k70–79 `clr*` (light-bar frames)
  * k80/81 `copb/copm` (close-up bumper)
* **CAR @1383:** k0 `dash`, 1 `dot `, 2 `dota`, 3 `gbo0`, 4 `gbox`, 5 `gnob`, 6 `gnab`, 7–12 `inl1 ina1 inl2 ina2 inl3 ina3`,
  13 `inst`, 14 `mirr`, 15 `rad0`, 16–20 `rad5..rad1`, 21 `radb`, 22 `roof`, 23 `whl1`, 24 `whl3`.
* **DIGITS @13E7** (only when DS:27FB≠1): `0`–`9`, `spdo`, `tach`, `tac1-3`.

---------------------------------------------------------------------------------------------

## 4. Pseudocode

Types: `u8 s8 u16 s16 u32`. `sar` = arithmetic shift. All arithmetic is 16-bit and wraps.
`div32_16(n, d)` means the x86 `DIV`. **Division overflow or /0 is caught by the game's int 0 handler
at DS:1423:** it returns `AX = 0xFFFF`, DX unchanged, and resumes after the 2-byte `div` (the NOP pairs
after every div exist for this). The port must implement:

```c
u16 div32_16(u32 n, u16 d) { if (d == 0 || n / d > 0xFFFF) return 0xFFFF; return n / d; }
```

### 4.0 Tables (`port/spec/tables/`)

`sine_x15`, `persp_T`, `tan256`, `road_halfwidth_q4` (W), `row_depth_Z` (Z), `traffic_scale_main`,
`traffic_scale_mirror`, `mask_left_from_bit`, `mask_right_to_bit`, `mask_single_pixel`,
`roadside_pattern`, `windscreen_cracks`, `wheel_sin90`, `wheel_cos90`, `sprite_handle_tables`,
`projection_constants`, `object_scale_per_row` (derived).

Road record table DS:2B70 and stream DS:2D28 are in FORMATS.md: `rec[b] = {flag, curve s8, pitch s8, obj u8}`.

### 4.1 Stage start / per-life / per-frame snapshot

```c
void stage_init_road_ptr(void) {            // 0x1F4E
    road_ptr   = stage_ptr[stage_index] + 0x2D;   // DS:6361[]; 45 units into the stage
    road_subpos = 0; tick_count = 0; w_0A21 = 0;
    wheel_state = 1; marker_saved = 0;
}
void reset_car_state(void) {                // 0x1F93 (after crash and at stage start)
    speed_w = 0; car_lateral = (s16)0xFF8B; rpm = 800; w_091D = 800;
    steer = 0; w_090A = 0; car_heading = 0; w_090E = 0;
    row_limit_main = 0; row_limit_mirror = 0;          // invalidates projection cache
    drive_state = 0; b_0A78 = 0; b_0924 = 0; b_093C = 0; b_0938 = 0;
    cop_state = 0; traffic_count_left = traffic_count_right = 0; b_08F4 = 0;
    for (k = 0; k < 13; k++) traffic_slots[k].pos = 0;   // word at 0945+8k
    w_64FC = w_208F; w_6500 = 900; w_64FE = 0xFFFF;      // sound (platform)
    knob_x = car_bin[0x20]; knob_y = car_bin[0x22];
    gearbox_hide_delay = 13; redraw_0922 = redraw_0923 = flag_0920 = 1;
}
void snapshot_sim_state(void) {             // 0x2013, first thing every frame
    memcpy(DS+0x09AD, DS+0x0945, 0x68);   // 13 slots
    walk_ptr = r_road_ptr = road_ptr; r_subpos = road_subpos;
    r_cop_pos = cop_pos; r_cop_sub = cop_sub; r_cop_lane = cop_lane; r_cop_state = cop_state;
    r_traffic_count_l = traffic_count_left; r_traffic_count_r = traffic_count_right;
}
```

### 4.2 sin and atan lookup

```c
s16 sin_deg(s16 a) {                 // 0x39EB, a is a sign-extended byte (-128..127)
    int neg = 0;
    if (a < 0) a += 360;
    if ((u16)a > 180) { a -= 180; neg = 1; }
    if ((u8)a > 90) a = (u8)(180 - (u8)a);
    s16 v = sine_x15[a];              // 0..15
    return neg ? -v : v;
}
u16 atan_lookup(u16 q) {             // 0x3A18, q = max*256/min
    int bx = ((s16)q > 0x27A) ? 0x5A : 0x2E;   // SIGNED compare: q>=0x8000 (incl. 0xFFFF) starts at 0x2E
    while (q < tan256[bx/2]) bx -= 2;           // unsigned
    return (bx >> 1) + 45;                      // 45..90 degrees
}
```

Quirk: an overflowed ratio (0xFFFF) returns **68°**, not 90°.

### 4.3 Projection primitives

```c
s16 proj_x_main(s16 X, s16 Z) {      // 0x23F2 ; result in 1/4 px
    int neg = X < 0; u16 a = neg ? -X : X, q;
    if (Z <= 0) q = 0xC80;
    else { q = div32_16((u32)a * 600, (u16)Z); if (q > 0xC80) q = 0xC80; }
    return (neg ? -q : q) + proj_cx_main;          // DS:092C = 480
}
s16 proj_x_mirror(s16 X, s16 Z)       // 0x282C: same with 150, clamp 0x320, + DS:0930 (1120)

static u16 proj_y_core(s16 X, s16 Z, s16 Y, int *yneg) {   // shared part of 0x2421 / 0x285B
    u16 ax = X < 0 ? -X : X;
    *yneg = Y < 0; u16 c = *yneg ? -Y : Y;
    u16 r;
    if (Z <= 0) r = 0x45FF;
    else {
        u16 lo = ax, hi = (u16)Z;
        if ((s16)ax > Z) { lo = Z; hi = ax; }       // signed compare
        u16 q   = div32_16((u32)hi << 8, lo);       // lo==0 -> 0xFFFF
        u16 deg = atan_lookup(q);
        u16 p   = div32_16((u32)persp_T[deg] * c, hi);
        r = (p >= 0x4600) ? 0x45FF : p;
    }
    return r >> 8;                                  // 0..0x45
}
s16 proj_y_main(s16 X, s16 Z, s16 Y) {  // 0x2421 -> screen scanline (byte used)
    int yneg; s16 r = proj_y_core(X, Z, Y, &yneg);
    if (!yneg) r = -r;                   // Y >= 0 is above the horizon
    return r + proj_horizon_main;        // DS:092E = 70
}
s16 proj_y_mirror(s16 X, s16 Z, s16 Y) {  // 0x285B
    int yneg; s16 r = proj_y_core(X, Z, Y, &yneg);
    if (!yneg) r = -r;
    r = r >> 2 (sar); if (r < 0) r = 0; if (r > 0x11) r = 0x11;
    return r + proj_y_mirror_off;        // DS:0932 = 10
}
```

In effect `T[atan(hi/lo)]/hi ≈ 46080/√(X²+Z²)`, so `y ≈ 70 − 180·Y/dist` and `x ≈ 120 + 150·X/Z` px.

### 4.4 project_road_main (0x2054)

Row index `i = bp/2`. The code stores arrays at `base + bp`, so element i is at `base + 2i`.

```c
void project_road_main(void) {
    u16 prev_limit = (u8)row_limit_main;          // 19C9 (hi byte stays 0)
    slope_acc = 0; span_min = 0;                  // 1875, 19D1
    (u8)row_limit_main = 0; (u8)first_changed = 0; (u8)cut_row = 0;
    X[0] = car_lateral sar 3;  Y[0] = -12;  heading_acc = car_heading;
    cut_x = 0x141; min_ol = 0x141; span_max = 0x141;
    top_sy = 0x6F; cached_top_sy = 0x6F; (u8)cut_sy = 0x6F; (u8)min_ol_sy = 0x8C;
    (u8)cached_top_row = 2;

    for (i = 1; ; i++) {
        u8 b = *walk_ptr;
        if (drive_state != 0 && (s16)walk_ptr >= (s16)road_end_ptr) b = 0;
        rec = &RECORDS[b]; walk_ptr++;
        obj[i] = rec->obj;
        slope_acc += (s16)(s8)rec->pitch * 4;
        s16 y = sin_deg((s8)(slope_acc >> 8)) + Y[i-1];
        if ((u8)first_changed == 0 && y != Y[i]) first_changed = 2*i;
        Y[i] = y;
        s16 h = heading_acc + (((s16)((s8)rec->curve << 8)) sar 2);   // curve*64
        if (h < -0x4B00) h = -0x4B00; else if (h > 0x4B00) h = 0x4B00;
        heading_acc = h;
        s16 x = 2 * sin_deg((s8)(h >> 8)) + X[i-1];
        if ((u8)first_changed == 0 && x != X[i]) first_changed = 2*i;
        X[i] = x;

        s16 ax, dx; u16 sy;
        if (first_changed == 0 && 2*i < (s16)prev_limit) {      // row unchanged: reuse cache
            ax = ol[i]; dx = or[i]; sy = sy_[i];
            if ((u8)sy < top_sy) { top_sy = sy; top_row = 2*i; cached_top_sy = sy; cached_top_row = 2*i; }
        } else {
            if (first_changed == 0) first_changed = 2*i;
            u8 s = (u8)proj_y_main(X[i], Z[i], Y[i]);
            sy_[i] = s; sy = s;
            if (s < top_sy) { top_sy = s; top_row = 2*i; }
            if (s == sy_[i-1]) {                  // same scanline as nearer row: copy, skip tracking
                cx[i] = cx[i-1]; ol[i] = ol[i-1]; l[i] = l[i-1]; r[i] = r[i-1]; or[i] = or[i-1];
                goto next;
            }
            s16 c = proj_x_main(X[i], Z[i]);
            cx[i] = c sar 2;
            u16 W = road_halfwidth_q4[i];
            u16 W5 = (W >> 2) + W + ((W >> 1) & 1);           // shr,shr,adc
            l[i]  = (s16)(c - W)  sar 2;
            ol[i] = (s16)(c - W5) sar 2;
            r[i]  = (s16)(c + W)  sar 2;
            or[i] = (s16)(c + W5) sar 2;
            ax = ol[i]; dx = or[i];
        }
        // tracking (both paths)
        if (i != 1 && ax < ol[i-1] && ax < min_ol && sy < min_ol_sy /*u16*/) { min_ol = ax; min_ol_sy = sy; }
        if (ax > cut_x) row_limit_main = 2*i;
        if (dx < cut_x) {
            if (sy <= min_ol_sy) { cut_x = dx; cut_sy = sy; cut_row = 2*i; cut_top_sy = top_sy; }
            if (dx <= 0) { if (sy <= min_ol_sy) cut_x = -33; row_limit_main = 2*i; }
        }
    next:
        if ((row_limit_main != 0 && 2*(i+1) > 8) || 2*(i+1) == 0x50) break;
    }
    row_limit_main = 2*(i+1);

    // ---- phase 2: rebuild per-scanline span arrays from the first changed row on
    if (first_changed == 0 || cached_top_sy == top_sy) return;
    u8 crest = cached_top_sy;                     // 1437
    u16 prev = cached_top_row;                    // SI
    for (bp = first_changed; ; ) {
        u8 s = sy_[bp/2];
        u8 n = crest - s;
        if (crest > s && s != sy_[prev/2]) {      // row visible above everything nearer
            if ((s16)bp >= (s16)cut_row) span_max = cut_x + 6;
            crest = s;
            if (n == 1) {
                span_ol[s] = clamp(ol[bp/2]); span_l[s] = clamp(l[bp/2]);
                span_r[s]  = clamp(r[bp/2]);  span_or[s] = clamp(or[bp/2]);
            } else {                                // n scanlines s .. s+n-1
                interp_edge_span(ol[bp/2], ol[prev/2], n, &span_ol[s]);
                interp_edge_span(l[bp/2],  l[prev/2],  n, &span_l[s]);
                interp_edge_span(r[bp/2],  r[prev/2],  n, &span_r[s]);
                interp_edge_span(or[bp/2], or[prev/2], n, &span_or[s]);
            }
            prev = bp;
            if (crest == top_sy) return;
        }
        bp += 2; if (bp == row_limit_main) return;
    }
}
// clamp(v): v < span_min ? span_min : (v > span_max ? span_max : v)   (signed)
```

Notes:
* `crest > s` is the `sub dl,cl ; jbe` test (unsigned). Entries for scanlines of cached rows are
  kept from earlier frames.
* `2*i < prev_limit` is a signed word compare. The hi byte of 19C9 is 0.

**Mirror (0x2478)** is the same with these differences:

| Aspect | Mirror value |
|---|---|
| Stream read | backwards from `road_ptr − 2` (`walk_ptr--` after each read) |
| Initial heading | `−car_heading` |
| X[0] | `car_lateral sar 3` (not negated) |
| Initial values | `top_sy = cached_top_sy = cut_sy = 0x11`, `min_ol_sy = 0x1E`, `span_min = 0xF0` |
| Loop end | `bp == 0x32` (rows 1..24); `mirror_rows_done` = bp each pass while `row_limit == 0` |
| Projection | proj_y_mirror / proj_x_mirror; `W = road_halfwidth_q4[i] >> 1`, then the same W5 formula |
| Off-screen cut | when `dx <= 0xF0` (instead of ≤0): cut_x = 0xE6 |
| Arrays | as in §3.2 |

### 4.5 interp_edge_span (0x3A37)

This is literal. `bh`, `ch`, `bl` and `cl` are **8-bit**, and `<=` on them is a **signed byte** compare.
Each call writes exactly `n` words starting at `dst`.

```c
void interp_edge_span(s16 a, s16 b, u8 n, s16 *dst) {  // AX=a, BX=b, CL=DL=n
    s16 d = b - a; u16 cnt = n; s8 bh; u8 ch, bl, cl = n;
    if (d < 0) {
        s16 lim = span_min; d = -d; bl = (u8)d;
        if (d > (s16)cl) {                         // steep
            bh = 0; ch = bl >> 1;
            for (;;) {
                a--; if (a < lim) goto fill;
                bh += cl; if (bh <= (s8)ch) continue;
                a++; *dst++ = a; if (--cnt == 0) return;
                bh -= bl; a--;                     // loop head decrements again
            }
        } else {                                   // shallow
            bh = 0; ch = cl >> 1;
            for (;;) {
                *dst++ = a; if (--cnt == 0) return;
                bh += bl; if (bh <= (s8)ch) continue;
                bh -= cl; a--; if (a >= lim) continue; else goto fill;
            }
        }
    fill: while (cnt--) *dst++ = lim; return;
    } else {
        s16 lim = span_max; bl = (u8)d;
        if (d > (s16)cl) {
            bh = 0; ch = bl >> 1;
            for (;;) {
                a++; if (a > lim) goto fill2;
                bh += cl; if (bh <= (s8)ch) continue;
                a--; *dst++ = a; if (--cnt == 0) return;
                bh -= bl; a++;
            }
        } else {
            bh = 0; ch = cl >> 1;
            for (;;) {
                *dst++ = a; if (--cnt == 0) return;
                bh += bl; if (bh <= (s8)ch) continue;
                bh -= cl; a++; if (a < lim) continue; else goto fill2;
            }
        }
    fill2: while (cnt--) *dst++ = lim; return;
    }
}
```

The steep case uses only the low byte of |d| (`bl`). Differences over 255 px behave oddly; reproduce as written.

### 4.6 Buffer primitives

Colour indices in comments are **buffer** indices 0–7. On screen they probably become `c|8` under
palette DS:00CC:

* 0 → 8 black (road)
* 1 → 9 dark grey (shoulders)
* 2 → 10 brown (right-hand ground)
* 4 → 12 light cyan (left-hand area)
* 7 → 15 white (dashes)

See Open question 1.

Buffer pixel colour = bit0 plane0 (`cur_target.plane[0]`, CS:5A66) | bit1 plane1 (5A68) | bit2 plane2 (5A6A).
Row y starts at byte offset `rowtab[y] = 40·y`. Pixel k in a byte is bit `0x80>>k`.

```c
// 0x2E8B fill_span_to(end): sets pixels [pos .. end-1] in plane P; pos=(bytepos dx, bit span_bit)
bool fill_span_to(s16 end) {       // returns true when the row is complete (dx == 40)
    s16 e = end - 1; u16 eb, ebit;
    if (e < 0) return false;                 // 0x339E mirror: if (e < 0xF0) return false
    if (e >= 320) { eb = 39; ebit = 7; } else { eb = e sar 3; ebit = e & 7; }
    s16 cnt = eb - dx; if (cnt < 0) return false;
    u8 v = mask_left_from_bit[span_bit] | P[di];
    if (cnt - 1 >= 0) {                      // several bytes
        P[di++] = v; dx++; v = 0xFF;
        for (k = cnt - 1; k; k--) { P[di++] = 0xFF; dx++; }
    }
    P[di] = v & mask_right_to_bit[ebit];     // NB: last byte is assigned, not ORed
    ebit++; if (ebit == 8) { di++; dx++; ebit = 0; }
    span_bit = ebit;
    return dx == 40;
}

void fill_road_scanlines_main(void) {        // 0x2DEE
    (u8)min_ol_sy = (u8)(min_ol_sy << 1);    // byte doubling, may wrap
    for (si = 2*top_sy; si != 0xDE; si += 2) {        // scanlines top_sy..110
        di = rowtab[si/2]; dx = 0; span_bit = 0; P = plane2;
        if ((s16)si > (s16)min_ol_sy && min_ol < span_ol[si/2]) {
            if (fill_span_to(min_ol)) continue; P = plane1;
        }
        if (fill_span_to(span_ol[si/2])) continue;       // colour 4 (or 2 after min_ol)
        P = plane0; if (fill_span_to(span_l[si/2])) continue;   // shoulder, colour 1
        s16 rr = span_r[si/2]; if (rr >= 320) continue;          // road surface stays colour 0
        di += (rr sar 3) - dx; dx = rr sar 3; span_bit = rr & 7;
        P = plane0; if (fill_span_to(span_or[si/2])) continue;  // shoulder, colour 1
        P = plane1; fill_span_to(320);                           // right side, colour 2
    }
}
```

`fill_road_scanlines_mirror` (0x3306) is the same over `si = 2*top_sy_m .. 0x22`, with
`di = rowtab[si/2 + 0x1B] + 0x1E`, `dx = 0x1E` and the mirror span arrays.

```c
void fill_scenery_above_road(void) {         // 0x2EDC, rows 0x13 .. top_sy-1, word-wide (16 px)
    s16 k = (cut_x + 0x20) sar 4;            // words of colour 4 on the left
    for (y = 0x13; y != top_sy; y++) {
        u16 *p = rowtab[y]; int words = (y >= 0x1B && y <= 0x2C) ? 15 : 20;  // leave mirror area
        if (k <= 0)        fill16(plane1, p, words);                // all colour 2
        else if (k >= 20)  fill16(plane2, p, words);                // all colour 4
        else if (words == 15) { if (k >= 15) fill16(plane2,p,15); else { fill16(plane2,p,k); fill16(plane1,p+2k,15-k); } }
        else { fill16(plane2,p,k); fill16(plane1,p+2k,20-k); }
    }
}
void draw_mirror_background(void) {          // 0x33FB
    select_road_buffer(); clip = {x0:0x1E, x1:0x28, y0:0x1B, y1:0x2C}; fill_clip_rect(8);
    s16 k = ((cut_x_m + 0x10) sar 3) - 0x1E;  // bytes of colour 4
    for (y = 0x1B; y != top_sy_m + 0x1B; y++) {
        p = rowtab[y] + 0x1E;
        if (k <= 0) fill8(plane1,p,10); else if (k >= 10) fill8(plane2,p,10);
        else { fill8(plane2,p,k); fill8(plane1,p+k,10-k); }
    }
}
```

### 4.7 draw_road_main (0x28C5): objects and deferred draw list

A **frame** is pushed on the CPU stack. It is drawn later by the pop loop (LIFO, so rows pushed
first, the nearest, are drawn last):

```
frame  = {clip_y1, clip_xbytes, and_sprite, x, y, or_sprite, x, y}
         -> set clip.x1 = clip_xbytes, clip.y1 = clip_y1; blit_and(and_sprite,x,y); blit_or(or_sprite,x,y)
frame2 = {0xFFFE, or_sprite, x, y}   -> blit_or only (clip unchanged from the previous frame)
end    = {0xFFFF}
```

For a pair at table entry `e`, the **image is `e`** (OR) and the **mask is `e+1`** (AND).
Blits subtract the sprite hotspot. The clip x0 and y0 stay at 0 and 0x13.

```c
void draw_road_main(void) {
    fill_road_scanlines_main();
    crest = 0x6F; clip = {x0:0, x1:0x28, y0:0x13, y1:0x6F};
    dash = dash_phase; xclip_px = 320; xclip_b = 40;
    push(END);
    bp = 2;
    do {
        i = bp/2;
        s = road_halfwidth_q4[i] >> 4; if (s >= 31) s = 31; obj_scale = s;
        q4 = (s >> 1) & 0xFC;                               // 0,4,8,12 -> scale index s>>3
        if (bp == cut_row) {
            s16 t = (cut_x + 0x20) sar 3;
            if ((u16)t > 40) t = (t > 40) ? 40 : 0;           // negative -> 0
            xclip_b = t; xclip_px = t * 8;
        }
        u8 y = sy_[i];
        if (y < crest) {
            crest = y; clip.y1 = y;
            if (!(dash & 4) && (u16)cx[i] < xclip_px)        // centre-line dash pixel
                OR colour 7 at (cx[i], y);                   // bit set in plane2, plane1, plane0
        }
        if (!(dash & 0x0F) && (u16)ol[i] < xclip_px)           // pole every 16 units, left shoulder
            push_frame(crest, xclip_b, AND XROADA[2 + q4/4], OR XROADA[6 + q4/4], ol[i], (u8)(y - s));
        if (bp < 0x20 && bp <= cut_row) {                     // right-side scenery, immediate XOR
            u16 pe = roadside_pattern[(u8)(dash << 1) & 0x1E];
            u8 type = pe, cnt = pe >> 8;
            if (type < 6 && (u16)or[i] < 320) {
                s16 yy = y; if (cnt) yy -= (u8)(s >> 1) * cnt;
                blit_xor(XROADA[10 + 4*type + q4/4], or[i], yy);   // clip.y1 = current crest
            }
        }
        u8 t = (obj[i] & 0x3F) - 2;
        if (t <= 6) {                                         // signs 2..8
            s16 x = (obj[i] & 0x80) ? l[i] : r[i];
            if ((u16)x < xclip_px) {
                u16 yy = (u8)y - s;                             // 16-bit
                push_frame2(OR XROADA[97 + q4/4], x, yy);        // post, drawn after the sign
                u16 e = 41 + 8*t + (s & 0xF8)/4;                 // entry k: sign image, k+1 mask
                push_frame(crest, xclip_b, AND XROADA[e+1], OR XROADA[e], x, yy);
            }
        }
        for (j = 0; j < 10; j++) {                            // traffic
            slot = &r_traffic_slots[j]; if (slot->pos == 0) continue;
            s16 rr = (slot->pos - r_road_ptr) * 2;
            bool hit = (rr == bp && r_subpos <= slot->sub) || (rr + 2 == bp && r_subpos > slot->sub);
            if (!hit) continue;
            u16 off = traffic_scale_main[i] + slot->type;     // byte offset in XROADB/C table
            s16 x = (cx[i] + (j < 5 ? l[i] : r[i])) sar 1;
            if ((u16)x >= xclip_px) continue;
            u16 yy = y, cy = crest; if (bp == 2) { yy = 0x76; cy = 0x6F; }
            push_frame(cy, xclip_b, AND TAB1173[off + 4], OR TAB1173[off], x, yy);
        }
        if (r_cop_state != 0 && r_cop_state != 7) {           // police car ahead
            s16 rr = (r_cop_pos - r_road_ptr) * 2;
            bool hit = (rr == bp && r_subpos >= r_cop_sub) || (rr + 2 == bp && r_subpos < r_cop_sub);
            if (hit) {
                u16 x = ((u16)(r[i] + cx[i]) >> 1) - ((u16)(r_cop_lane * (r[i] - cx[i])) >> 4);
                if ((s16)x <= (s16)xclip_px) {
                    u16 row = bp;
                    if (r_cop_state != 3 && (s16)(cop_row_smooth - bp) <= 2 && (s16)(cop_row_smooth - bp) >= -2) row = cop_row_smooth;
                    else cop_row_smooth = bp;
                    u16 e = 0x132B + traffic_scale_main[row/2];     // cpr* pair
                    u16 yy = word(DS:1B73+bp), cy = crest; if (bp == 2) { yy = 0x76; cy = 0x6F; }
                    if (e == 0x134B) push_frame(cy, xclip_b, AND copm, OR copb, x, yy);
                    if (!(tick_count & 8)) push_frame(cy, xclip_b, AND [e+0x2C], OR [e+0x28], x, yy); // clr* lights
                    push_frame(cy, xclip_b, AND [e+4], OR [e], x, yy);
                }
            }
        }
        // hazard slot 12 (DS:0A0D): immediate OR, no sub-unit test
        if ((hz.pos - r_road_ptr) * 2 == bp) {
            u8 type = hz.w6 & 0xFF, lane = hz.w6 >> 8;
            u16 dx = (u16)(r[i] - cx[i]) >> 2;
            u16 x = (dx >> 1) + dx * lane + cx[i];
            if (x < xclip_px) blit_or(XROADA_ENTRY(0x1133 + q4 + type), x, word(DS:1B73+bp));
        }
        if ((u16)cut_x < 320 && bp == cut_row) {                // cliff face where road bends away
            s16 yy = (s16)cut_sy < 0x75 ? cut_sy : 0x75;
            push_frame(crest, xclip_b, AND clfa, OR clfo, cut_x, yy);
        }
        dash++; bp += 2;
    } while ((s16)bp < (s16)row_limit_main);

    if (bp == 0x50) {                                  // whole draw distance visible: one far car per lane
        tr = top_row;
        for (j = r_traffic_count_l - 1; j >= 0; j--) {   // slots at 09AD
            if ((s16)(slot[j].pos - r_road_ptr) < 0x27) continue;
            s16 x = (cx[tr/2] + l[tr/2]) sar 1;
            if ((u16)x < xclip_px) push_frame(crest, xclip_b, AND TAB1173[slot[j].type+4], OR TAB1173[slot[j].type], x, (u8)sy_[39]);
            break;
        }
        same for r_traffic_count_r with slots at 09D5 and r[tr/2];
    }
    pop_and_draw_frames();      // clip.x1/y1 left at the last frame's values
}
```

Details verified in the disassembly:
* Police hit test: `rr==bp` draws when `r_subpos < cop_sub` is **false**, i.e. `jl` skips.
  Precisely: bp match needs `!(r_subpos < cop_sub)`; bp−2 match needs `r_subpos < cop_sub`.
  The traffic test is the reverse (`jg`).
* `push_frame` y for police and hazards reads a **word** at DS:1B73+bp. The odd byte is always 0.
* Scenery XOR sprites and hazards draw with clip.x1 = 0x28 and clip.y1 = the crest at that moment.
  They are drawn immediately, before all deferred frames.
* Sprites use the hotspot-relative blit.

**draw_road_mirror (0x2F7A)** differences:

| Aspect | Mirror behaviour |
|---|---|
| Clip | x0 0x1E, x1 0x28, y0 0x1B, y1 = 0x11+0x1B |
| Counters | `crest = 0x11`; `dash = dash_phase − 2`, **decremented** per row |
| Scale | `s = min(W[i+1] >> 5, 31)` |
| X-clip at cut row | `t = (cut_x_m + 0x10) sar 3` (same clamp) |
| Crest | `clip.y1 = y + 0x1B`; centre pixel only if `0xF0 <= cx <= xclip_px` (signed), at row `y + 0x1B` |
| Poles | only if `0xF0 <= ol < xclip_px` (signed); y = `(u8)(y − s) + 0x1B` |
| Rocks/scenery | not drawn |
| Signs | `x = side ? l : r`, `0xF0 <= x < xclip_px` (signed). **One** frame: AND `XROADA[41 + (s & 0xF8)/4 + 1]` (the type-0 mask at that scale, whatever the sign type), then OR post `pst[q]`. The sign image itself is never drawn. y = `y − s + 0x1B` |
| Traffic | `rr = −(pos − r_road_ptr)*2`; `rr==bp` needs `r_subpos >= sub`; `rr+2==bp` needs `r_subpos < sub`. off = `traffic_scale_mirror[i] + type`, then `+0xC8` for j<5 (front→rear table), `−0xC8` for j≥5. yy = `sy+0x1B`. No bp==2 special case |
| Police | `rr = (r_road_ptr − r_cop_pos)*2`; `rr==bp` needs `r_subpos <= cop_sub`; `rr+2==bp` needs `r_subpos > cop_sub`. x formula as main, signed `jg` reject. Uses and updates `cop_row_smooth` (shared). e = `0x1303 + traffic_scale_mirror[row/2]` (cop0/1/2 front); lights `[e+0x50]/[e+0x54]` when `!(tick&8)`; y = `word(1E7F+bp) + 0x1B` |
| Hazards | none |
| Horizon cliff | if `0xF0 <= cut_x_m < 320` and bp == cut_row_m: AND `mcfa`, OR `mcfo` at `(cut_x_m, min(cut_sy_m, 15) + 0x1B)` |
| Loop end | `bp < row_limit_mirror` |
| Pop loop | no 0xFFFE frames; `clip.y1 = popped + 0x1B` |

### 4.8 Overlays, present, dashboard

```c
void draw_buffer_overlays(void) {          // 0x349D (target = road buffer, default clip)
    select_road_buffer();
    blit_and_own(CAR.mirr);                                   // mirror frame cut-out
    if (cop_state == 6 && ticket_flag == 0) blit_replace_own(XROADA.tick);
    if (drive_state == 2) {
        if (stage_index != 4) { set_text_attr(3,0); print_centered(" Pulling into the gas station... ", 0x50); }
        else if (b_0938 != 1) { set_text_attr(3,0); print_centered(" Pulling into the dealership... ", 0x50); }
    }
}
void present_road_buffer(void) {           // 0x3AF7
    select_screen(); clip.y1 = 0x6F;       // screen clip: x 0..40 bytes, y0 0x13 (set in 0x1DC0)
    blit_replace_own(road_buf_sprite);     // 320x112 3-plane buffer at (0,0) -> rows 0x13..0x6E
}

void draw_dashboard_dynamic(void) {        // 0x35C6, target = screen
    // radar detector
    SPR r = CAR.radb;
    if (tick_count & 8) {
        r = CAR.rad0;
        if (r_slot11.pos != 0) { s16 d = r_slot11.pos - 1 - r_road_ptr;
            if (d >= 0) { sound_tick(DS:0B0F); r = CAR_ENTRY(0x13C3 + ((d >> 2) & 0xFC)); } }  // rad5,rad4,...
    }
    blit_replace_own(r);
    // steering wheel pose: XOR toggles over the centred wheel in 'dash'
    u8 st = steer > 0 ? 0 : (steer == 0 ? 1 : 2);
    if (st != wheel_state) {
        if (((st | wheel_state) & 1) == 0) st = 1;               // never jump 0<->2 in one frame
        u16 idx = ((st | wheel_state) & 2) * 2;                  // 0 -> whl1, 4 -> whl3
        wheel_state = st;
        select_screen(); blit_xor_own(CAR_ENTRY(0x13DF + idx));
    }
    // wheel marker ('dot') on a 90 px radius
    u16 a = (steer < 0 ? -steer : steer); int neg = steer < 0;
    u8 k = (u8)((u16)(a << 2) >> 8); if ((s8)k >= 0x3C) k = 0x3C;  // signed byte compare
    s16 mx = wheel_sin90[k]; if (!neg) mx = -mx;                 // [k==60 reads cos[0]=90]
    mx += car_wheel_x;                                           // DS:269B
    u16 my = car_wheel_y; (u8)my -= wheel_cos90[k];              // DS:269D, low byte only
    if (marker_saved) blit_replace(&marker_save_sprite, marker_save_x, marker_save_y);
    marker_save_x = (mx - 2) & 0xFFF8; marker_save_y = my - 2;
    grab_screen(&marker_save_sprite, marker_save_x, marker_save_y);
    blit_and(CAR.dota, mx, my); blit_or(CAR.dot, mx, my);
    marker_saved = 1;
    if (redraw_0923 != 1) return;
    redraw_0923 = 0;
    select_target(inst_buf); blit_replace(CAR.inst, 0, 0);
    if (car_needle_gauges == 1) {                                // DS:27FB
        u16 v = speed_w >> 8; if (units_mode == 2) { v -= 0x12; if ((s16)v < 0) v = 0; }
        if ((s16)v >= 0xA0) v = 0xA0;
        u16 tip = car_speedo_tip[v];                             // DS:2809, lo=x hi=y
        draw_line(speedo_px, speedo_py, (tip & 0xFF) - inst_x, (tip >> 8) - inst_y, 0xFFFF);
        u16 rr = rpm < car_rev_limit ? rpm : car_rev_limit;      // unsigned
        tip = car_tach_tip[rr >> 6];                             // DS:29B7
        draw_line(tach_px, tach_py, (tip & 0xFF) - inst_x, (tip >> 8) - inst_y, 0xFFFF);
        blit_and_own(CAR_ENTRY(0x13A3 + 8*wheel_state));         // ina1/2/3
        blit_or_own (CAR_ENTRY(0x139F + 8*wheel_state));         // inl1/2/3
    } else {                                                     // digital cluster
        u8 v = speed_w >> 8; if (v >= 0x56) v = 0x56;
        clip.y0 = inst_h - ((u8)(v*2) / 5 + 1);  blit_or_own(DIG.spdo);  clip.y0 = 0;   // bar
        u16 rr = rpm >= 0x1C20 ? 0x1C20 : rpm;
        u8 q = (u8)((rr >> 3) / 100); u8 h = q >> 1;
        if ((q & 1) || h == 0 || h == 4) { clip.x1 = inst_wbytes + h - 4; blit_or_own(DIG.tach); }
        else blit_or_own(DIG_ENTRY(0x1413 + 4*h));               // tac1..tac3
        clip.x1 = inst_wbytes;
        u8 sp = speed_w >> 8;
        if (sp >= 100) { draw_digit(1, 0x4C); sp -= 100; draw_digit(sp/10, 0x52); }
        else if (sp/10) draw_digit(sp/10, 0x52);
        draw_digit(sp%10, 0x58);
        u16 rp = rpm >= 10000 ? 9999 : rpm; u8 hh = rp / 100;
        if (hh/10) draw_digit(hh/10, 0xB9); draw_digit(hh%10, 0xBF);
    }
    select_screen(); blit_replace(inst_buf_sprite, inst_x, inst_y);
}
void draw_digit(u8 d, s16 x) { blit_or(DIG[d], x - inst_x, 0x20); }   // 0x38CD

void draw_gear_box(void) {                 // 0x351A
    if (gearbox_visible != gearbox_prev) {
        gearbox_prev = gearbox_visible;
        if (gearbox_visible != 1) goto closed;
        goto redraw;
    }
    if (gearbox_visible == 1) { if (redraw_0922 != 1) return; goto redraw; }
    if (gearbox_hide_delay == 0) return;
    if (--gearbox_hide_delay != 0) { if (redraw_0922 != 1) return; goto redraw; }
closed: select_screen(); blit_replace_own(CAR.gbo0); return;
redraw:
    redraw_0922 = 0; select_target(gbox_buf);
    blit_replace(CAR.gbox, 0, 0);
    blit_and(CAR.gnab, knob_x - gbox_x, knob_y - gbox_y);
    blit_or (CAR.gnob, knob_x - gbox_x, knob_y - gbox_y);   // NB: 0x4DF1 is called with sp already popped by 4, it reuses the same x,y
    select_screen(); blit_replace(gbox_buf_sprite, gbox_x, gbox_y);
}
```

### 4.9 Frame loop and end sequences (0x1DC0, 0x392C, 0x38EB)

```c
stage_init_road_ptr(); reset_car_state(); load_stage_resources();
select_screen(); set_target_clip(screen, 0, 0x28, 0x13, 200); fill_clip_rect(8);
blit_replace_own(CAR.dash); blit_replace_own(CAR.roof); tick_count = 0;
for (;;) {
    snapshot_sim_state(); project_road_main(); project_road_mirror();
    select_road_buffer(); fill_clip_rect(8);
    fill_scenery_above_road(); draw_road_main();
    draw_mirror_background(); draw_road_mirror(); draw_buffer_overlays();
    present_road_buffer(); draw_dashboard_dynamic(); draw_gear_box(); rng_stir();
    if (demo_mode && (s16)tick_count > 0x2D0) return -1;
    if (drive_state == 0) continue;
    if (drive_state == 1) return -1;
    if (drive_state == 2) { if (speed_w != 0) continue;
        sound_stop(); w_78EC = road_ptr - stage_ptr[stage_index] - 0x2D;
        if (stage_index == 4) dealership_ending(); return 1; }
    // crash
    sound_stop(); b_093C = 0; tick_count += 0xF0;
    snapshot_sim_state(); crash_windscreen_sequence();
    if (--lives_78E6 == 0) { blit_and_own(gvrm); blit_or_own(govr); wait_fire_button(); return 0; }
    reset_car_state(); queue_song(DS:0B05);
}
// the exits also restore int 0/int 8 and free the three buffers (game_flow / platform)

void crash_windscreen_sequence(void) {     // 0x392C: reuses last projection (no 0x2054/0x2478)
    select_road_buffer(); fill_clip_rect(8); fill_scenery_above_road(); draw_road_main();
    select_road_buffer();
    for (k = 1; k <= cnt[0]; k++) draw_line(p0.x, p0.y, pk.x, pk.y, 0xFFFF);    // set 0: star
    draw_mirror_background(); draw_road_mirror(); draw_buffer_overlays(); present_road_buffer();
    for (set = 1; set < 7; set++) {
        select_road_buffer();
        for each segment: draw_line(x1,y1,x2,y2,0xFFFF);           // lines accumulate in the buffer
        draw_mirror_background(); draw_road_mirror(); draw_buffer_overlays(); present_road_buffer();
    }
    if (lives_78E6 != 1) wait_fire_button();
}
void dealership_ending(void) {             // 0x38EB
    b_0938 = 1; select_screen(); blit_replace_own(XROADA.deal); blit_and_own(CAR.mirr);
    wait_fire_button(); blit_replace_own(XROADA.note);
    while (read_input() & 0x10) ;  wait_fire_button();
}
```

Quirk: `fill_road_scanlines_main` doubles `min_ol_sy` in place. The crash sequence calls it a second
time without re-projecting, so the value is doubled twice there.

---------------------------------------------------------------------------------------------

## 5. Hardware / DOS dependencies

| Dependency | Where | SDL3 replacement |
|---|---|---|
| EGA planar VRAM A000 via blitters (func-select AND/OR/XOR/replace) | all blits via platform | 320×200 indexed framebuffer; implement AND/OR/XOR/replace on 4-bit indices |
| RAM 3-plane road buffer (40×112 bytes/plane), direct byte writes to plane segments CS:[5A66/68/6A] | 0x2DEE, 0x2EDC, 0x28C5 centre pixel, 0x3306, 0x33FB | 320×112 u8 index buffer (bits 0–2); spans OR bits into planes |
| Copy of buffer to VRAM (replace, planes 0–2 per plane map 01 02 04 00) | 0x3AF7 | copy rows 19–110 into the framebuffer. **Plane 3** in the window comes from the initial `fill(8)` of rows 19–199 and is probably not touched by the blit (see Open questions) |
| int 0 (divide error) vector → DS:1423 returns AX=0xFFFF, skips the 2-byte `div` | 0x23F2, 0x2421, 0x282C, 0x285B | `div32_16` saturating helper (§4) |
| int 8 timer ISR CS:3B1F runs the simulation | installed in 0x4792 | run simulation ticks on a fixed-rate timer thread or loop, and snapshot at frame start |
| Keyboard/joystick poll 0x5C24 | 0x1F7B, 0x38EB | SDL input |
| PC speaker song DS:0B0F (radar beep), 0x8A08 stop | 0x35C6, 0x1DC0 | audio module |
| Text print 0x9507 into buffer | 0x349D | bitmap font (platform) |

No CRTC start-address page flipping and no vertical-retrace wait were found in this range.

---------------------------------------------------------------------------------------------

## 6. Timing

* **The render loop is not frame-locked.** Each pass repaints the road window completely and copies it.
  The frame rate is whatever the CPU allows.
* **The simulation runs in int 8** (the tick rate is in the simulation/platform specs).
  * `tick_count` (DS:80A4) is incremented there.
  * The radar detector and police light bar flash on `tick_count & 8`, i.e. they toggle every 8 ticks.
  * The demo ends when `tick_count > 720`.
* **These are per-frame, not per-tick:**
  * the centre-line dash phase shift (it follows `dash_phase` changes from the sim);
  * the gear-box close delay (`gearbox_hide_delay` = 13 frames);
  * the crash animation (7 redraws with no delay);
  * `rng_stir`, called once per frame.
* **Race protection:** `snapshot_sim_state` copies the ISR-updated fields. A port that runs simulation
  and render in one thread should keep this order: run ticks, snapshot, render.
* **Projection caching** (`first_changed_row`) only saves work. Its output equals a full recompute,
  except where stale span entries survive for cached rows. That matches a full recompute as long as
  those rows are unchanged. A port can recompute everything, provided `row_limit` and the tracking
  variables follow the same rules.

---------------------------------------------------------------------------------------------

## 7. Open questions

1. **Road-window colours (plane 3).** The buffer holds indices 0–7. The screen was pre-filled with
   index 8 (plane 3 set) in rows 19–199. If `0x5DE2`'s replace path leaves unmapped planes alone (the
   decompile suggests it only programs map-mask bits from the plane map), the visible index is `c|8`.

   Palette names below use the game palette DS:00CC:

   | Buffer index c | Used for | If plane 3 is kept (c\|8) | If plane 3 is cleared (c) |
   |---|---|---|---|
   | 0 | road surface | 8 black | 0 black |
   | 1 | shoulders | 9 dark grey | 1 blue |
   | 2 | right-hand ground | 10 brown | 2 green |
   | 4 | left-hand area (beside the road and above it, left of cut_x) | 12 light cyan | 4 red |
   | 7 | centre dashes | 15 white | 7 yellow |

   The `c|8` column reads naturally as sea or sky on the left, a brown cliff side on the right, a black
   road, dark-grey shoulders and white dashes, so it is the likely one. Confirm in the platform blitter
   or with a screenshot. Sprites carry their own colours.
2. The `& 0xFFFC` on the sprite's own x in the `*_own` blits, and how the blitters treat x in pixels vs
   bytes: platform spec.
3. Slot fields +4 and the exact role of slot 10 (DS:09FD) are simulation-owned. Slot 11 (0A05) is read
   only as the "cop ahead" radar source.
4. `units_mode` (DS:790A==2) subtracts 18 from the speedo index. Its meaning (a different car model or
   km/h?) is not resolved.
5. Mirror signs draw only the mask of the type-0 sign and the post. This looks like a bug but is
   faithful to the code.
6. `cut_top_sy` (19BF/19C1) and `mirror_rows_done` (1435) are written but never read in this range.
7. The high bytes of DS:19CE/19CA (next to the byte variables `top_sy` and `prev_row_limit`) are assumed
   to be 0. They are read as words in a few compares.
