# drive_scene — Test Drive (Amiga) `td`, overlay 2: the driving picture

Porting spec for everything the Amiga drive **draws**: the Road Drawer task and frame composition, the road
renderer (main view and mirror), road-side objects, traffic and police scaling and ordering, sky (clouds) and
bugs on the windscreen, the cockpit overlays, the gauges (hardware sprites and the Corvette's digital
cluster), the gear knob, the copper palette split, the crash sequence and the ending picture.
State updates (speed, steering, traffic AI, police, collisions) belong to `drive_sim`; the stage loop
0x1C900 belongs to `game_flow`. DOS counterpart: `port/spec/scene_render.md` (cited as *DOS §n*).

Conventions: `port/RE_GUIDE.md` and `port/amiga/README.md`. Functions are image addresses, globals `D:xxxx`
(offset into the data hunk; A4-relative displacement d is `D:(0x7FFE+d)`). `int` is 16-bit, big-endian.
16.16 longs are written `x.l`; their high word (the integer part) is `HI(x)`, which is also what a
`move.w D:xxxx` reads. Everything below was re-derived from `tools/amigaidx.py … dis`; the Ghidra decompile
(`port/amiga/decomp/td.c`) drops most register arguments of this overlay's hand-written assembly and several
stack arguments of the C parts, and it misses a store in 0x1D484. Confidence: **verified** unless marked.

-----------------------------------------------------------------------------------------------------------

## 1. Overview

### 1.1 Picture layout

The drive uses the two graphics.library Views of the game (A = `D:293E`, B = `D:2950`, 320×200, 5 planes,
see `title_select.md` §display model) as a **double buffer**: `D:24C8` = back view (drawn), `D:24CE` = front
view (shown); `show_view` 0x1C62E swaps them. There is no separate road buffer as on DOS: everything is drawn
straight into the back view's bitplanes with the blitter.

| Rows | What | Redrawn |
|---|---|---|
| 0..116 (0x00..0x74) | **Road window**: cleared to colour 4 (sky) every frame, road, scenery, traffic, clouds, bugs. The **mirror** is a second road view in the rectangle x 0xF0..0x13F, rows 0x1A..0x2A. The cockpit shapes `roof` (0..16), `hood` (≈106..116), `post` (A-pillar) and `mirr` (mirror frame, at 224,24) are blitted over it every frame. | every frame |
| 117..199 (0x75..) | **Dashboard**: the `<car>Dash` ILBM, loaded once into both views. Only the steering wheel (`whl*` XOR), the gear gate (`gbox` XOR) and the Corvette's digital cluster are blitted here. | on change, per buffer |
| sprites | **Hardware sprites**: 0/1 tachometer needle, 2/3 speedometer needle (analog cars), 4..7 gear knob `gnob` (two attached pairs), sprite 7 also the 4×4 steering-wheel marker dot. | CPU writes into sprite data |

A user copper list (`0x24D8A`) loads the sprite pointers at the top and switches the 32 colour registers at
line 0x75 from the **road palette** `D:19CE` (upper part, `LoadRGB4`) to the **dash palette** `D:24D2`
(the `<car>Dash` CMAP, captured once).

Road-window colours (road palette `D:19CE`): 4 = sky and left-hand side (`0x3BF`), 6 = ground right of the
road, left dips and the horizon cliff area (`0x743`), 12 = shoulder (`0xAAA`), 13 = road (`0x999`),
5 = centre line (`0xEE2`), 28 = lane marks on wide roads (`0xFFF`), 28 = windscreen cracks.

### 1.2 Tasks and pipeline

The drive runs in **two exec tasks**:

* **Main task** (the game's own task, raised to priority 4 by 0x24E94): the stage loop 0x1C900
  (`game_flow`) runs the simulation (`drive_sim`, 0x20CB0 …) and moves the gear-knob sprites (0x1CD72); it
  waits with `WaitTOF` until 5 VBL have passed since the previous iteration.
* **"Road Drawer" task** (priority −1, 2000-byte stack, entry 0x24F9A → 0x1D484), created per stage by
  0x24E94: an endless loop that renders one frame into the back view and shows it. It runs whenever the main
  task waits. It is paused by `D:24AE` (busy-waiting and acknowledging with `D:2844 = 1`).

Per render frame, 0x1D392 takes a snapshot of the sim state under `Forbid`/`Permit` (speed, road position,
lateral, steering, the 12 traffic slots), then draws with the blitter owned (`OwnBlitter`).

```
0x24F9A road_drawer_entry (A4 from 0x24F96)
 └─ 0x1D484 road_drawer_main  (loop forever)
     ├─ while (D:24AE) D:2844 = 1              ; paused
     ├─ 0x1D392 render_frame(back view)
     │   ├─ target = back bitmap; Forbid; snapshot; Permit; OwnBlitter
     │   ├─ 0x1D9CC compose_road_window
     │   │   ├─ 0x2090C detect_pitch_bump        (result unused: dead consumer)
     │   │   ├─ 0x1D36C set_main_window_clip, 0x10D14 blit_init, 0x1D9C6 queue_reset
     │   │   ├─ 0x1D97C clear_window                          ; colour 4
     │   │   ├─ 0x1DA14 draw_road_main
     │   │   │   ├─ 0x1DA72 init_row_scale
     │   │   │   ├─ 0x1E314 walk_road_rows ×40  (per row:)
     │   │   │   │    0x1D32A road_record_at, slot cars 0x1E0CC/0x1E078/0x1E19E, hazards 0x1E2F8,
     │   │   │   │    0x1E5C6 row_widths, signs/posts (queue), 0x1E216, scenery 0x1E230/0x1E276/0x1E2B0,
     │   │   │   │    slot cars 0x1E062/0x1E08E/0x1E0A4/0x1E0B8, 0x20128 fill_road_row ─► 0x20096,
     │   │   │   │    0x1E65C lane marks, 0x2031C centre line ─► 0x1D27E/0x1D2C2,
     │   │   │   │    0x1DD56 y step, 0x2472A x step, 0x246FA heading, 0x1DD96 slope, 0x1DD34 scale
     │   │   │   └─ 0x202A8 fill_left_ground
     │   │   ├─ 0x1EDAE (empty stub)
     │   │   ├─ 0x1E758 draw_clouds ─► 0x1EBA8, 0x1EAE0 ─► 0x1EB5E, 0x1E784
     │   │   ├─ 0x20456 draw_object_queue ─► 0x2034E cliff, 0x206E8/0x205CE/0x20740/0x20562/0x20546/0x20526/0x20580
     │   │   ├─ 0x1E7D2 draw_bugs
     │   │   ├─ 0x1DAA2 draw_road_mirror ─► 0x1DAF6, 0x1D97C, 0x1E314 ×30
     │   │   ├─ 0x1EDAE, 0x20456 (mirror objects)
     │   │   ├─ 0x1EBC4 draw_cockpit_overlays ─► hood/roof/post/mirr, 0x1EC94 radar, 0x1ED06 wheel
     │   │   ├─ 0x203E0 toggle_gear_box
     │   │   └─ 0x1E63A draw_ticket
     │   ├─ blit_wait; DisownBlitter
     │   └─ 0x20AF4 update_gauges ─► 0x1F2EA draw_needle ×2 | 0x2097C draw_digital_cluster ─► 0x20A88
     ├─ if D:0B2E: Text "Pulling into the gas station/dealership..." at (0x30,0x55), pens 8/0
     ├─ 0x1C62E show_view(back)                ; LoadView + swap
     ├─ WaitTOF
     └─ D:28D6++                               ; frame counter (never read)

main task, per sim tick (every ≥5 VBL):  0x1CD72 update_knob_sprites; sim (drive_sim) incl.
                                         0x247B2 update_wheel_marker (sprite 7) via 0x24924.
stage entry/exit: 0x24ACA stage_display_setup, 0x24CE4 stage_display_shutdown (both from 0x1C900)
crash: 0x1FBD8 crash_windscreen_sequence;  ending: 0x1CF76 dealership_ending
```

### 1.3 How the road is drawn

Unlike DOS (fixed per-row depth table, projection with a divide and an atan table, crest culling by
scanline spans), the Amiga renderer is an **incremental fixed-point walker**:

* It walks 40 road units forward (30 backwards for the mirror) from the car's unit. Each row has a
  **scale** `s` (`D:0B62`, u16 fraction of 1): 0xFFFF…0xE8F5 for the nearest row depending on the
  sub-unit position, then ×0xE8F5/65536 (0.910) per row.
* Screen position of the row: `y` (16.16, `D:0B66`) starts at 160 below the window and decreases by
  `8·s + slope·s/4` per row; `x` (road centre, 16.16, `D:0B6A`) moves by `sin(heading)·80·s` plus a lateral
  parallax term. Heading integrates the record's curve (/8 degrees per row, clamped ±90°), slope integrates
  its pitch (clamped per row by `D:0B38`).
* Half-widths come from the record's first byte (hi nibble left, lo nibble right, table 0x1E45A:
  0x140..0x500): **the DOS "flag" byte is a road-width code** (the road data are byte-identical to DOS).
* Each row fills the scanlines between the previous row's y and its own y (a trapezoid, edges interpolated)
  with one-row blits on single planes, clipped to the **crest** `D:0B74` (smallest y so far). The walk stops
  when the crest reaches the top of the clip.
* Objects are pushed into a queue (x, y clamped to the crest, code, scale) near→far, and drawn far→near
  (LIFO) after the road, each clipped at its own base line.

-----------------------------------------------------------------------------------------------------------

## 2. Function table

Owned by this spec. "DOS equivalent" = DOS address and name (`port/symbols.csv`) of the closest DOS
routine; *part of* means the Amiga function covers only part of it, *+* that it merges several.

| address | name | signature | purpose | DOS equivalent | confidence |
|---|---|---|---|---|---|
| 0x1D27E | plot_pixel_set | asm: d0 x, d1 y; plane = `D:0BEC[D:0B60/4]` | set one pixel if 0≤x<320 and 10≤y<`D:0B74` | – | verified |
| 0x1D2C2 | plot_pixel_clear | as 0x1D27E | clear one pixel, same bounds | – | verified |
| 0x1D306 | mul_scale | asm: d0.l = (s16)d0.w × `D:0B62` (u16), signed 32-bit | scale a signed road coordinate | – | verified |
| 0x1D31A | clamp_word | asm: `*(s16*)a3` clamped to [d0.w, d1.w] | helper | – | verified |
| 0x1D32A | road_record_at | asm: d7 unit → a2 = record (4 bytes) | stream byte → record; record 0 outside the stage | part of 0x2054 (stream read) | verified |
| 0x1D36C | set_main_window_clip | asm | `D:0B74 = 0x75`; clip y 0..0x75, x 0..0x140; `D:0DDA = 0x75` | 0x3ACE select_road_buffer | verified |
| 0x1D392 | render_frame | `void(View *back)` | snapshot sim state, compose road window, gauges | part of 0x1DC0 run_stage (loop body) + 0x2013 snapshot_sim_state | verified |
| 0x1D484 | road_drawer_main | task body, never returns | pause handshake, render, "Pulling into…" text, show, WaitTOF | 0x349D draw_buffer_overlays (text) + 0x3AF7 present_road_buffer | verified |
| 0x1D97C | clear_window | asm | fill clip rect rows [`D:0380`,`D:0B74`) with colour 4 | 0x74F4 fill_clip_rect / 0x33FB | verified |
| 0x1D9C6 | queue_reset | asm | `D:0F80 = 0` | – | verified |
| 0x1D9CC | compose_road_window | asm, saves all | draw order of the road window (§4.2) | part of 0x1DC0 | verified |
| 0x1DA14 | draw_road_main | asm | main view: init, walk 40 rows, left-ground fill | 0x2054 project_road_main + 0x28C5 draw_road_main | verified |
| 0x1DA72 | init_row_scale | asm | first-row scale and sub-unit weight from the position fraction | – | verified |
| 0x1DAA2 | draw_road_mirror | asm | mirror: clip, clear, walk 30 rows backwards | 0x2478 project_road_mirror + 0x2F7A draw_road_mirror + 0x33FB | verified |
| 0x1DAF6 | set_mirror_window_clip | asm | clip x 0xF0..0x140, y 0x1A..0x2B; `D:0B74 = 0x2B` | part of 0x33FB | verified |
| 0x1DD34 | row_scale_step | asm | `s *= 0xE8F5/65536`; clear sub-unit weight | – | verified |
| 0x1DD56 | row_y_step | asm | crest update; `y -= 8s + slope·s/4` | – | verified |
| 0x1DD96 | row_slope_step | asm | slope += pitch × f(s); per-row clamp | – | verified |
| 0x1E062 | queue_slot_car_0 | asm: d7 unit, d1 y | same-direction slot 0 (`trk`, code 0x18) | part of 0x28C5 (traffic) | verified |
| 0x1E078 | queue_slot_car_1 | asm | slot 1 (`x7r`, 0x19), centre-relative | part of 0x28C5 | verified |
| 0x1E08E | queue_slot_car_2 | asm | slot 2 (`vnr`, 0x1A) | part of 0x28C5 | verified |
| 0x1E0A4 | queue_slot_car_3 | asm | slot 3 (`sdr`, 0x1B) | part of 0x28C5 | verified |
| 0x1E0B8 | queue_slot_car_4 | asm | slot 4 (`sdr`, 0x1C) | part of 0x28C5 | verified |
| 0x1E0CC | queue_police_car | asm | slot 5, police (`cpr`, 0x1D); pull-over lateral | part of 0x28C5 (police) | verified |
| 0x1E19E | queue_oncoming_cars | asm | 5 oncoming slots (`rig sed vnf sed sed`, 0x10..0x14) | part of 0x28C5 | verified |
| 0x1E216 | queue_post | asm | code 0x41 (`pst`) at the left edge every 16 units | 0x28C5 poles (DOS: `pal/pol`) | verified |
| 0x1E230 | queue_scenery_wed | asm | table 0x1E47A → code 0x30 (`wed`) | 0x28C5 roadside XOR scenery | verified |
| 0x1E276 | queue_scenery_rock | asm | table 0x1E4BA → code 0x31 (`rck`) | 0x28C5 roadside scenery | verified |
| 0x1E2B0 | queue_scenery_lin | asm | table 0x1E4FA → code 0x32 (`lin`) | 0x28C5 roadside scenery | verified |
| 0x1E2F8 | queue_hazard | asm | road object 0x20..0x23 → queue, x from lane bits | 0x28C5 hazard slot 12 | verified |
| 0x1E314 | walk_road_rows | asm, saves all | the per-row loop (§4.3) | loops of 0x2054 + 0x28C5 | verified |
| 0x1E5C6 | row_widths | asm | half-widths from record byte 0 | DOS W[i] table (fixed) | verified |
| 0x1E63A | draw_ticket | asm | `tick` when `D:0D74 ≥ 0x1E` | part of 0x349D | verified |
| 0x1E65C | draw_lane_marks | asm | wide road: flag `D:0D98`, lane dash at cx+0x1C0·s | – | verified |
| 0x1E758 | draw_clouds | asm | heading delta → cloud motion, draw 4 clouds | – (Amiga only) | verified |
| 0x1E784 | blit_clouds | asm | `cldA cldB cld0 cld1` above the horizon | – | verified |
| 0x1E7D2 | draw_bugs | asm | bugs hitting the windscreen (list at 0x1E89A) | – (Amiga only) | verified |
| 0x1EAE0 | move_clouds | asm: d0 = 4·Δheading | parallax + drift, wrap ±400 | – | verified |
| 0x1EB5E | wrap_cloud_x | asm: d0 | wrap to [−400, 400] | – | verified |
| 0x1EB78 | init_clouds | `void(void)` | start positions | – | verified |
| 0x1EBA8 | wrap_angle_delta | asm: d0 − d1 → [−180, 180] | helper | – | verified |
| 0x1EBC4 | draw_cockpit_overlays | asm | `hood roof post mirr`, radar, wheel | 0x349D (mirr) + roof blit of 0x1DC0 | verified |
| 0x1EC94 | draw_radar_detector | asm | blink cycle, `rad0..5` XOR, beep | part of 0x35C6 draw_dashboard_dynamic | verified |
| 0x1ED06 | draw_steering_wheel | asm | 5 poses, XOR `whl0..3`, per-buffer state | part of 0x35C6 | verified |
| 0x1ED64 | xor_wheel_pose | asm: d0 pose | XOR `whl[p]` (p≠2) | part of 0x35C6 | verified |
| 0x1ED8A | reset_wheel_state | `void(int keep)` | pose memory + marker cache | part of 0x1F4E stage_init_road_ptr | verified |
| 0x1EDAE | window_rect_stub | asm | computes the clear-rect arguments and does nothing | – | verified |
| 0x1EF14 | cop_move_long | `void(UCopList*, long reg, long value)` | CMove hi, CBump, CMove lo, CBump | – | verified |
| 0x1EF76 | spr_pos_word | `int(int h, int v0, int v1, int att)` | SPRxPOS value | – | verified |
| 0x1EF90 | spr_ctl_word | same | SPRxCTL value | – | verified |
| 0x1EFD4 | cop_sprite_pos | `void(UCopList*, h, v0, v1, att, n)` | CMove SPRnPOS/SPRnCTL | – | verified |
| 0x1F05A | sprite_set_segment | `void(int word, int h, int v0, int v1, int att, int n)` | write a segment's POS/CTL words | – | verified |
| 0x1F0DC | sprite_add_segment | `void(int h, int v0, int v1, int att, int n)` | append a segment to sprite n | – | verified |
| 0x1F12C | pack_shape_to_sprite | `void(Shape*, u16 *dst, int planes, int col, Shape *mask, int mcol)` | copy planes (masked) into DATA/DATB words | – | verified |
| 0x1F27E | shape_to_sprite_segment | `void(Shape*, int n, int planes, int col)` | pack into the next segment of sprite n | – | verified |
| 0x1F2EA | draw_needle | `void(int x, int y, int which)` | Draw a needle into a 32×51 bitmap, pack to sprites | part of 0x35C6 (draw_line needles) | verified |
| 0x1F582 | position_wheel_marker | `void(int x, int y)` | sprite 7 segment 0 at (x, y) | part of 0x35C6 (dot) | verified |
| 0x1F5BA | sprites_init | `void(void)` | allocate sprite data, needle/knob/dot segments, SPREN | part of 0x4792 | verified |
| 0x1F99A | sprites_free | `void(void)` | WaitTOF, SPREN off, free | – | verified |
| 0x1F9FE | shake_dash_sprites | `void(void)` | re-position needle and knob sprites; only caller is dead code | – | verified |
| 0x1FAD4 | ucop_sprite_pointers | `void(UCopList*)` | CWait(−10,0); per sprite POS/CTL and SPRxPT | – | verified |
| 0x1FB4A | ucop_palette_split | `void(UCopList*, u16 *pal, int line)` | CWait(line−1, `D:0DCC`); 32 × COLORxx; end | – | verified |
| 0x1FBD8 | crash_windscreen_sequence | `void(void)` | 7 steps of cracks with the cockpit re-overlaid | 0x392C crash_windscreen_sequence | verified |
| 0x1FDF4 | redraw_cockpit_back | `void(void)` | target = back view; 0x1EBC4 | – | verified |
| 0x1FE38 | min16 | `int(int a, int b)` | | – | verified |
| 0x1FE54 | clamp_rgb4 | `int(int c, int level)` | each 4-bit gun min(gun, level) | – | verified |
| 0x1FEAE | fade_out_palette | `void(int delay, u16 *pal2, int line)` | 16-step fade of front ViewPort (+ lower palette) | – (also used by gas station 0x14902) | verified |
| 0x20096 | fill_row_span | asm: a0 plane, d4 row·40, d1 x0, d2 x1 | one-row blit D=A (overwrites whole words: bug 5, fixed by default) | 0x2E8B fill_span_to | verified |
| 0x20128 | fill_road_row | asm | trapezoid between previous and current row: road, shoulders, right ground | 0x2DEE fill_road_scanlines_main | verified |
| 0x202A8 | fill_left_ground | asm | colour 6 in left-hand dips | part of 0x2DEE (min_ol logic) | verified |
| 0x2031C | draw_centre_line | asm | 2-pixel centre line, dashed unless wide | part of 0x28C5 (centre dash) | verified |
| 0x2034E | draw_horizon_cliff | asm | colour-6 block + `clf0` right of the cliff line | part of 0x28C5 / 0x2EDC | verified |
| 0x203E0 | toggle_gear_box | asm | XOR `gbox` when this buffer's state differs | part of 0x351A draw_gear_box | verified |
| 0x20410 | queue_object | asm: d0 x, d1 y, d2 code | push (x, min(y,crest), code, scale), max 199 | push_frame in 0x28C5 | verified |
| 0x20456 | draw_object_queue | asm | pop LIFO, clip at base, dispatch; cliff | pop_and_draw_frames in 0x28C5 | verified |
| 0x20526 | draw_obj_lin | asm | code 0x32 | – | verified |
| 0x20546 | draw_obj_rock | asm | code 0x31 | – | verified |
| 0x20562 | draw_obj_wed | asm | code 0x30 | – | verified |
| 0x20580 | draw_obj_post | asm | code 0x41 | – | verified |
| 0x205A6 | scale_index5 | asm: d4 scale → 0,4..16 | 5 sizes | DOS obj_scale | verified |
| 0x205BC | scale_index4 | asm: d4 scale → 0,4,8,12 | 4 sizes | – | verified |
| 0x205CE | draw_obj_traffic | asm | codes 0x10..0x1D, size hysteresis, police lights | traffic/police frames of 0x28C5 | verified |
| 0x206A0 | draw_obj_sign_mirror | asm | pole + sign back (`rsg`) | mirror signs of 0x2F7A | verified |
| 0x206E8 | draw_obj_sign | asm | codes 2..0xF: pole + sign | sign frames of 0x28C5 | verified |
| 0x20740 | draw_obj_hazard | asm | codes 0x20..0x23 | hazard blit of 0x28C5 | verified |
| 0x2090C | detect_pitch_bump | asm | `D:283C = −1` when pitch changes by ≥3 | – | verified |
| 0x20940 | dash_shake_update | asm, **no caller** | would shake needle/knob sprites by `D:2840` | – | verified (dead) |
| 0x2097C | draw_digital_cluster | asm | Corvette: `inst`, bars, digits, wheel overlays | digital part of 0x35C6 | verified |
| 0x20A88 | draw_number | asm: d0 value, a2 digit shapes, a3 positions | up to 3 XOR digits | 0x38CD draw_digit | verified |
| 0x20AF4 | update_gauges | asm | wheel-dependent masks; needles or digital cluster on change | gauge part of 0x35C6 | verified |
| 0x1CD72 | update_knob_sprites | `void(void)` | glide gear knob sprites, close delay, hide | 0x351A draw_gear_box | verified |
| 0x1CF76 | dealership_ending | `void(void)` | EndGame picture over the dash, `note` | 0x38EB dealership_ending | verified |
| 0x246FA | row_heading_step | asm | heading += curve/8 (sub-unit weighted), clamp ±90 | part of 0x2054 | verified |
| 0x2472A | row_x_step | asm | x += sin(heading)·80·s, lateral parallax | part of 0x2054 | verified |
| 0x247B2 | update_wheel_marker | asm | angle → marker position → sprite 7 | marker part of 0x35C6 | verified |
| 0x24ACA | stage_display_setup | `void(int car)` | load shapes/car/dash, palette, first frames, start task | 0x4792 stage_enter_install_isr (+0x10E2 car load) | verified |
| 0x24CE4 | stage_display_shutdown | `void(int keep)` | stop task, sprites off, fade, free | exit path of 0x1DC0 | verified |
| 0x24D68 | remake_view | `void(View*)` | MakeVPort + MrgCop | – | verified |
| 0x24D8A | setup_drive_copper | `void(View*)` | capture dash palette (once), user copper list, road palette | 0x5D palette setup | verified |
| 0x24E52 | fade_out_drive | `void(void)` | 0x1FEAE(1, dash palette, 0x75), rebuild both views | – | verified |
| 0x24E94 | start_road_drawer | `void(void)` | AddTask "Road Drawer" (paused), main task pri 4 | 0x4792 int 8 hook (conceptually) | verified |
| 0x24F3A | stop_road_drawer | `void(void)` | pause, wait ack, RemTask, free, pri 0 | – | verified |
| 0x24F9A | road_drawer_entry | task initPC | A4 from 0x24F96; 0x1D484 | – | verified |
| 0x24FAA | load_cockpit_shapes | `void(void)` | Dash.Shp lookups + masks | 0x4792 CAR table @1383 | verified |
| 0x253E6 | load_road_shapes | `void(void)` | 0x24FAA + Road.Shp lookups + masks | 0x4792 XROADA/B/C tables | verified |
| 0x25740 | load_scenery_shapes | `void(void)` | rocks, oil, potholes, gravel | 0x4792 XROADA k101–116 | verified |
| 0x259D8 | load_sign_shapes | `void(void)` | signs, sign backs, poles | 0x4792 XROADA k41–100 | verified |
| 0x2627C | load_traffic_shapes | `void(void)` | traffic, police, light bars | 0x4792 XROADB/XROADC | verified |

Functions this spec calls that belong elsewhere:

| address | name used here | spec | notes |
|---|---|---|---|
| 0x1C900 | drive_stage | see game_flow | stage loop; calls 0x24ACA, 0x1FBD8, 0x24CE4, 0x1CF76, 0x1CD72; GAME OVER blit of `game` (`D:2766`/`D:276A`) |
| 0x1C62E | show_view | see title_select | LoadView; `D:24CE` = v, `D:24C8` = other, RastPorts `D:24C0`/`D:287A` |
| 0x1CCF6 | stage_reset_objects | see drive_sim | also clears the bug list (256 words at 0x1E89A) |
| 0x1DB36 0x1DC2E 0x1DCDC 0x1DDEA 0x1E53A 0x1E6A6 0x1E720 0x1E73A 0x1EC1A 0x1EDCE 0x1EE76 0x2076C–0x20826 0x20CB0 0x20D68 0x20E70 0x2481C 0x2484C 0x24924 0x2498E 0x249CC 0x24A02 0x24A04 0x24AA8 | – | see drive_sim | sim; 0x1EDCE/0x1EE76 set the knob target `D:24B6/D:24B2` and `D:0B30/1`; 0x20D68 copies the car record; 0x20E70 selects the stage stream |
| 0x26C50 | radar_beep | see platform_audio | |
| 0x10D14 0x10D44 0x10D72 0x10DBE 0x10E12 0x10E1C 0x10E26 0x10E3A 0x10E58 0x10E78 0x10E88 0x10FA4 0x10FBC 0x110C4 0x111E6 0x11432 | blit_init, blit_wait, blit_rect_clear, blit_rect_set, shape_pos, sub_hotspot, set_target, … | see platform_video | semantics used here: §4.0 |
| 0x10BA8 0x10C5A 0x15472 0x149D2 0x149E8 0x15904 0x1591A 0x159FA | pool_alloc, make_mask, find_shape, load_file, load_file_chip, alloc, alloc_chip, free | see platform_video | FORMATS.md §File loading |
| 0x1063A 0x1574E 0x1580C 0x14984 | ilbm_to_view, view_clear, view_copy(src,dst), draw_shape_to_view | see platform_video | |
| 0x1530E 0x12056 0x1205E 0x12108 0x12146 | rand16, abs16, abs32, sin16_16, cos_deg | see drive_sim / platform_video | 0x12108: sin of a 16.16 angle, interpolated table 0x1216C (sin·65536) |
| 0x10462 0x153E4 0x1544E 0x117E8 | poll_input, fire_pressed, break_pressed, set_my_task_pri | see platform_video | |
| 0x178D0 0x17944 0x17892 0x17966 0x175EA 0x176DC | Forbid, Permit, AddTask, RemTask, Delay, CopyMem | glue | |
| 0x179DC 0x179F4 0x17A06 0x17A18 0x17A20 0x17A4A 0x17A62 0x17A74 0x17A98 0x17AB6 0x17AC4 0x17AD6 0x17AEE 0x17B24 0x17B34 0x17B64 0x17B92 0x17B9A 0x17880 | CBump, CMove, CWait, DisownBlitter, Draw, FreeVPortCopLists, InitBitMap, InitRastPort, LoadRGB4, MakeVPort, Move, MrgCop, OwnBlitter, SetAPen, SetBPen, Text, WaitBlit, WaitTOF, AllocMem | graphics/exec glue | LVOs from the glue at 0x17880–0x17BAE |

-----------------------------------------------------------------------------------------------------------

## 3. Globals

### 3.1 Inputs from the simulation (read here; updated in drive_sim)

| D: | name | type | meaning | written by | read here by | DOS |
|---|---|---|---|---|---|---|
| 28A6 | car_speed | s32 16.16 | speed; HI = mph shown | sim | 0x1D392 (→289E), 0x1E7D2, 0x20AF4, 0x2097C | DS:0927 |
| 28AE | road_pos | s32 16.16 | HI = road unit, LO = fraction | sim | 0x1D392 (→28BA) | DS:0906 + DS:0912 |
| 2896 | car_lateral | s32 16.16 | lateral position, init 0x640000 (100) | sim, 0x24ACA | 0x1D392 (→289A) | DS:0910 |
| 28AA | steer_angle | s32 16.16 | steering | sim | 0x1D392 (→28A2), 0x247B2 | DS:0914 |
| 191A | rpm | u16 | engine rpm | sim | 0x20AF4, 0x2097C | DS:091B |
| 19B4 | view_heading | s32 16.16 deg | car heading relative to road | sim 0x24A04 | 0x2472A | DS:090C |
| 28C6 | world_heading | s32 16.16 deg | 0..359, integrates curves (0x1DCDC) | sim, 0x24ACA (0) | 0x1E758 | – |
| 0C6E | same_dir_slots | 6 × s32 16.16 | unit (HI) of same-direction traffic; slot 5 police; 0 = empty | sim | 0x1D392 (→0D40) | DS:096D |
| 0CF2 | oncoming_slots | 5 × s32 | unit of oncoming traffic | sim | 0x1D392 (→0D58) | DS:0945 |
| 0CAA | slot_slide | 6 × s16 (stride 4) | lateral slide of same-direction slots 0..4 (sim adds 0x38; render decays it) | sim 0x1DDEA, **0x1E124** | 0x1E124 | – |
| 0CBE | police_slide | s16 | slide of slot 5 (negative, sim subtracts 0x38) | sim, **0x1E0CC** | 0x1E0CC | – |
| 0D74 | cop_stop_timer | s16 | ≥0x1E: ticket shown | sim | 0x1E63A | DS:0A23 = 6 |
| 0D78 | cop_seq_timer | u16 | police pull-over sequence counter | sim | 0x1E0CC | – |
| 0D7A | cop_mode | u16 | ≥10 pulling over; 0xF stopped (brake lights) | sim | 0x1E0CC, 0x205CE | DS:0A23 |
| 0DBE | radar_level | s32 16.16 | HI = detector level 0..; 0 none | sim 0x1EC1A | 0x1EC94 | – |
| 0DC4 | radar_on_time | u16 | lit phase length, 0x32 VBL | data, sim | 0x1EC94 | – |
| 0B2E | pulling_in | u16 | 1 when within 0x50 units of the end | 0x1C900 | 0x1D484 | DS:0929 = 2 |
| 24CC | stage_index | u16 | 0..4 | game_flow | 0x1D484 | DS:7B16 |
| 1984 | stage_end_unit | s16 | index of 0xFF − 45 | 0x20E70, **0x1D32A** | 0x1D32A | – |
| 1986 / 198A | road_stream / road_records | ptr | stage byte stream / 110 × 4-byte records (0x20F08) | 0x20E70 | 0x1D32A | DS:6361 / DS:2B70 |
| 0B30 / 0B31 | gearbox_wanted[2] | u8 per buffer | 0xFF = gear gate shown in buffer 0/1 | sim, poll_input ('D' key via `D:0B34`), VBL server | 0x203E0, 0x1CD72, 0x1CF76 | DS:08BE |
| 24B6 / 24B2 | knob_target_x/y | s16 | knob sprite target (gate pos + (0x80,0x2C) − gnob hot spot) | sim 0x1EDCE/0x1EE76 | 0x1CD72 | DS:0A81/0A83 |
| 24BA | knob_close_delay | u16 | frames before the gate closes (7) | sim | 0x1CD72 | DS:091F (13) |
| 26FC | shift_in_progress | u16 | cleared when the knob arrives | sim | 0x1CD72 | – |
| 0B34 | gearbox_hold | u16 | 'D' key toggle: keep the gate | poll_input | 0x1CD72 | DS:08BE toggle |
| 1924.. | car record copy | | 1926 tach clamp (+002), 1930/1932/1934 marker x/y/r (+00C/+00E/+010), 193A gate table (+020), 194E needle flag (+16C), 1950 speed digit xy (+16E), 1954/1956/195A speed bar dir/x0/scale (+17A/+17C/+180), 195C/196C digit prefixes (+182/+32C), 1960 tach digit xy (+31C), 1964/1966/196A tach bar dir/x0/scale (+324/+326/+32A), 1970–1973 needle pivots (+16E..+171), 1974/1976 speed box (+172/+174), 1978/197A tach box (+176/+178), 197C speed tips (+17A), 1980 tach tips (+328) | 0x20D68 | gauges | DS:268F.. |

### 3.2 Render state (owned here)

| D: | name | type | meaning | written by | read by |
|---|---|---|---|---|---|
| 289E / 28BA / 289A / 28A2 | r_speed / r_road_pos / r_lateral / r_steer | s32 | frame snapshots (Forbid) of 28A6/28AE/2896/28AA | 0x1D392 | walker, gauges |
| 0D40 / 0D58 | r_same_dir / r_oncoming | 6 × s32 each | snapshots of 0C6E / 0CF2[0..5] | 0x1D392 | 0x1E062.., 0x1E19E |
| 2836 | back_index | u16 | 0 = drawing into view A, 1 = B | 0x1D392 | 0x203E0, 0x20AF4 |
| 2840 | sprite_shake | s16 | subtracted from sprite v0/v1 in 0x1F05A; set 0 each frame (±1 only in dead code) | 0x1D392, 0x20964/0x20970 | 0x1F05A |
| 2842 | horizon_shake | s16 | front ViewPort DyOffset, 0 if outside ±10; added to the start y. DyOffset is only ever cleared, so 0 | 0x1D392 | 0x1DA14 |
| 2844 | drawer_paused_ack | u16 | 1 while the task is paused, 0 while drawing | 0x1D484, 0x24E94 | 0x24F3A |
| 24AE | drawer_pause | u16 | 1 = pause the Road Drawer | 0x24E94, 0x24F3A, 0x1C900 (0) | 0x1D484 |
| 28E6 / 28EA | drawer_stack / drawer_task | ptr | 2000-byte stack, 0x5C-byte Task | 0x24E94 | 0x24F3A |
| 28D6 | drawer_frames | u32 | frames rendered (write-only) | 0x1D484, 0x1C900 | – |
| 0B62 | row_scale | u16 | scale of the current row (1 = 0x10000) | walker | all queue/fill code |
| 0B64 | row_scale2 | u16 | scaled like 0B62, never read | 0x1DA72, 0x1DD34 | – |
| 0B66 | row_y | s32 16.16 | screen y of the current row | walker | |
| 0B6A | row_cx | s32 16.16 | screen x of the road centre | walker | |
| 0B6E | heading_acc | s32 16.16 deg | clamped ±0x5A | walker | 0x2472A |
| 0B72 | slope_acc | s16 | clamped per row by table D:0B38 | walker | 0x1DD56 |
| 0B74 | crest_y | s16 | smallest row y so far = clip bottom for road and objects | 0x1D36C, 0x1DAF6, 0x1DD56 | fills, queue, pixels |
| 0B76 | row_index | u16 | 0..39 | walker | |
| 0D82 | first_row_weight | u16 | sub-unit weight (0..0x7FFF) of row 0; 0 afterwards | 0x1DA72, 0x1DD34 | steps |
| 0F7E | mirror_flag | s16 | 0 main, −1 mirror | 0x1DA14, 0x1DAA2 | walker, dispatch |
| 0D84 / 0D7C / 0D7E | row_centre / slot_base_x / slot_base_lat | s16 | per-row bases for slot cars | walker | slot routines |
| 0D8C / 0D8E | half_left / half_right | u16 | half-widths of the row | 0x1E5C6 | walker, 0x1E65C |
| 0D90 / 0D92 | last_left / last_right | u16 | previous row's widths (for code 0xFF) | 0x1E5C6 | 0x1E5C6 |
| 0D94 / 0D96 | car_half_left / car_half_right | u16 | widths at row 0 (car's unit) — read by the sim (road-edge tests) | 0x1E5C6 | sim 0x1DB36, 0x1E6A6, 0x249CC |
| 0D98 | wide_road | s16 | −1 when right half > 0x224 | 0x1E65C | 0x2031C |
| 0C00 / 0C02 | right_edge / left_edge | s16 | edges of the current row (px) | walker | 0x20128 |
| 0CC2 | slot_lateral | 6 × s16 (stride 4) | lateral of same-dir slots — **read by the sim** for collisions | 0x1E142 | sim 0x1DDEA |
| 0D28 | oncoming_lateral | 5 × s16 (stride 4) | set to −0xE0 when drawn — read by the sim | 0x1E19E | sim |
| 0DDC / 0DDE / 0DE0 | prev_left / prev_right / prev_y | s16 | previous row for the trapezoid fill | 0x20128 | 0x20128 |
| 0DE2 / 0DE4 | step_left / step_right | s16 | per-scanline edge steps (stale when n = 1: bug 6, fixed by default) | 0x20128 | 0x20128 |
| 0DE6 | left_shoulder_x | s16 [row+1] | per scanline, left shoulder x | 0x20128 | 0x202A8 |
| 0F78 / 0F7A | max_left_x / max_left_row | s16 | max of 0DE6 (init 0xD8F0) | 0x1DA14, 0x20128 | 0x202A8 |
| 0F7C | shoulder_plane4 | u16 | cleared each row, never set: shoulders always on plane 3 | 0x20128 | 0x20128 |
| 0DD2 / 0DD4 / 0DD6 / 0DD8 | cliff_x / cliff_y / cliff_scale / min_row_y | s16/u16 | leftmost right-shoulder x, its y, its scale; init 20000 | 0x1DA14, 0x1DAA2, 0x20128 | 0x2034E, 0x20456 |
| 0DDA | window_bottom | s16 | 0x75 (main) / 0x2B (mirror) | 0x1D36C, 0x1DAF6 | 0x202A8, 0x2034E, 0x205CE |
| 0B60 | pixel_plane_off | u16 | plane × 4 for 0x1D27E/0x1D2C2 | 0x1E65C, 0x2031C | pixel routines |
| 0F80 | queue_count | s16 | objects queued | 0x20410, 0x20456, 0x1D9C6 | |
| 0F82 / 1112 / 12A2 / 1432 | queue_x / queue_y / queue_code / queue_scale | 199 × s16 each | the object queue | 0x20410 | 0x20456 |
| 15C2 | traffic_size[14] | u16 (stride 4) | last size index per traffic code (hysteresis), shared by both views | 0x205CE | 0x205CE |
| 15FA / 15FC | traffic_scale_tmp / police_flash | u16 / u8 | | 0x205CE | 0x205CE |
| 0D9E | cloud_heading | s16 | heading at the last cloud update | 0x1E758, 0x1EB78 | 0x1E758 |
| 0DA0 / 0DA4 / 0DA8 / 0DAC | cloud_x[4] | s32 16.16 | cloud positions (HI) | 0x1EB78, 0x1EAE0 | 0x1E784 |
| 0DB0 / 0DB4 / 0DB8 | cloud_x[4..6] | s16 | set by 0x1EB78, used only by dead code 0x1EA9A | 0x1EB78 | – |
| 0x1E89A (code) | bug_list | u16 count + 30 × {s16 x, s16 y, Shape *img, Shape *mask, u16 ttl} | in overlay code, writable | 0x1E7D2, 0x1CCF6 | 0x1E7D2 |
| 0DC6 / 0DC8 | radar_dark / radar_time | u16 / u32 | blink phase and its start tick (`D:03D8`) | 0x1EC94 | 0x1EC94 |
| 0C4A / 0C4C | wheel_pose_other / wheel_pose_here | s16 | pose 0..4 drawn in the other / this buffer (swapped each frame); 0xFE0C = unknown | 0x1ED06, 0x1ED8A | 0x1ED06, 0x20AF4 |
| 0B32 / 0B33 | gearbox_shown[2] | u8 | XOR state of `gbox` in buffer 0/1 | 0x203E0, 0x24ACA, 0x1FBD8 | 0x203E0, 0x1CD72 |
| 24B8 / 24B4 | knob_x / knob_y | s16 | knob sprite position (glides toward 24B6/24B2) | 0x1CD72, 0x1CF76 | 0x1CD72, 0x1F9FE |
| 2832 / 2834 | knob_shown_x / knob_shown_y | s16 | last position written to the sprites | 0x1CD72, 0x1C900 | 0x1CD72 |
| 284C | knob_visible | u16 | knob sprites on screen | 0x1CD72 | 0x1CD72, 0x1F9FE |
| 1904 | gauge_pose | u16 | wheel pose the gauge masks were chosen for | 0x20AF4 | 0x20AF4 |
| 1902 / 1900 | needle_speed / needle_rpm | u16 | analog cache; 1900 is never written here (always redraws) | 0x20AF4, 0x1C900, 0x1CF76 | 0x20AF4 |
| 1906 / 190A | digital_speed[2] / digital_rpm[2] | u16 per buffer | digital cache | 0x20AF4 | 0x20AF4 |
| 2726 / 2756 | tach_overlay / _mask | Shape* | `tcm[pose]` | 0x20AF4, 0x24FAA | 0x1F2EA, 0x2097C |
| 272A / 275A | speed_overlay / _mask | Shape* | `spm[pose]` | 0x20AF4, 0x24FAA | 0x1F2EA, 0x2097C |
| 2E46 | sprite_data[8] | u16* | chip block of 0x7D0 bytes, sprite n at +250·n | 0x1F5BA | sprite code, 0x1FAD4 |
| 292E | sprite_next_word[8] | u16 | next free word in each sprite's data | 0x1F5BA, 0x1F0DC, 0x1F27E | |
| 284E / 2850 | needle_seg / dot_seg | u16 | segment word offsets (0) | 0x1F5BA | 0x1F2EA, 0x1F582 |
| 2852 / 2854 | speed_pair_shift / tach_pair_shift | u16 | 0 or 32: left needle sprite moved right | 0x1F2EA | 0x1F2EA, 0x1F9FE |
| 28F6 / 28F8 / 28FA / 28FC | knob_seg[4] | u16 | knob segment offsets in sprites 4..7 (10) | 0x1F5BA | 0x1CD72, 0x1CF76, 0x1F9FE |
| 28DA / 28DE / 28E2 | needle_shape / needle_rp / needle_bm | ptr | 16-byte shape header + 0xCC bytes (32×51×1); RastPort; BitMap | 0x1F5BA | 0x1F2EA |
| 199E / 1998 | marker_cache / marker_angle | s32 | last steering·2; 0x87654321 = invalid | 0x247B2, 0x1ED8A | 0x247B2 |
| 199C | near_rows_flag | s16 | x-step helper: −1 while rows are below y 0x7D | 0x2472A | 0x2472A |
| 283C / 283A / 283E | pitch_bump_flag / bump_state / last_pitch | s16/s16/u8 | pitch-change detector; consumer is dead code | 0x2090C | 0x20940 (dead) |
| 24D2 | dash_palette[32] | u16 | CMAP of `<car>Dash`, captured once per game | 0x24D8A | 0x24D8A, 0x24E52, 0x1CF76, gas station |
| 2846 | dash_palette_valid | u16 | | 0x24D8A, 0x1C900 (0) | 0x24D8A |
| 19CE | road_palette[32] | u16 (data) | §4.12 | – | 0x24D8A |
| 19CA | loading_palette[2] | u16 (data) | `0x000, 0xD04` | – | 0x24ACA |
| 0DCC | palette_split_h | u16 (data) = 100 | CWait horizontal position | – | 0x1FB4A, 0x1FEAE |
| 0B38 | slope_clamp[40] | s8 (data) | §4.12 | – | 0x1DD96 |
| 0C04 / 0C26 | first_mask[17] / last_mask[17] | u16 (data) | `0xFFFF>>n` / `~(0xFFFF>>n)` | – | 0x20096 |
| 1646 / 1654 | crack_count[7] / crack_ptr[7] | u16 / ptr (data) | crash cracks, §4.12 (same values as DOS) | – | 0x1FBD8 |
| 276E | mask_pool | ptr | masks made by make_mask; 31000 bytes (5000 in the ending) | 0x24ACA, 0x1C900, 0x1CF76 | loaders |
| 27CE / 27D2 / 2548 | dash_shapes / road_shapes / car_record | ptr | `<car>Dash.Shp`, `Pics/Road.Shp`, `<car>.b` | 0x24ACA | loaders |
| 24BC | picture | ptr | last ILBM loaded (dash / EndGame / EndGame.Shp) | load_file | 0x24ACA, 0x1CF76 |
| 2508..2DFE | shape handles | Shape* | §4.11 | loaders | dispatch, overlays |

-----------------------------------------------------------------------------------------------------------

## 4. Pseudocode

Types: `u8 s8 u16 s16 u32 s32`. `mulu(a,b)` = `(u32)(u16)a * (u16)b`, `muls(a,b)` = `(s32)(s16)a * (s16)b`,
`HI(l)` = `(s16)(l >> 16)`. `asr` = arithmetic shift. Registers keep their 68000 widths: an operation marked
`.w` wraps at 16 bits and leaves the high word of the register unchanged.
`g_original_bugs` is the port's `--original-bugs` flag (not an Amiga global): its branch is the original
behaviour, the other the default fix (port/amiga/README.md, *Original bugs*; this spec owns bugs 2, 5 and 6).

### 4.0 Blitter primitives used here (platform_video; semantics needed by the port)

Target = the five plane pointers `D:0BEC..D:0BFC` (set by 0x10E26 from `BitMap.Planes`), 40 bytes per row.
Clip = `D:0380` top y, `D:0382` bottom y (exclusive), `D:0384` left x, `D:0386` right x (exclusive; the setter
0x10FBC rounds x0/x1 down to 16). Shapes are FORMATS.md §Shape (`+8/+A` = own position, `+4/+6` hot spot);
a pointer ≤ 0x32 is ignored. Masks are 1-plane shapes (OR of all planes) made by `make_mask` into `D:276E`.

The names below are this spec's; port/amiga/symbols.csv keeps platform_video's (the owner) and lists these as
aliases: blit_init = `blit_begin` 0x10D14, sub_hotspot = `shape_sub_hot`, set_target = `blit_set_dest` 0x10E26,
blit_cookie_aligned = `blit_shape_word_asm` 0x10E88, blit_cookie = `blit_shape_asm` 0x110C4, blit_xor =
`blit_shape_xor` 0x111E6, blit_xor_aligned = `blit_shape_xor_word` 0x11432, blit_rect_clear/set =
`blit_clear_rect`/`blit_fill_rect`, clip_full_screen = `set_clip_full` 0x10FA4. The semantics agree with
platform_video §4 (checked in the merge).

| call | semantics |
|---|---|
| `shape_pos(s)` 0x10E12 | d0,d1 = s→x, s→y (own position) |
| `sub_hotspot(s)` 0x10E1C | d0 −= s→hot_x, d1 −= s→hot_y |
| `blit_cookie_aligned(img, mask, x, y)` 0x10E88 | x rounded down to 16; D = mask·img + ¬mask·D on all 5 planes; no mask (ptr < 2000): copy (replace) |
| `blit_cookie(img, mask, x, y)` 0x110C4 | pixel-exact x (shifted); same minterms; no mask: opaque copy of the rectangle |
| `blit_xor(img, x, y)` 0x111E6 | pixel-exact XOR of the image planes into the target |
| `blit_xor_aligned(img, x, y)` 0x11432 | x rounded down to 16, XOR, right clip exact to the pixel |
| `blit_rect_clear/set(plane, x, y, wbytes, h)` 0x10D72/0x10DBE | whole words (x rounded down to 16) set to 0 / 0xFFFF |
| `fill_row_span` 0x20096 | see §4.4 — in the original **overwrites** its first/last words (bits outside the span become 0); README bug 5, fixed by default |

All clip against `D:0380..D:0386`; parts outside are skipped.

### 4.1 Stage display setup, Road Drawer task, shutdown

```c
void stage_display_setup(int car) {                       // 0x24ACA
    world_heading = 0; D:28CA = 0; car_lateral = 0x640000; steer_angle = 0; car_speed = 0; D:28B2 = 0;
    if (dash_shapes == 0) {                               // first stage of this car / after a full free
        view_clear(&viewA); view_clear(&viewB);           // 0x1574E: black colours, BltClear planes
        Move(&rpA, 100, 100); SetAPen(&rpA, 1); Text(&rpA, "Loading Game...", 15);
        LoadRGB4(viewA.vp, loading_palette /*D:19CA*/, 2); show_view(&viewA);
        road_shapes = load_file_chip("Pics/Road.Shp");
        car_record  = load_file(sprintf("%s.b", carpath[car] /*D:2E66[car]*/));
        copy_car_record();                                 // 0x20D68 (drive_sim)
        gearbox_shown[0] = gearbox_shown[1] = 0;
        dash_shapes = load_file_chip(sprintf("%sDash.Shp", carpath[car]));
        mask_pool = pool_alloc(0x7918);                    // 31000
        load_road_shapes();                                // 0x253E6 (includes 0x24FAA)
        picture = load_file(sprintf("%sDash", carpath[car]));
        sprites_init(); init_clouds(); reset_wheel_state(0);
        ilbm_to_view(picture, back);                       // dash picture into the back view
        setup_drive_copper(back); render_frame(back); show_view(back);
        ilbm_to_view(picture, back);                       // and into the other view
        free(picture);
    } else {                                               // shapes still loaded (after a crash/restart)
        sprites_init(); init_clouds(); reset_wheel_state(1);
        setup_drive_copper(back); render_frame(back); show_view(back);
    }
    setup_drive_copper(back); render_frame(back);          // second buffer
    start_road_drawer();
}

void start_road_drawer(void) {                            // 0x24E94
    *(long *)0x24F96 = A4;                                 // saved A4 for the task entry
    set_my_task_pri(4);                                    // 0x117E8: SetTaskPri(FindTask(0), 4)
    drawer_stack = alloc(0x7D0); drawer_task = alloc(0x5C);
    t->ln_Type = 1 /*NT_TASK*/; t->ln_Name = "Road Drawer"; t->ln_Pri = -1;
    t->tc_SPLower = drawer_stack; t->tc_SPUpper = t->tc_SPReg = drawer_stack + 0x7D0;
    drawer_paused_ack = 0; drawer_pause = 1;               // starts paused; 0x1C900 clears drawer_pause
    AddTask(t, road_drawer_entry /*0x24F9A*/, 0);
}
void road_drawer_entry(void) { A4 = *(long *)0x24F96; road_drawer_main(); drawer_paused_ack = -1; }

void road_drawer_main(void) {                             // 0x1D484
    for (;;) {
        while (drawer_pause) drawer_paused_ack = 1;       // busy wait (store dropped by Ghidra)
        drawer_paused_ack = 0;
        render_frame(back /*D:24C8*/);
        if (pulling_in) {
            SetAPen(back_rp /*D:287A*/, 8); SetBPen(back_rp, 0); Move(back_rp, 0x30, 0x55);
            if (stage_index < 4) Text(back_rp, "Pulling into the gas station...", 0x1F);
            else                 Text(back_rp, "Pulling into the dealership...", 0x1E);
        }
        show_view(back); WaitTOF(); drawer_frames++;
    }
}

void stop_road_drawer(void) {                             // 0x24F3A
    if (!drawer_task) return;
    drawer_pause = 1;
    while (drawer_paused_ack == 0) Delay(1);
    Forbid(); RemTask(drawer_task); free(drawer_task); drawer_task = 0;
    free(drawer_stack); drawer_stack = 0; set_my_task_pri(0); Permit();
}

void stage_display_shutdown(int keep) {                   // 0x24CE4 (1 after crash/stage end, 0 at exit)
    stop_road_drawer(); reset_wheel_state(1); sprites_free();
    viewA.vp->DyOffset = 0; viewB.vp->DyOffset = 0;
    fade_out_drive();
    if (!keep) { free(dash_shapes); free(road_shapes); free(mask_pool); free(car_record); /* each then 0 */ }
}
```

### 4.2 One frame

```c
void render_frame(View *v) {                              // 0x1D392
    sprite_shake = 0;
    horizon_shake = (v == back ? front : back)->vp->DyOffset;
    if (horizon_shake < -10 || horizon_shake > 10) horizon_shake = 0;
    set_target(v->vp->RasInfo->BitMap->Planes);
    back_index = (v != &viewA);
    Forbid();
    r_speed = car_speed; r_road_pos = road_pos; r_lateral = car_lateral; r_steer = steer_angle;
    for (i = 0; i < 6; i++) { r_same_dir[i] = same_dir_slots[i]; r_oncoming[i] = oncoming_slots[i]; }
    Permit();                                              // (i = 5 of 0CF2 reads the next variable)
    OwnBlitter(); compose_road_window(); blit_wait(); DisownBlitter();
    update_gauges();
}

void compose_road_window(void) {                          // 0x1D9CC, d7 = HI(r_road_pos)
    detect_pitch_bump();                                   // 0x2090C, see §4.8.6
    set_main_window_clip(); blit_init(); queue_count = 0;
    clear_window();
    draw_road_main();                                      // walk + fill + queue (main)
    /* 0x1EDAE: no effect */
    draw_clouds();
    draw_object_queue();
    draw_bugs();
    draw_road_mirror();                                    // clip, clear, walk + fill + queue (mirror)
    draw_object_queue();
    draw_cockpit_overlays();
    toggle_gear_box();
    draw_ticket();
}

void set_main_window_clip(void) { crest_y = 0x75; set_clip(0, 0x75, 0, 0x140); window_bottom = 0x75; }
void set_mirror_window_clip(void) {                       // 0x1DAF6
    crest_y = 0x2B; /* D:0B80[25] = 0xF0, D:0BB2[25] = 0x13C: write-only */
    set_clip(0x1A, 0x2B, 0xF0, 0x140); window_bottom = 0x2B;
}
void clear_window(void) {                                 // 0x1D97C: colour 4
    int x = D:0384, y = D:0380, wb = (u16)(D:0386 - x) >> 3, h = crest_y - y;
    if (h <= 0) return;
    blit_rect_clear(pl0,x,y,wb,h); blit_rect_clear(pl1,..); blit_rect_set(pl2,..);
    blit_rect_clear(pl3,..); blit_rect_clear(pl4,..);
}
```

### 4.3 The road walker

```c
void draw_road_main(void) {                               // 0x1DA14
    cliff_x = cliff_y = min_row_y = 20000; heading_acc = 0;
    row_y = (s32)(u16)(0xA0 + horizon_shake) << 16;         // add.w to the high word
    init_row_scale();
    row_cx = 0xA00000 - mul_scale(HI(r_lateral));
    mirror_flag = 0; max_left_x = (s16)0xD8F0; prev_y = 0x74;
    walk_road_rows(); fill_left_ground();
}
void init_row_scale(void) {                               // 0x1DA72
    row_scale = 0xFFFF; row_scale2 = 0xFFFF;
    u16 f = -(u16)LO(r_road_pos);                          // neg.w of the fraction
    first_row_weight = f >> 1; if (first_row_weight == 0) first_row_weight = 1;
    row_scale -= mulu(f, 0x170B) >> 16;
}
void draw_road_mirror(void) {                             // 0x1DAA2
    cliff_x = cliff_y = min_row_y = 20000; heading_acc = 0;
    row_y = 0x3E0000; row_scale = 0x5000;
    row_cx = (s32)(u16)(0x118 - ((s16)(HI(r_lateral) * 5) asr 4)) << 16;
    set_mirror_window_clip(); clear_window(); mirror_flag = -1;
    walk_road_rows();                                      // first_row_weight is 0 here
}

void walk_road_rows(void) {                               // 0x1E314; d7 = HI(r_road_pos) on entry
    row_index = 0; slope_acc = 0;
    int left = mirror_flag ? 0x1D : 0x27;                   // dbra: 30 / 40 rows
    for (;;) {
        u8 *rec = road_record_at(d7);                      // a2
        s16 obj = (s8)rec[3];                              // d3
        s16 x = HI(row_cx), y = HI(row_y);                 // d0, d1
        row_centre = slot_base_x = x; slot_base_lat = 0;
        queue_police_car(); queue_slot_car_1(); queue_oncoming_cars();
        if ((obj & 0x3F) >= 0x20 && (obj & 0x3F) <= 0x23) queue_hazard(x, y, obj);  // no row test
        row_widths(rec);
        x -= mulu(half_left, row_scale) >> 16; left_edge = x;
        if ((s8)obj >= (s8)0x82 && (s8)obj <= (s8)0x8F && row_index > 6)
            queue_object(x, y, obj & 0x7F);                // signs on the left
        queue_post(x, y);                                  // 0x1E216
        slot_base_lat = half_right;
        x = row_centre + (mulu(half_right, row_scale) >> 16);
        right_edge = slot_base_x = x;
        if (row_index <= 6) {                              // 0x1E3BE..0x1E3DC
            u32 p = (u32)(mirror_flag ? 0x2D6E : 0x9160) * half_right;     // mulu.w
            if (g_original_bugs) slot_base_x = (u16)p + row_centre;       // bug 2: low word (no swap)
            else                 slot_base_x = (u16)(p >> 16) + row_centre; // fixed: high word, as at 0x1E3B2
        }
        if ((u8)obj >= 2 && (u8)obj <= 0x0F && row_index > 6)
            queue_object(x, y, (u8)obj);                   // signs on the right
        queue_scenery_wed(x, y); queue_scenery_rock(x, y); queue_scenery_lin(x, y);
        queue_slot_car_0(); queue_slot_car_2(); queue_slot_car_3(); queue_slot_car_4();
        fill_road_row();
        draw_lane_marks(); draw_centre_line();
        row_y_step(); row_x_step(); row_heading_step(rec); row_slope_step(rec); row_scale_step();
        if (crest_y <= D:0380) return;                    // crest reached the top of the clip
        row_index++;
        d7 += mirror_flag ? -1 : 1;
        if (--left < 0) return;
    }
}

u8 *road_record_at(s16 d7) {                              // 0x1D32A (also used by the sim)
    u8 b = 0;
    if (d7 >= 0 && (d7 < stage_end_unit || d7 + 0x2D < stage_end_unit)) {
        b = road_stream[d7];
        if (b == 0xFF) { d7 -= 0x2D; stage_end_unit = d7; b = 0; }   // d7 is the caller's register!
    }
    return road_records + 4 * b;
}
```

`stage_end_unit` starts at (index of 0xFF) − 45, so the 0xFF branch is not reached with the shipped data;
every unit at or beyond it reads record 0 (straight and flat), like DOS `road_end_ptr`.

```c
void row_widths(u8 *rec) {                                // 0x1E5C6; table 0x1E45A = 0x140 + 0x40·i
    u8 b = rec[0];
    if (b == 0xFF) {
        if (row_index == 0) { half_left = car_half_left; half_right = car_half_right; }
        else                { half_left = last_left;     half_right = last_right; }
    } else {
        half_left  = W[(b >> 4) & 0xF]; half_right = W[b & 0xF];
        if (row_index == 0) { car_half_left = half_left; car_half_right = half_right; }
    }
    last_left = half_left; last_right = half_right;
}
```

Shipped width bytes are 0x22..0x29 and 0xFF: left half always 0x1C0, right half 0x1C0..0x380.

```c
void row_y_step(void) {                                   // 0x1DD56
    if (HI(row_y) <= crest_y) crest_y = HI(row_y);
    u32 d1 = mulu(8, row_scale);
    if (first_row_weight) d1 = mulu((u16)(d1 >> 8), first_row_weight) >> 7;
    s16 sl = mirror_flag ? -slope_acc : slope_acc;
    row_y -= (mul_scale(sl) asr 2) + d1;
}
void row_x_step(void) {                                   // 0x2472A
    u16 k = 0x50;
    if (mirror_flag) k = 0x28;
    else {
        if (HI(row_y) >= 0x7D) { near_rows_flag = -1; heading_acc = view_heading; return; }
        if (near_rows_flag)    { near_rows_flag = 0;  heading_acc = view_heading; return; }
    }
    s32 h = heading_acc; int neg = h < 0; if (neg) h = -h;
    u32 sn = sin16_16(h);                                  // 0x12108: 0..0xFFFF
    s32 d = mul_scale((s16)(mulu(sn, k) asr 8)) asr 8;     // (sn·k)>>8 then ×scale>>8
    row_cx += neg ? -d : d;
    if (mirror_flag) row_cx -= mul_scale(-HI(r_lateral)) asr 3;
    else { s32 t = mul_scale(HI(r_lateral)) asr 2; row_cx += t - (t asr 2); }
}
void row_heading_step(u8 *rec) {                          // 0x246FA
    s32 c = (s8)rec[1];
    c = first_row_weight ? (muls(c, first_row_weight) << 1) : (c << 16);
    heading_acc += c asr 3;
    clamp_word(&HI(heading_acc), -0x5A, 0x5A);             // high word only
}
void row_slope_step(u8 *rec) {                            // 0x1DD96
    u32 d1 = row_scale;
    if (first_row_weight) d1 = (mulu(row_scale, first_row_weight) << 1) >> 16;
    if (mirror_flag) d1 <<= 1;
    d1 = (s32)(0x48000 - 4 * d1) asr 4;
    slope_acc += muls((s8)rec[2], (s16)d1) >> 16;
    s16 t = (s8)slope_clamp[row_index];                    // D:0B38
    clamp_word(&slope_acc, -t, t);
}
void row_scale_step(void) {                               // 0x1DD34
    row_scale  = mulu(row_scale,  0xE8F5) >> 16;
    row_scale2 = mulu(row_scale2, 0xE8F5) >> 16;
    first_row_weight = 0;
}
```

Notes: `row_x_step` runs before `row_heading_step`, and `row_y_step` before `row_slope_step`: a row's own
curve and pitch take effect from the next row. On the main view the heading is re-seeded from the car heading
until the rows reach y < 0x7D (plus one more row), so rows below the window never bend. With `frac == 0`,
`init_row_scale` gives weight 1 (not 0x8000) and scale 0xFFFF: a one-frame jump at every unit boundary.

### 4.4 Road fill

```c
void fill_road_row(void) {                                // 0x20128
    shoulder_plane4 = 0;
    s16 sh = mulu(0x6E, row_scale) >> 16;
    s16 y = HI(row_y);
    if (y < min_row_y) min_row_y = y;
    if (right_edge + sh < cliff_x) {
        cliff_x = right_edge + sh; cliff_scale = row_scale; cliff_y = y;
        if (min_row_y < cliff_y) cliff_y = min_row_y;
    }
    D:0386 -= 1;
    if (y < crest_y) {                                     // (second test crest >= y is redundant)
        if (crest_y < prev_y) prev_y = crest_y;
        s16 row = prev_y - 1; u16 off = row * 40; s16 n = row - y;
        if (n > 1 || (n == 1 && !g_original_bugs)) {       // bug 6: n == 1 halves computed and discarded
            step_left  = trunc0((s16)(left_edge  - prev_left),  n + 1);   // divu, sign by negation
            step_right = trunc0((s16)(right_edge - prev_right), n + 1);
        }                                                  // (n == 1: asr #1 with the same sign handling)
        for (;;) {
            fill_row_span(pl0, off, prev_left, prev_right);               // road (+plane 3 below)
            s16 xl = prev_left - sh;
            left_shoulder_x[prev_y] = xl;                                  // indexed by row+1
            if (xl > max_left_x) { max_left_x = xl; max_left_row = prev_y; }
            fill_row_span(shoulder_plane4 ? pl4 : pl3, off, xl, prev_right + sh);
            fill_row_span(pl1, off, prev_right + sh + 1, D:0386);          // right ground
            if (--prev_y <= y) break;
            prev_left += step_left; off -= 40; prev_right += step_right;
        }
    }
    D:0386 += 1;
    prev_left = left_edge; prev_right = right_edge; prev_y = y;
}
```

It fills the scanlines `y .. min(prev_y, crest)−1` (n+1 lines) from the previous row's edges, stepping by
`(cur − prev)/(n+1)`: the last line stops one step short of the current edges. **Bug 6 (README):** with n = 1
two lines are filled; the code computes the halves (0x201BE–0x201D8: `asr #1` of the two differences, rounded
toward 0 like the `divu` path) but branches to 0x20206 past the stores at 0x201FE, so the original uses the stale
step of the previous call. Fixed by default: store them (the value is `trunc0(diff, 2)`, identical to the
general path); `--original-bugs` keeps the stale step. Colours with the colour-4 background
(plane 2): road = planes 0+2+3 = 13, shoulders = 2+3 = 12, right ground = 1+2 = 6.

```c
void fill_row_span(u16 *plane, u16 off, s16 x0, s16 x1) {  // 0x20096 (inclusive x0..x1)
    if (x0 > D:0386) return; if (x0 < D:0384) x0 = D:0384;
    if (x1 < D:0384) return; if (x1 > D:0386) x1 = D:0386;
    u16 *p = plane + off/2 + ((x0 >> 3) & ~1)/2;
    int bytes = ((x1 >> 3) & ~1) + 2 - ((x0 >> 3) & ~1); if (bytes == 0) return;
    // one-row blit, BLTCON0 0x01F0 (D = A), A = 0xFFFF with FWM = first_mask[x0&15], LWM = last_mask[(x1&15)+1]
    for (k = 0; k < bytes/2; k++) {
        u16 a = 0xFFFF; if (k == 0) a &= first_mask[x0 & 15]; if (k == bytes/2 - 1) a &= last_mask[(x1 & 15) + 1];
        if (g_original_bugs) p[k] = a;                     // bug 5: whole word overwritten, bits outside the span -> 0
        else                 p[k] |= a;                    // fixed: D = A | C, bits outside the span kept
    }
}

void fill_left_ground(void) {                             // 0x202A8 (main view only)
    s16 top = prev_y, best = max_left_x, brow = prev_y;
    for (s16 r = max_left_row; r > top; r--)
        if (left_shoulder_x[r] < best) { best = left_shoulder_x[r]; brow = r; }
    if (best >= max_left_x) return;
    u16 off = brow * 40;
    for (s16 r = brow + 1; r <= window_bottom; r++, off += 40) {
        s16 x1 = left_shoulder_x[r] - 1;
        if (x1 >= best) fill_row_span(pl1, off, best, x1);            // colour 6
    }
}
```

Below the row where the left shoulder, seen from the nearest max, comes back furthest left, the ground
between that x and the shoulder turns colour 6 (the DOS `min_ol` effect). Entries for scanlines not written
this frame keep old values.

```c
void draw_centre_line(void) {                             // 0x2031C, d7 = current unit
    if (!wide_road && !(d7 & 4)) return;
    pixel_plane_off = 0x0C; blit_wait();
    plot_pixel_clear(HI(row_cx), HI(row_y)); plot_pixel_clear(HI(row_cx) + 1, HI(row_y));   // 13 -> 5
}
void draw_lane_marks(void) {                              // 0x1E65C
    wide_road = 0;
    if ((s16)half_right <= 0x224) return;
    wide_road = -1;
    if (!(d7 & 4)) return;
    s16 x = row_centre + (mulu(0x1C0, row_scale) >> 16);
    pixel_plane_off = 0x10; plot_pixel_set(x, HI(row_y));                  // plane 4
    pixel_plane_off = 0x00; plot_pixel_clear(x, HI(row_y));                // 13 -> 28
}
void plot_pixel_set(s16 x, s16 y) {                       // 0x1D27E (0x1D2C2 clears)
    if (x < 0 || x >= 0x140 || y < 10 || y >= crest_y) return;
    plane[pixel_plane_off/4][y*40 + (x >> 3)] |= 1 << (7 - (x & 7));
}
```

The pixel routines do not test the mirror rectangle: in the mirror pass a centre-line or lane pixel with
x < 0xF0 lands in the main view (probably rare).

```c
void draw_horizon_cliff(void) {                           // 0x2034E
    s16 x = (cliff_x + 0x20) & 0xFFF0; if (x < 0) x = 0;
    s16 wb = ((D:0386 - x) asr 3) & 0xFFFE;
    if (wb > 0) {
        s16 h = cliff_y; if (h > window_bottom) cliff_y = h = window_bottom;
        h -= D:0380; if (h <= 0) return;
        blit_rect_clear(pl0,x,D:0380,wb,h); blit_rect_set(pl1,..); blit_rect_set(pl2,..);
        blit_rect_clear(pl3,..); blit_rect_clear(pl4,..);                  // colour 6
    }
    s16 save = D:0382; D:0382 = cliff_y;
    blit_cookie(clf0, clf0_mask, cliff_x - clf0.hot_x, cliff_y - clf0.hot_y);
    D:0382 = save;
}
```

### 4.5 Objects: queue, slot cars, dispatch

```c
void queue_object(s16 x, s16 y, u16 code) {               // 0x20410
    if (queue_count >= 0xC7) return;
    queue_x[n] = x; queue_y[n] = (y >= crest_y) ? crest_y : y;
    queue_code[n] = code; queue_scale[n] = row_scale; queue_count++;
}
void queue_hazard(s16 x, s16 y, u8 obj) {                 // 0x1E2F8; code = obj & 0x3F (0x20..0x23)
    s16 d = mulu(obj, row_scale) >> 16;                    // whole byte: lane bits 0x40/0x80 included
    queue_object(x + 2*d, y, obj & 0x3F);                  // lanes at 64/192/320/448 × s right of centre
}
void queue_post(s16 x, s16 y) {                           // 0x1E216
    if ((d7 & 0xF) == 0 && row_index > 6) queue_object(x, y, 0x41);
}
void queue_scenery_wed(s16 x, s16 y) {                    // 0x1E230, table A = 0x1E47A
    u8 a = A[d7 & 0x3F]; if (!a || y >= 0x7A) return;
    s16 t = mulu(2*a, row_scale) >> 16;
    queue_object(x + (t asr 3) + (mulu(0x6E, row_scale) >> 16), y - t, 0x30);
}
void queue_scenery_rock(s16 x, s16 y) {                   // 0x1E276, table B = 0x1E4BA
    if (!B[d7 & 0x3F] || y >= 0x7A) return;
    queue_object(x + (mulu(0x28, row_scale) >> 16), y, 0x31);
}
void queue_scenery_lin(s16 x, s16 y) {                    // 0x1E2B0, table C = 0x1E4FA
    u8 c = C[d7 & 0x3F]; if (!c || y >= 0x7A) return;
    s16 t = mulu(8*c, row_scale) >> 16;
    queue_object(x + (t asr 3) + (mulu(0xB4, row_scale) >> 16), y - t, 0x32);
}
```

Same-direction slot cars (0x1E062 slot 0 … 0x1E0B8 slot 4, 0x1E0CC slot 5 = police). `d6 = 4·slot`,
`d5` = base lateral: −0xE0 for slots 0, 2, 3, 4 and +0xE0 for slot 1:

```c
void queue_slot_car(int slot, s16 d5, s16 y) {            // common tail 0x1E124 / 0x1E142
    if (d7 != HI(r_same_dir[slot])) return;
    if (slot == 5) {                                       // 0x1E0CC
        if (cop_mode >= 10) {                              // unsigned
            u16 t = cop_seq_timer > 0x3C ? 0x3C : cop_seq_timer;
            s16 a = t - 0x1E; if (a < 0) a = -a;
            d5 = ((a - 0x1E) << 4) + 0xE0;
        } else {
            d5 = 0xE0; s16 s = police_slide;
            if (s < 0) { s += 0x38; if (s < -0xE0) s = -0xE0; d5 += s; police_slide = s; }
        }
    } else {
        s16 s = slot_slide[slot];
        if (s > 0) { s -= 0x38; if (s > 0xE0) s = 0xE0; d5 += s; slot_slide[slot] = s; }
    }
    slot_lateral[slot] = slot_base_lat + d5;               // read back by the simulation
    u16 save = row_scale;
    if (row_index <= 6) {
        if (row_index <= 2) goto out;
        row_scale = mirror_flag ? 0x2D6E : 0x9160;
    }
    queue_object(slot_base_x + ((muls(d5, row_scale >> 1) >> 16) << 1), y, 0x18 + slot);
out: row_scale = save;
}

void queue_oncoming_cars(s16 x, s16 y) {                  // 0x1E19E
    u16 save = row_scale;
    if (row_index <= 6) { if (row_index <= 2) goto out; row_scale = mirror_flag ? 0x2D6E : 0x9160; }
    for (k = 0; k < 5; k++) if (d7 == HI(r_oncoming[k])) {
        oncoming_lateral[k] = slot_base_lat - 0xE0;        // slot_base_lat is 0 here
        queue_object(x - (mulu(0xE0, row_scale) >> 16), y, 0x10 + k);
    }
out: row_scale = save;
}
```

Slots 5, 1 and the oncoming cars are queued before the widths are known (`slot_base_x` = centre, `slot_base_lat` =
0); slots 0, 2, 3, 4 after (`slot_base_x` = right edge, `slot_base_lat` = right half-width). On a normal road
(right half 0x1C0) both give lane centre 0xE0. **Bug 2 (README):** in the original, for rows 3..6 slots 0, 2, 3, 4
use the broken `slot_base_x` of §4.3 (the low word of `K·half_right`: every other `mulu` of the walker is followed
by `swap`, this one is not) and land far off-screen, while slots 1 and 5 and oncoming cars are drawn there at the
fixed near size. Fixed by default: with the high word, slot 0 on a normal road gets `centre + HI(0x9160·0x1C0) +
(−0xE0·0x9160 >> 16)` ≈ `centre + 0xE0·0.567`, the same place as slot 1, so the near cars show; `--original-bugs`
keeps them hidden. The slides decay by 0x38 **per rendered frame** and stick once they cross 0.

```c
void draw_object_queue(void) {                            // 0x20456
    u16 save = D:0382;
    while (--queue_count >= 0) {
        s16 x = queue_x[n], y = queue_y[n]; D:0382 = y; u16 code = queue_code[n], s = queue_scale[n];
        if (s > cliff_scale) { draw_horizon_cliff(); cliff_scale = 0xFFFF; }   // unsigned
        if      (code >= 2    && code <= 0x0F) draw_obj_sign(x, y, code, s);
        else if (code >= 0x10 && code <= 0x1D) draw_obj_traffic(x, y, code, s);
        else if (code >= 0x20 && code <= 0x23) draw_obj_hazard(x, y, code, s);
        else if (code == 0x30) draw_obj_wed(x, y, s);
        else if (code == 0x31) draw_obj_rock(x, y, s);
        else if (code == 0x32) draw_obj_lin(x, y, s);
        else if (code == 0x41) draw_obj_post(x, y, s);
    }
    D:0382 = save; queue_count = 0;
    if (cliff_scale != 0xFFFF) draw_horizon_cliff();       // cliff_scale is not reset here
}

u16 scale_index5(u16 s) {                                 // 0x205A6 -> 0,4,8,12,16 (byte offset)
    s += 0x1000; if (s & 0x8000) s = 0x7FFF;               // s >= 0xF000 wraps to a small value
    return (mulu(s, 0x28) >> 16) & 0x1C;
}
u16 scale_index4(u16 s) {                                 // 0x205BC -> 0,4,8,12
    s += 0x1000; if (s & 0x8000) s = 0x7FFF;
    return rol16(s, 5) & 0x0C;                             // = ((s >> 13) & 3) * 4
}
```

Every object is drawn with `blit_cookie(img, mask, x − hot_x, y − hot_y)` and clip bottom `D:0382` = its
(crest-clamped) base y, except traffic (clip bottom = `window_bottom`). A null table entry draws nothing.

```c
void draw_obj_sign(s16 x, s16 y, u16 code, u16 s) {       // 0x206E8
    y -= mulu(0x5A, s) >> 16;
    if (mirror_flag) {                                     // 0x206A0
        u16 i = scale_index4(s); if (i > 4) i = 4;         // only sizes 0 and 1
        blit(pol[i/4], pol_mask[i/4]); blit(rsg[i/4], rsg_mask[i/4]);       // sign back
        return;
    }
    u16 i = scale_index5(s);
    blit(pol[i/4], pol_mask[i/4]);                         // D:25E4 / D:25C8
    blit(SIGN[code][i/4], SIGN_MASK[code][i/4]);           // D:1A2E / D:1A6E tables
}
void draw_obj_hazard(..) { i = scale_index5(s); blit(HAZ[code-0x20][i/4], HAZ_MASK[code-0x20][i/4]); } // D:1A0E/D:1A1E
void draw_obj_wed (..) { i = scale_index4(s); x += 6; blit(wed[i/4],  wed_mask[i/4]); }
void draw_obj_rock(..) { i = scale_index4(s);          blit(rck[i/4],  rck_mask[i/4]); }
void draw_obj_lin (..) { i = scale_index4(s); x += 6; blit(lin[i/4],  lin_mask[i/4]); }
void draw_obj_post(..) { y -= mulu(0x23, s) >> 16; i = scale_index4(s); blit(pst[i/4], pst_mask[i/4]); }

void draw_obj_traffic(s16 x, s16 y, u16 code, u16 s) {    // 0x205CE; d4 is a 32-bit register
    D:0382 = window_bottom;
    u16 d2 = (code - 0x10) * 4;
    traffic_scale_tmp = s;
    u32 r = scale_index5_reg(s);                           // returns d4 = swap(mulu(s',0x28)) & 0xFFFF001C
    if ((u16)r != traffic_size[d2]) {
        if ((u16)r > traffic_size[d2])                     // growing: need 1/0.828 more
            r = scale_index5((u16)(mulu(s, 0xD3FC) >> 16));
        else {                                             // shrinking: need 1.207 less
            u32 n = ((u32)s << 16) | (r >> 16);            // low word = low half of the previous product
            if ((n / 0xD3FC) <= 0xFFFF) r = scale_index5((u16)(n / 0xD3FC));
            else                        r = scale_index5((u16)(r >> 16));  // divu overflow keeps d4 (swapped)
        }
    }
    traffic_size[d2] = (u16)r; u16 i = (u16)r;
    Shape **img  = (mirror_flag ? MIRROR_CAR     /*D:1B2E*/ : CAR     /*D:1AAE*/)[d2/4];
    Shape **mask = (mirror_flag ? MIRROR_CARMASK /*D:1B6E*/ : CARMASK /*D:1AEE*/)[d2/4];
    blit_cookie(img[i/4], mask[i/4], x - hot, y - hot);
    if (d2 == 0x34) {                                      // police
        police_flash++;
        if (police_flash & 2) blit_xor((mirror_flag ? cpl : clr)[i/4], x - hot, y - hot);  // light bar
        if (cop_mode == 0xF && cpb[i/4]) blit_xor(cpb[i/4], x - hot, y - hot);            // sizes 3,4 only
    }
}
```

`scale_index5_reg`: the exact register effect of 0x205A6 (`mulu`, `swap`, `and.w #$1C`), needed only for
the divu-overflow case (scale ≥ 0xD3FC while shrinking). The size memory `traffic_size` is per code and shared
by the main view and the mirror; `police_flash` counts police draws (twice per frame when it is in both views).

### 4.6 Clouds and bugs

```c
void draw_clouds(void) {                                  // 0x1E758 (main view only)
    D:0382 = crest_y;                                      // not restored
    s16 h = HI(world_heading);
    s16 d = wrap_angle_delta(h, cloud_heading);            // 0x1EBA8: h - ref wrapped to [-180, 180]
    cloud_heading = h;
    move_clouds(d << 2);
    static const s16 dy[4] = { 0x11, 0x14, 0x23, 0x26 };   // 0x1E7CA
    for (i = 0; i < 4; i++)                                // cldA, cldB, cld0, cld1 (D:2564.., masks D:2554..)
        blit_cookie(cld[i], cld_mask[i], HI(cloud_x[i]) - hot_x, HI(row_y) - dy[i] - hot_y);
}
void move_clouds(s16 d4) {                                // 0x1EAE0
    s32 v = (s32)d4 << 16;
    for all 4: cloud_x[i] -= v;  v asr= 1;  for all 4: cloud_x[i] -= v;  v asr= 1;
    cloud_x[0] += v; cloud_x[1] += v;                      // net: clouds 0,1 -5·Δ, clouds 2,3 -6·Δ px
    cloud_x[0] += 0xFA0; cloud_x[1] += 0x1388; cloud_x[2] += 0x1770; cloud_x[3] += 0x1B58;   // drift/frame
    for all 4: HI(cloud_x[i]) = wrap_cloud_x(HI(cloud_x[i]));  // 0x1EB5E: +-0x320 into [-400, 400]
}
void init_clouds(void) {                                  // 0x1EB78 (high words only)
    cloud_heading = 0; HI(cloud_x[0..3]) = { 0x1E, 0x78, 0x32, 0x15E };
    D:0DB0 = 0x78; D:0DB4 = 0x15E; D:0DB8 = -0xC8;         // for the dead code at 0x1EA9A
}
```

`HI(row_y)` is the value after the last walked row, i.e. just beyond the horizon; the clip bottom is the crest.

```c
void draw_bugs(void) {                                    // 0x1E7D2; list in code at 0x1E89A
    D:0382 = 0x75;
    if (bug_count < 30 && (u16)HI(r_speed) >= 0x55 && (rand16() & 0x3FF) == 0) {
        e = &bugs[bug_count]; e->x = (rand16() & 0xFF) + 0x20; e->y = rand16() & 0x7F;
        e->img = bug1; e->mask = bug1_mask; e->ttl = 5; bug_count++;
    }
    for (each e in bugs[0..bug_count-1]) {
        blit_cookie(e->img, e->mask, e->x, e->y);         // no hot-spot correction
        u16 t = e->ttl;
        if (t) {
            e->y -= 2; e->ttl = t - 1;
            if (t == 1) { r = rand16() & 3; e->img = bugABCD[r]; e->mask = bugABCD_mask[r]; }   // splat
            else if (t == 2) { e->img = bug1b; e->mask = bug1b_mask; }                          // "bug1" again
        }
    }
}
```

A bug flies up 2 px per frame for 4 frames, then stays as a splat until the list is cleared at stage start
(0x1CCF6). Both lookups are `"bug1"` (`bug0`, `bug2`, `bugE` are never used).

### 4.7 Cockpit overlays

```c
void draw_cockpit_overlays(void) {                        // 0x1EBC4
    clip_full_screen();
    blit_cookie_aligned(hood, hood_mask, hood.x, hood.y);
    blit_cookie_aligned(roof, roof_mask, roof.x, roof.y);
    blit_cookie_aligned(post, post_mask, post.x, post.y);
    blit_cookie_aligned(mirr, mirr_mask, mirr.x, mirr.y);
    draw_radar_detector(); draw_steering_wheel();
}

void draw_radar_detector(void) {                          // 0x1EC94; tick_count = D:03D8 (60 Hz)
    s16 dt = (s16)(tick_count - radar_time);
    if (radar_dark) {
        if (dt < 8) return;
        radar_dark = 0; radar_time = tick_count;
        if (HI(radar_level)) radar_beep();                 // 0x26C50
    } else {
        s16 l = HI(radar_level); if (l > 5) l = 5;
        blit_xor_aligned(rad[l], rad[l].x, rad[l].y);      // over the freshly drawn roof
        if (dt >= radar_on_time) { radar_dark = -1; radar_time = tick_count; }
    }
}

void draw_steering_wheel(void) {                          // 0x1ED06
    s16 p = (abs16(HI(r_steer)) + 4) >> 3;  if (p >= 3) p = 2;
    if (HI(r_steer) < 0) p = -p;  p += 2;                   // 0..4, 2 = centred (in the dash picture)
    if (p != wheel_pose_here) {
        if (wheel_pose_here != 2 && wheel_pose_here >= 0 && wheel_pose_here < 5) xor_wheel_pose(wheel_pose_here);
        wheel_pose_here = p; xor_wheel_pose(p);
    }
    swap(wheel_pose_other, wheel_pose_here);
}
void xor_wheel_pose(s16 p) { if (p == 2) return; if (p > 2) p--; blit_xor_aligned(whl[p], whl[p].x, whl[p].y); }
void reset_wheel_state(int keep) {                        // 0x1ED8A
    if (!keep) wheel_pose_other = wheel_pose_here = (s16)0xFE0C;
    else wheel_pose_here = wheel_pose_other;
    marker_cache = 0x87654321;
}

void toggle_gear_box(void) {                              // 0x203E0
    if (gearbox_wanted[back_index] != gearbox_shown[back_index]) {
        gearbox_shown[back_index] = ~gearbox_shown[back_index];
        blit_xor_aligned(gbox, gbox.x, gbox.y);
    }
}
void draw_ticket(void) { if (cop_stop_timer >= 0x1E) blit_cookie(tick, tick_mask, tick.x, tick.y); }  // 0x1E63A
```

### 4.8 Gauges and sprites

#### 4.8.1 Sprite bookkeeping

Sprite data: one chip block of 0x7D0 bytes, sprite n at `+250·n` (125 words). A sprite is a chain of
*segments*: two control words (POS, CTL) then two words (DATA, DATB) per line; a zero control pair ends the
chain. The copper list (§4.9) reloads SPRxPT every frame, so CPU writes show on the next frame.

```c
u16 spr_pos(h, v0, v1, att) { return ((v0 & 0xFF) << 8) + ((s16)h asr 1); }                       // 0x1EF76
u16 spr_ctl(h, v0, v1, att) { return ((v1 & 0xFF) << 8) + ((v0 & 0x100) >> 6) + ((v1 & 0x100) >> 7)
                                     + ((att ? 1 : 0) << 7) + (h & 1); }                            // 0x1EF90
void sprite_set_segment(u16 w, s16 h, s16 v0, s16 v1, int att, int n) {                            // 0x1F05A
    v0 -= sprite_shake; v1 -= sprite_shake;
    sprite_data[n][w] = spr_pos(h, v0, v1, att); sprite_data[n][w + 1] = spr_ctl(h, v0, v1, att);
}
void sprite_add_segment(h, v0, v1, att, n) {                                                       // 0x1F0DC
    sprite_set_segment(sprite_next_word[n], h, v0, v1, att, n);
    sprite_next_word[n] += (v1 - v0) * 2 + 2;
}
void pack_shape_to_sprite(Shape *src, u16 *dst, u16 planes, u16 col, Shape *mask, u16 mcol) {      // 0x1F12C
    u16 ww = (src->w_bytes + 1) >> 1, mw = mask ? (mask->w_bytes + 1) >> 1 : 0, k = 0;
    u16 *sp = (u16 *)(src + 1);                            // plane data after the 16-byte header
    for (p = 0; p < src->planes; p++, sp += src->h * ww) {
        if (!((1 << p) & planes)) continue;
        u16 d = k, c = col, m = mcol;
        for (r = 0; r < src->h; r++, d += 2, c += ww, m += mw)
            dst[d] = mask ? (sp[c] & ((u16 *)(mask + 1))[m]) : sp[c];   // mask: its plane 0, h rows of *src*
        k++;                                               // next copied plane goes to the DATB words
    }
}
void shape_to_sprite_segment(Shape *s, int n, u16 planes, u16 col) {                              // 0x1F27E
    pack_shape_to_sprite(s, sprite_data[n] + sprite_next_word[n] + 2, planes, col, 0, 0);
    sprite_next_word[n] += s->h * 2 + 2;
}

void sprites_init(void) {                                 // 0x1F5BA
    speed_pair_shift = tach_pair_shift = 0;
    sprite_data[0] = alloc_chip(0x7D0);
    for (n = 0; n < 8; n++) { sprite_data[n] = sprite_data[0] + n * 125; sprite_next_word[n] = 0; }
    needle_seg = 0;
    if (needle_gauges /*D:194E*/) {
        sprite_add_segment(tach_box_x + 0x80, tach_box_y + 0x2C, tach_box_y + 0x5F, 0, 0);      // D:1978/197A
        sprite_add_segment(tach_box_x + 0x90, tach_box_y + 0x2C, tach_box_y + 0x5F, 0, 1);
        sprite_add_segment(speed_box_x + 0x80, speed_box_y + 0x2C, speed_box_y + 0x5F, 0, 2);   // D:1974/1976
        sprite_add_segment(speed_box_x + 0x90, speed_box_y + 0x2C, speed_box_y + 0x5F, 0, 3);
    }
    dot_seg = sprite_next_word[7];                         // 0
    for (n = 4; n < 8; n++) {
        sprite_add_segment(0xE4, 0xA4, 0xA8, 0, n);        // 4 lines
        u16 *d = sprite_data[n] + dot_seg + 2;
        if (n == 7) { d[0]=d[1]=0x6000; d[2]=d[3]=0xF000; d[4]=d[5]=0xF000; d[6]=d[7]=0x6000; }   // marker dot
        else for (i = 0; i < 8; i++) d[i] = 0;
    }
    for (n = 4; n < 8; n++) knob_seg[n - 4] = sprite_next_word[n];                               // 10
    shape_to_sprite_segment(gnob, 4, 0x3, 0); shape_to_sprite_segment(gnob, 5, 0xC, 0);
    shape_to_sprite_segment(gnob, 6, 0x3, 1); shape_to_sprite_segment(gnob, 7, 0xC, 1);
    if (needle_gauges) {
        needle_bm = alloc(0x28); InitBitMap(needle_bm, 1, 0x20, 0x33);
        needle_rp = alloc(0x64); InitRastPort(needle_rp); needle_rp->BitMap = needle_bm;
        needle_shape = alloc_chip(0xDC); needle_bm->Planes[0] = needle_shape + 0x10;
        needle_shape->w_bytes = 4; ->h = 0x33; ->planes = 1; ->plane_bytes = 0xCC;
        SetAPen(needle_rp, 1);
    }
    DMACON = 0x8020;                                       // sprite DMA on
}
void sprites_free(void) { WaitTOF(); DMACON = 0x0020; free sprite_data[0], needle_shape, needle_rp, needle_bm (each then 0); }
```

Sprite use: 0/1 tachometer and 2/3 speedometer (colour 1 of their pair: COLOR17 / COLOR21 of the dash
palette); 4+5 and 6+7 attached pairs = the 32-pixel, 15-colour gear knob (`gnob` planes 0..3; plane 4 is not
used); sprite 7 segment 0 = the 4×4 marker dot, colour 3 of pair 6/7 (COLOR31).

#### 4.8.2 Analog needles

```c
void update_gauges(void) {                                // 0x20AF4 (render task, after the road)
    if (wheel_pose_other != gauge_pose) {                  // pose just drawn into this buffer
        gauge_pose = wheel_pose_other; i = gauge_pose;
        speed_overlay = spm[i]; speed_overlay_mask = spm_mask[i];     // D:2712.., D:2742..
        tach_overlay  = tcm[i]; tach_overlay_mask  = tcm_mask[i];     // D:26FE.., D:272E..
        needle_speed = 0xFFFF; digital_speed[0] = digital_speed[1] = 0xFFFF;
    }
    u16 sp = HI(car_speed);                                // live D:28A6, not the snapshot D:289E
    if (!needle_gauges) {
        b = back_index;
        if (sp == digital_speed[b] && (rpm & 0xFFE0) == digital_rpm[b]) return;
        digital_speed[b] = sp; digital_rpm[b] = rpm & 0xFFE0;
        draw_digital_cluster(); return;
    }
    if (sp == needle_speed && (rpm & 0xFFE0) == needle_rpm) return;   // needle_rpm stays 0xFFFF: always redraws
    s16 r = rpm; if (r > tach_clamp /*+002*/) r = tach_clamp; if (r <= 0x320) r = 0x320;
    u16 i = ((u16)r >> 5) & 0x1FE;
    draw_needle(tach_tips[i] - tach_box_x, tach_tips[i + 1] - tach_box_y, 0);          // u8 pairs (+328)
    needle_speed = sp;
    s16 v = sp - 10; if (v < 0) v = 0;
    draw_needle(speed_tips[2*v] - speed_box_x, speed_tips[2*v + 1] - speed_box_y, 2);  // (+17A)
}
```

Note: 0x20AF4 reads `D:28A6` (the live speed), not the snapshot `D:289E`; rpm is the live `D:191A`.

```c
void draw_needle(s16 x, s16 y, int which) {               // 0x1F2EA; which 0 = tach (sprites 0/1), 2 = speed (2/3)
    u16 off = (x > 0x18) ? 16 : 0;
    Shape *ov = which ? speed_overlay : tach_overlay;     // wheel-rim overlay used as the mask
    for (i = 0; i < 0x33; i++) ((u32 *)needle_bm->Planes[0])[i] = 0;
    if (x - off < 0 || x - off > 0x1F || y < 0 || y >= 0x33) return;   // old needle stays in the sprites
    if (which == 0) Move(needle_rp, pivot_tach_x - tach_box_x - off, pivot_tach_y - tach_box_y);      // +170/+171
    else            Move(needle_rp, pivot_speed_x - speed_box_x - off, pivot_speed_y - speed_box_y);  // +16E/+16F
    Draw(needle_rp, x - off, y);
    u16 *d0 = sprite_data[which] + needle_seg + 2, *d1 = sprite_data[which + 1] + needle_seg + 2;
    if (off) { pack_shape_to_sprite(needle_shape, d1, 1, 0, ov, 1); pack_shape_to_sprite(needle_shape, d0, 1, 1, ov, 2); }
    else     { pack_shape_to_sprite(needle_shape, d0, 1, 0, ov, 0); pack_shape_to_sprite(needle_shape, d1, 1, 1, ov, 1); }
    u16 *shift = which ? &speed_pair_shift : &tach_pair_shift;
    s16 bx = which ? speed_box_x : tach_box_x, by = which ? speed_box_y : tach_box_y;
    if (which == 0 || which == 2) if (2*off != *shift) {
        *shift = 2*off;
        sprite_set_segment(needle_seg, bx + *shift + 0x80, by + 0x2C, by + 0x5F, 0, which);   // left sprite only
    }
}
```

The needle box is 48 px wide and 51 lines tall, covered by two 16-px sprites: the right one stays at box+16,
the left one sits at box+0 (needle columns 0..31) or jumps to box+32 (columns 16..47). The wheel-rim overlay
`tcm*`/`spm*` masks the needle where the rim covers the gauge; its plane 0 is read with the needle's height
(51 lines), so beyond the overlay's own height the mask comes from its next plane (quirk).

#### 4.8.3 Digital cluster (Corvette, `+16C == 0`)

```c
void draw_digital_cluster(void) {                         // 0x2097C
    OwnBlitter(); clip_full_screen(); blit_init();
    blit_cookie_aligned(inst, 0, inst.x, inst.y);          // replace
    s16 len = mulu(HI(car_speed), speed_bar_scale /*+180*/) >> 16;
    if (speed_bar_dir == 0) D:0380 = speed_bar_x0 - len;   // clip TOP: a vertical bar growing upward
    else                    D:0386 = speed_bar_x0 + len;   // clip right
    blit_xor_aligned(sped, sped.x, sped.y); D:0380 = 0; D:0386 = 0x140;
    s16 r = rpm; if (r <= 0x320) r = 0x320;
    len = mulu((u16)r >> 4, tach_bar_scale /*+32A*/) >> 16;
    if (tach_bar_dir == 0) D:0380 = tach_bar_x0 - len; else D:0386 = tach_bar_x0 + len;
    blit_xor_aligned(tach, tach.x, tach.y); D:0380 = 0; D:0386 = 0x140;
    draw_number(HI(car_speed), speed_digits /*D:27A6*/, speed_digit_xy /*+16E*/);
    u16 t = (u32)(u16)r / 100; if (t >= 100) t = 99;
    draw_number(t, tach_digits /*D:277E*/, tach_digit_xy - 2 /*+318*/);
    if (tach_overlay)  blit_cookie(tach_overlay,  tach_overlay_mask,  own position);
    if (speed_overlay) blit_cookie(speed_overlay, speed_overlay_mask, own position);
    blit_wait(); DisownBlitter();
}
void draw_number(u16 v, Shape **dg, s16 *xy) {            // 0x20A88: positions are top-left, no hot spot
    if (v >= 100) blit_xor(dg[v / 100], xy[0], xy[1]);
    if (v >= 10)  blit_xor(dg[(v / 10) % 10], xy[2], xy[3]);
    blit_xor(dg[v % 10], xy[4], xy[5]);
}
```

For the Vette, speed dir 0 and "x0" 169 = the bottom line of `sped` (32×34 at 64,135): the bar is revealed
upward. FORMATS.md's reading ("left edge moves left from x0") is wrong for dir 0. The routine pops and pushes
back two longs of the caller's stack (`movem.l (a7)+,a2-a3 / movem.l a2-a3,-(a7)` at 0x20A22): no net
effect.

#### 4.8.4 Gear knob and gear gate

```c
void update_knob_sprites(void) {                          // 0x1CD72 (main task, per sim tick)
    if (gearbox_shown[0] && gearbox_shown[1]) {
        s16 d = knob_target_x - knob_x;
        knob_x = d > 4 ? knob_x + 4 : d < -4 ? knob_x - 4 : knob_target_x;
        d = knob_target_y - knob_y;
        knob_y = d > 8 ? knob_y + 8 : d < -8 ? knob_y - 8 : knob_target_y;
        if (knob_x == knob_shown_x && knob_y == knob_shown_y && knob_visible) {
            if (shift_in_progress) shift_in_progress = 0;
            if (knob_close_delay) knob_close_delay--;
            if (!knob_close_delay && !gearbox_hold) { gearbox_wanted[0] = gearbox_wanted[1] = 0; knob_shown_x = 0; }
        } else {
            s16 v1 = knob_y + gnob.h;
            sprite_set_segment(knob_seg[0], knob_x,      knob_y, v1, 0, 4);
            sprite_set_segment(knob_seg[1], knob_x,      knob_y, v1, 1, 5);
            sprite_set_segment(knob_seg[2], knob_x + 16, knob_y, v1, 0, 6);
            sprite_set_segment(knob_seg[3], knob_x + 16, knob_y, v1, 1, 7);
            knob_shown_y = knob_y; knob_shown_x = knob_x; knob_close_delay = 7; knob_visible = 1;
        }
    }
    if (knob_visible && (!gearbox_wanted[0] || !gearbox_wanted[1])) {
        for (n = 4; n < 8; n++) sprite_set_segment(knob_seg[n - 4], 0, 300, 0, 0, n);   // off screen
        knob_visible = 0;
    }
}
```

The gate (`gbox`) is XOR-drawn per buffer by `toggle_gear_box` in the render task; the knob follows only
once the gate is shown in both buffers.

#### 4.8.5 Steering-wheel marker

```c
void update_wheel_marker(void) {                          // 0x247B2, from the sim (0x24924) every tick
    s32 a = steer_angle << 1;
    if (a == marker_cache) return;
    marker_angle = marker_cache = a;
    clamp_word(&HI(marker_angle), -0x23, 0x23);            // +-35 degrees
    s16 y = marker_y /*+00E*/ - (mulu(cos_deg(HI(marker_angle)), marker_r /*+010*/) >> 16);
    s16 x = mulu(sin16_16(abs32(marker_angle)), marker_r) >> 16;
    if (HI(marker_angle) < 0) x = -x;
    x += marker_x /*+00C*/;
    position_wheel_marker(x, y);
}
void position_wheel_marker(s16 x, s16 y) { sprite_set_segment(dot_seg, x + 0x80, y + 0x2C, y + 0x30, 0, 7); }  // 0x1F582
```

#### 4.8.6 Dashboard bump shake (dead)

```c
void detect_pitch_bump(void) {                            // 0x2090C, d7 = HI(r_road_pos)
    u8 *rec = road_record_at(d7); pitch_bump_flag = 0;
    s8 d = last_pitch - rec[2]; if (d < 0) d = -d;
    if (d >= 3) pitch_bump_flag = -1;
    last_pitch = rec[2];
}
// 0x20940 (no caller): on pitch_bump_flag edges set sprite_shake = -1 / +1 and call shake_dash_sprites (0x1F9FE),
// which re-positions needle sprites 0/1 and knob sprites 4/5. Since nothing calls it, the port can drop it.
```

### 4.9 Copper list, palettes, fade

```c
void setup_drive_copper(View *v) {                        // 0x24D8A
    if (!dash_palette_valid) for (i = 0; i < 32; i++) dash_palette[i] = v->vp->ColorMap->ColorTable[i];
    dash_palette_valid = 1;
    UCopList *u = AllocMem(0xC, MEMF_PUBLIC|MEMF_CLEAR);
    ucop_sprite_pointers(u);
    ucop_palette_split(u, dash_palette, 0x75);
    v->vp->UCopIns = u; remake_view(v);                    // MakeVPort + MrgCop
    LoadRGB4(v->vp, road_palette /*D:19CE*/, 32);
    FreeVPortCopLists(viewA.vp); FreeVPortCopLists(viewB.vp);   // rebuilt by the next show_view/LoadView path
}
void ucop_sprite_pointers(UCopList *u) {                  // 0x1FAD4
    CWait(u, -10, 0); CBump(u);
    for (n = 0; n < 8; n++) {
        CMove SPRnPOS = spr_pos(0x80, 0x28, 0x28, 0); CMove SPRnCTL = spr_ctl(...);   // 0x1EFD4, each CBump
        CMove SPRnPTH = hi(sprite_data[n]); CMove SPRnPTL = lo(sprite_data[n]);          // 0x1EF14
    }
}
void ucop_palette_split(UCopList *u, u16 *pal, s16 line) {     // 0x1FB4A
    CWait(u, line - 1, palette_split_h /*100*/); CBump(u);
    for (i = 0; i < 32; i++) { CMove(u, COLOR00 + 2*i, pal[i]); CBump(u); }
    CWait(u, 10000, 255); CBump(u);                        // CEND
}
void fade_out_palette(int delay, u16 *pal2, s16 line) {   // 0x1FEAE (front view)
    FreeVPortCopLists(front->vp);
    u16 a[32] = front->vp->ColorMap colours; u16 b[32]; if (pal2) b = pal2[0..31];
    for (lv = 15; lv >= 0; lv--) {
        for (i = 0; i < 32; i++) { a[i] = clamp_rgb4(a[i], lv); b[i] = clamp_rgb4(b[i], lv); }
        if (pal2) {
            FreeVPortCopLists(front->vp);
            u = AllocMem(0xC, PUBLIC|CLEAR); CWait(u, line - 1, 100); CBump; 32 × CMove COLORxx = b[i]; CWait(u, 10000, 255);
            front->vp->UCopIns = u; remake_view(front);
        }
        LoadRGB4(front->vp, a, 32); Delay(delay);
    }
    FreeVPortCopLists(front->vp);
}
u16 clamp_rgb4(u16 c, u16 lv) { return min16(c & 0xF00, lv << 8) + min16(c & 0xF0, lv << 4) + min16(c & 0xF, lv); }  // 0x1FE54
void fade_out_drive(void) {                               // 0x24E52
    fade_out_palette(1, dash_palette, 0x75);
    FreeVPortCopLists(viewA.vp); FreeVPortCopLists(viewB.vp); remake_view(&viewA); remake_view(&viewB);
}
```

Note the fade drops the sprite-pointer part of the user copper list (the new list only has the palette), so
sprites stop being re-armed during the fade; `sprites_free` already turned sprite DMA off.

### 4.10 Crash and ending

```c
void crash_windscreen_sequence(void) {                    // 0x1FBD8
    RastPort rp; InitRastPort(&rp); SetAPen(&rp, 0x1C);    // colour 28 (white)
    view_copy(front, back);                                // 0x1580C: colours + BltBitMap
    front = &viewA;                                        // D:24CE forced to view A (see open questions)
    gearbox_shown[1] = gearbox_shown[0];                   // the other branch (at 0x1FC16) is unreachable
    reset_wheel_state(1);
    rp.BitMap = back->vp->RasInfo->BitMap;
    Move(&rp, cr[0][0]*2, cr[0][1]);                       // set 0: star from point 0
    for (k = 0; k < crack_count[0]; k++) Draw(&rp, cr[0][2k+2]*2, cr[0][2k+3]);
    redraw_cockpit_back();                                 // overlays cover the cracks at roof/hood/post/mirror
    show_view(back); view_copy(front, back); Delay(2);
    for (s = 1; s < 7; s++) {
        rp.BitMap = back->vp->RasInfo->BitMap;
        for (k = 0; k < crack_count[s]; k++) { Move(&rp, cr[s][4k]*2, cr[s][4k+1]); Draw(&rp, cr[s][4k+2]*2, cr[s][4k+3]); }
        redraw_cockpit_back(); show_view(back); view_copy(front, back); Delay(2);
    }
}
void redraw_cockpit_back(void) {                          // 0x1FDF4
    WaitBlit(); OwnBlitter(); blit_wait(); set_target(back bitmap planes);
    blit_init(); draw_cockpit_overlays(); blit_wait(); DisownBlitter();
}
```

GAME OVER (in 0x1C900, game_flow): `blit_cookie(game, game_mask, game.x, game.y)` into the back view,
`show_view`, wait for fire/break.

```c
void dealership_ending(void) {                            // 0x1CF76
    mask_pool = pool_alloc(0x1388); load_cockpit_shapes(); sprites_init();
    if ((picture = load_file("pics/EndGame")) == 0) goto out;
    ilbm_to_view(picture, back);
    for (p = 0; p < 5; p++)                                // keep the dashboard: copy rows 0x75.. from the front
        CopyMem(front_bm->Planes[p] + front_bm->BytesPerRow * 0x75,
                back_bm->Planes[p]  + back_bm->BytesPerRow  * 0x75,
                (u16)((back_bm->Rows - 0x75) * back_bm->BytesPerRow));
    free(picture);
    picture = load_file_chip("pics/EndGame.Shp"); Shape *note = find_shape(picture, 'note');
    redraw_cockpit_back();
    D:28C2 = D:28C0 = D:28BE = D:2838 = 0xFFFF;            // write-only leftovers
    needle_rpm = 0xFFFF; car_speed = 0; rpm = 0;           // clr.l D:191A also clears D:191C
    set_target(back planes); update_gauges();              // needles to rest / digital 0
    u = AllocMem(0xC, PUBLIC|CLEAR); ucop_sprite_pointers(u); ucop_palette_split(u, dash_palette, 0x75);
    back->vp->UCopIns = u; remake_view(back); show_view(back);
    if (gearbox_wanted[0]) {                               // knob to gate 0
        knob_x = gate[0].x + 0x80 - gnob.hot_x; knob_y = gate[0].y + 0x2C - gnob.hot_y;
        four sprite_set_segment calls as in 0x1CD72;
    }
    for (i = 0; i < 300 && !break_pressed() && !fire_pressed(); i++) { WaitTOF(); poll_input(); }
    draw_shape_to_view(note, front);                       // 0x14984, at its own position (64,21)
    free(picture); Delay(10);
    while (!fire_pressed() && !break_pressed()) { WaitTOF(); poll_input(); }
out: free(mask_pool); mask_pool = 0;
}
```

### 4.11 Shape handles (loaders 0x24FAA, 0x253E6, 0x25740, 0x259D8, 0x2627C)

`find_shape(archive, 'name')` for each name; a mask is made with `make_mask(mask_pool, shape)` where
listed. `D:27CE` = `<car>Dash.Shp`, `D:27D2` = `Pics/Road.Shp`.

| handles (mask) | shapes | used by |
|---|---|---|
| 2574 (2578), 2688 (268C), 2600 (2604), 25C0 (25C4) | `hood roof post mirr` | 0x1EBC4 |
| 26FE..270E (272E..273E†) | `tcm0 tcm1 tcmC tcm2 tcm3` (index = wheel pose; missing → `tcmC`) | gauges |
| 2712..2722 (2742..2752†) | `spm0 spm1 spmC spm2 spm3` (missing → `spmC`) | gauges |
| 277E[10], 27A6[10] | tach / speed digits: prefix (`+32C` / `+182`) & 0x7F7F7F00 + '0'..'9'† | 0x20A88 |
| 2772, 2776, 277A | `inst sped tach`† | 0x2097C |
| 257C, 2514 | `gnob gbox` | sprites, 0x203E0 |
| 2690..269C | `whl0 whl1 whl2 whl3` | 0x1ED64 |
| 2620..2634 (2608..261C) | `rad0..rad5` | 0x1EC94 |
| 2564..2570 (2554..2560) | `cldA cldB cld0 cld1` | clouds |
| 25B0..25BC (25A0..25AC) | `pst1..pst4` | code 0x41 |
| 2550 (254C) | `clf0` | cliff |
| 26B0..26BC (26A0..26AC) | `wed0..wed3` | code 0x30 |
| 2590..259C (2580..258C) | `linA..linD` | code 0x32 |
| 251C (2518), 2524 (2520), 2538..2544 (2528..2534) | `bug1`, `bug1` (again), `bugA..bugD` | bugs |
| 275E (2762), 2766 (276A) | `tick`, `game` | ticket, GAME OVER |
| 2668..2684 (2648..2660: 7 masks) | `rckA..rckH` (`rckH` has no mask; `rckF..H` unused) | codes 0x31, 0x20 |
| 2962 (2976), 298A (299E), 29B2 (29C6) ×5 | `oil0-4`, `pot0-4`, `gra0-4` | codes 0x21..0x23 |
| 29DA 2A02 2A2A 2A52 2A7A 2AA2 (+0x14 masks) ×5 | `rtn ltn twt sp3 sp5 sp6` 0-4 | sign codes 2..7 |
| 2ACA 2AF2 2B1A 2B42 2B6A (+0x14) ×5 | `gas0-4` five times | sign codes 8..0xC |
| 2B92 (2BA6), 2BBA (2BCE) ×5 | `pas0-4`, `mrg0-4` | sign codes 0xD, 0xE |
| 2640 (2638) ×2 | `rsg0 rsg1` | mirror signs |
| 25E4..25FC (25C8..25E0) | `pol0..pol4 rpl0 rpl1` (`rpl*` unused) | sign poles |
| 2BE2 2C0A 2C32 2C5A 2D72 2D9A 2C82 2CAA 2CD2 2CFA 2D22 2D4A (+0x14) ×5 | `rig trk sed sdr rx7 x7r vnf vnr sed sdr sed sdr` 0-4 | traffic |
| 2DC2..2DD2 (2DD6..2DE6) | `cop0 cop1 cop2 cop3 cop3` | mirror police |
| 2DEA..2DFA (2DFE..) | `cpr0..cpr4` | police |
| 26E8..26F8, 26D4..26E4 | `cpl0 cpl1 cpl2 cpl3 cpl3`, `clr0..clr4` (no masks: XOR) | light bars |
| 26CC, 26D0 (26C0..26C8 = 0) | `cpb3 cpb4` | stopped police |

† digital dash only (`D:194E == 0`).

Pointer tables in initialised data (sign/traffic codes → handle arrays):

| table | entries |
|---|---|
| `D:1A2E` / `D:1A6E` SIGN / SIGN_MASK [16] | 0, 0, rtn, ltn, twt, sp3, sp5, sp6, gas, gas, gas, gas, gas, pas, mrg, 0 |
| `D:1A0E` / `D:1A1E` HAZ [4] | rck, oil, pot, gra |
| `D:1AAE` / `D:1AEE` CAR [16] (main) | 0x10.. rig, sed, vnf, sed, sed, 0, 0, 0, 0x18.. trk, x7r, vnr, sdr, sdr, cpr, 0, 0 |
| `D:1B2E` / `D:1B6E` MIRROR_CAR [16] | trk, sdr, vnr, sdr, sdr, 0, 0, 0, rig, rx7, vnf, sed, sed, cop, 0, 0 |

### 4.12 Data tables

```
road half-width W[16]   (0x1E45A)  0x140 + 0x40*i  (0x140 .. 0x500)
scenery A (wed, 0x1E47A) 180,0,0,0,0,0,0,110,0,0,0,0,0,217,0,0,0,130,0,0,0,0,0,0,0,0,100,0,0,60,0,0,
                         0,0,0,200,0,0,50,0,0,0,140,0,0,0,0,0,180,0,0,0,80,0,0,0,0,255,0,0,143,0,0,0
scenery B (rck, 0x1E4BA) 2 at 0,47; 1 at 17,26,38,48,60; else 0
scenery C (lin, 0x1E4FA) 129,0,17,0,160,33,0,195,0,0,18,0,128,242,0,0,0,51,0,0,115,0,18,0,241,0,128,0,19,193,0,161,
                         0,208,0,67,0,225,128,0,0,0,65,0,162,0,32,0,131,0,34,0,193,0,64,0,113,179,0,0,51,0,242,0
slope_clamp D:0B38[40]  0,0,1,1,2,2,3,5,8,10,15,20,25,30,35,40, then 40 x24
cloud dy (0x1E7CA)      0x11, 0x14, 0x23, 0x26
first_mask D:0C04[17]   0xFFFF >> n ;  last_mask D:0C26[17]  0, 0x8000, 0xC000, ... 0xFFFF
road_palette D:19CE     000 00F 673 853 3BF EE2 743 48F D32 1D6 686 00F AAA 999 00B 009
                        E00 000 111 222 333 444 555 666 777 888 999 CCC FFF 821 B32 F66
loading_palette D:19CA  000 D04
cracks D:1646 counts    11,12,11,15,14,11,13;  pointers D:1654 -> 0x19280.. (data hunk D:1670..): the DOS
                        windscreen_cracks values exactly (x stored halved), port/spec/tables/windscreen_cracks.json
sin table 0x1216C       sin(i deg)*65536 for i = 0..90, entry 91 = 65535 (interpolation guard)
```

-----------------------------------------------------------------------------------------------------------

## 5. Hardware / OS dependencies and SDL3 replacement

| Dependency | Where | Port replacement |
|---|---|---|
| Two Views double-buffered with LoadView (`show_view`) | 0x1D484, 0x24ACA, crash, ending | two 320×200 5-bit index buffers; present = swap |
| Blitter: cookie-cut, XOR, rectangle set/clear, D=A row spans, first/last word masks | all drawing | software blits on the index buffers, **reproducing word granularity**: aligned blits round x down to 16; rect fills overwrite whole 16-px words (bits outside the span cleared); `fill_row_span` does too only with `g_original_bugs` (bug 5) |
| OwnBlitter/WaitBlit/DisownBlitter | render, 0x2097C, 0x1FDF4 | none |
| graphics `Move/Draw` into a RastPort (needle bitmap, cracks), `Text` (Pulling into, Loading) | 0x1F2EA, 0x1FBD8, 0x1D484, 0x24ACA | a Bresenham line matching graphics.library `Draw` (1-px, both ends inclusive); the ROM 8×8 topaz font (platform_video) |
| User copper list: sprite pointers at line −10, 32 colour moves at line 0x74 h 100 | 0x24D8A, 0x1FAD4, 0x1FB4A | two palettes: rows 0..0x74 use the road palette, rows 0x75.. the dash palette (switch on row 0x75; the mid-line-116 change is hidden under the hood shape) |
| LoadRGB4, 12-bit colours | 0x24D8A, fade | expand `0RGB` × 17 |
| Hardware sprites 0..7 (DMA from chip data, attached pairs, POS/CTL words) | §4.8 | software sprite layer drawn over the frame after the playfield: parse the segment chains exactly (h, v0, v1, attach) with hstart−0x80, vstart−0x2C; sprite colours 17..31 of the **dash** palette when below line 0x75, of the road palette above (the palette split applies to sprites too) |
| DMACON SPREN on/off | 0x1F5BA, 0x1F99A | sprite layer enable flag |
| exec tasks: AddTask/RemTask, SetTaskPri, Forbid/Permit, busy-wait handshake | 0x24E94, 0x24F3A, 0x1D392 | run the renderer synchronously in the frame loop: sim tick(s) first, then one render frame whenever the main loop would wait; the Forbid snapshot becomes a plain copy (see Timing) |
| WaitTOF / tick_count `D:03D8` (60 Hz VBL, NTSC); dos `Delay` (1/50 s) | render loop, radar, crash, ending | 60 Hz frame clock from `host.c`; `Delay(n)` = n/50 s of host time |
| MakeVPort/MrgCop/FreeVPortCopLists, ViewPort DyOffset (always 0 here) | 0x24D68, fade | nothing (DyOffset 0) |
| VHPOSR-seeded rand16 0x1530E | bugs | platform_video's rand16 |

-----------------------------------------------------------------------------------------------------------

## 6. Timing

* **Simulation**: the main task loop 0x1C900 runs one sim step per iteration and waits until 5 VBL have
  passed since the previous one → at most 12 steps/s (60 Hz NTSC VBL); slower if the work takes longer.
* **Rendering**: the Road Drawer task renders as fast as the CPU/blitter allow, but calls `WaitTOF` after
  each `show_view`, so at most 60 frames/s; it only runs while the main task waits (priority −1 vs 4). On a
  7 MHz A500 a frame probably takes several VBLs (open question), so frames and sim steps interleave
  irregularly. Each frame uses a consistent snapshot of the sim state (Forbid), except the gauges, which
  read the live speed/rpm.
* **Per render frame (frame-rate dependent)**: slot-car slides (−0x38 per frame), bug creation (1/1024 per
  frame above 85 mph) and flight, cloud drift, police light flash (every 2 police draws), the sub-unit scale
  and all drawing.
* **Per sim step**: knob glide (4 px / 8 px) and gate close delay (7 steps), the wheel-marker sprite.
* **Per VBL tick** (`D:03D8`): radar detector blink (lit 50 ticks = 0.83 s, dark 8 ticks = 0.13 s at 60 Hz;
  beep at each re-light when the level is > 0). The VBL server 0x118B2 (platform) also drives the gear shift.
* **Crash**: 7 steps, each redraw + show + copy + `Delay(2)` (dos.library: 2/50 s, not VBL-based).
* **Ending**: `note` after 300 VBL (5 s at 60 Hz) or input, then `Delay(10)` (0.2 s) and wait for fire/break.
* **Port recommendation**: 60 Hz host frames (NTSC, port/amiga/README.md *Decisions* 1); run the sim step
  every 5th frame (12 Hz, or when 5 frames have elapsed), render every frame. This reproduces the "fast CPU"
  behaviour; the real A500 render rate is an open question.

-----------------------------------------------------------------------------------------------------------

## 7. Differences from DOS

1. **Architecture**: DOS renders in the main loop with the sim in the int 8 ISR and composes the road window
   in a RAM buffer copied to VRAM; the Amiga renders in a separate exec task ("Road Drawer", pri −1)
   straight into double-buffered Views, with the sim in the main task at ≤12 Hz.
2. **Screen layout**: DOS road window rows 19–110 below a `roof` drawn once; Amiga road window rows 0–116
   with `roof`, `hood`, `post` and `mirr` re-blitted every frame, dashboard from `<car>Dash` below row 117.
   32 colours with a copper palette split at row 117 (road palette `D:19CE` above, car palette below).
3. **Projection** is completely different: DOS uses fixed per-row depth `Z[i]`/width `W[i]` tables, a
   divide, an atan table and a ×15 sine table; the Amiga walks with a geometric scale (×0xE8F5/65536 per
   row, sub-unit start from the position fraction), `y −= 8s + slope·s/4`, `x += sin(heading)·80·s` plus
   lateral parallax, heading clamp ±90°, slope clamp per row (table `D:0B38`).
4. **Rows**: 40 main / 30 mirror (DOS 39 / 24); the Amiga stops when the crest reaches the top of the clip.
5. **Road width**: the Amiga reads the record's first byte (DOS "flag", ignored by DOS) as two width codes:
   left half 0x1C0, right half 0x1C0..0x380; roads with a right half > 0x224 get white lane marks and a solid
   centre line. Shoulders are `0x6E·s` wide (DOS: W5 = 1.25 W).
6. **Road data**: identical to DOS byte for byte (110-record table, all five stage streams). The end of the
   stage (0xFF − 45) reads record 0 in both.
7. **Fill**: DOS builds per-scanline span arrays with crest culling and a Bresenham span interpolator; the
   Amiga fills each row's trapezoid immediately with one-line blits clipped at the crest (in the original, a
   stale step when a trapezoid is 2 lines tall and a whole-word overwrite at span ends: bugs 6 and 5, fixed by
   default).
8. **Colours**: sky/left side colour 4 (`0x3BF`), right ground 6, shoulders 12, road 13, centre line 5
   (yellow, 2 px, dashed by unit bit 2), lane marks 28. DOS: buffer colours 4/2/1/0/7 (probably screen 12,
   10, 9, 8, 15). The DOS centre dash is 1 px and phased by `dash_phase`.
9. **Horizon cliff**: DOS `clfa/clfo` at the cut row; Amiga `clf0` plus a colour-6 block right of it, drawn
   in painter order just before the first object nearer than the cliff row.
10. **Objects**: queue of up to 199 (x, y, code, scale) drawn LIFO, each clipped at its own base and lifted
    to the crest when behind a hill (DOS keeps the object's y and clips it to the crest). Objects in rows
    ≤ 6 are not queued (signs, posts) or are frozen at scale 0x9160 (traffic, rows 3..6; slots 0/2/3/4 visible
    there only with the bug 2 fix) and dropped (rows 0..2). DOS draws traffic at `bp == 2` at y 0x76.
11. **Signs**: codes 2..0xF on both sides (DOS 2..8): 9..0xC are drawn as gas-station signs (the table
    repeats `gas`), 0xD `pas`, 0xE `mrg`; DOS does not draw 9..0xE at all. Signs stand on `pol*` poles;
    DOS uses `pst*` posts.
12. **Posts**: `pst1-4` every 16 units at the left road edge (DOS: `pal/pol` poles at the left shoulder).
13. **Scenery**: three 64-entry position tables (`wed`, `rck`, `lin`) on the right, via the queue (DOS: one
    XOR pattern table by the dash counter, rows < 16, drawn immediately).
14. **Hazards**: drawn straight from the road records at every row, 4 lanes from the object byte's top bits,
    5 sizes (`rck oil pot gra`); DOS draws the hazard slot 12 only.
15. **Traffic**: row match on the integer unit only (DOS compares sub-unit positions); lateral ±0xE0 lanes
    with slide animation; size with hysteresis per car type (×0.828 / ×1.207); the mirror shows rear views
    of oncoming cars and front views of same-direction cars (`rx7` only there); police: `cpr` (main) /
    `cop` (mirror), light bars `clr`/`cpl` XOR every other draw, `cpb3/4` when stopped. The render task
    writes the lateral positions back (`D:0CC2`, `D:0D28`) for the sim.
16. **Mirror**: shows sign backs (`rsg0/1`) on poles, traffic and police; DOS draws only the type-0 sign mask
    and the post (DOS bug). The mirror uses the same row walker, so hazards, scenery (`wed rck lin`) and
    posts appear in it too (DOS mirror: no hazards, no scenery).
17. **Amiga only**: 4 parallax clouds moving with the world heading, bugs splatting on the windscreen,
    left-dip ground fill, lane marks, cliff block.
18. **Cockpit**: steering wheel 5 poses (`whl0..3` XOR over the centred picture, per-buffer state, any jump
    allowed) vs DOS 3 poses; wheel marker = hardware sprite 7 (fixed 4×4 dot, ±35° clamp, updated by the sim
    tick) vs DOS `dot` shape with save-under; gear knob = 4 hardware sprites gliding 4/8 px per sim step,
    gate closes 7 steps after arrival (DOS 13 frames, RAM buffer); gauges = hardware-sprite needles drawn
    with graphics `Draw` into a 32×51 bitmap and masked by the wheel-rim overlays `tcm*/spm*` (DOS: lines
    into an instrument buffer, then `ina/inl` overlays).
19. **Gauge indices**: tach index `max(min(rpm, +002), 800)/64` (DOS clamps to +004), speed index
    `max(speed−10, 0)` for every car (DOS `units_mode` case). Analog needles are recomputed every frame
    (the rpm cache D:1900 is not updated by 0x20AF4, so they always redraw; no visible effect, kept in both
    modes); digital cluster only on change, per buffer.
20. **Digital cluster** (Corvette): `inst` replaced, speed bar = vertical `sped` revealed by the top clip,
    tach bar = `tach` revealed by the right clip, XOR digits `dgt0-9`, wheel-rim overlays; DOS uses digit
    sprites and `tac1-3` segments.
21. **Radar detector**: level from the sim (`D:0DBE`), lit 50 VBL / dark 8 VBL with a beep at each re-light
    (DOS: `rad5..rad1` by distance to the cop, `tick & 8`, beep every frame).
22. **Ticket**: `tick` when `D:0D74 ≥ 0x1E` (DOS `cop_state == 6 && ticket_flag == 0`).
23. **"Pulling into …"**: graphics Text at (0x30, 0x55), pens 8/0, into the back view; DOS prints centred at
    y 0x50 and suppresses the dealership text once the ending was shown.
24. **Crash**: same 7 crack sets as DOS, drawn with `Draw` in colour 28 on the full frame, cockpit shapes
    re-blitted over them, each step shown with `Delay(2)` (DOS: 7 immediate redraws into the road buffer);
    GAME OVER uses `game` (DOS `govr/gvrm`).
25. **Ending**: `pics/EndGame` in the top 117 rows keeping the dashboard, needles reset, `note` after 300 VBL
    or input (DOS: `deal` + `note` shapes, two fire presses).
26. **Fade**: stage exits fade both palettes to black in 16 steps (DOS has no fade).

-----------------------------------------------------------------------------------------------------------

## 8. Open questions

1. **Render rate on a real A500**: the Road Drawer's frame time (40+30 rows of one-line blits, 199-object
   queue, clouds, overlays) is unknown; the frame-rate-dependent effects (slides, bugs, clouds, police flash)
   depend on it. An emulator measurement is needed to pace the port faithfully.
2. **Row 3..6 slot cars** (`slot_base_x` = low word of `K·half_right` + centre, missing `swap`): *resolved*,
   README bug 2: fixed by default (high word); `--original-bugs` keeps the cars invisible (§4.3, §4.5).
3. **`front = &viewA` in the crash** (0x1FC02) can leave `D:24CE == D:24C8` until the next `show_view`; no
   visible effect was found, but the port must keep the same buffer identity sequence.
4. **Quick path of `stage_display_setup`** (shapes still loaded) does not reload the `<car>Dash` picture:
   it relies on the Views still holding the dashboard after the gas station (game_flow should confirm what
   0x147E4 does to the Views). *Merge:* game_flow's stage_results 0x147E4 draws the gas picture into the back
   View, shows it, and at the end copies the now-hidden cockpit View back onto the shown one (`view_copy(back,
   front)` after `show_view` swapped the roles), so the dashboard survives; only the too-slow path zeroes
   `D:24D2`.
5. **`wed0-3` have 4 planes** in `Road.Shp`; the blitter always copies 5 planes, so the fifth plane comes
   from the bytes after the shape (inside the mask, i.e. visible). Check against the archive layout.
6. **Needle mask rows beyond the overlay's height** read the overlay's next plane (§4.8.2); whether the
   shipped needle boxes ever reach those rows is unchecked.
7. **`scale_index5` for scales ≥ 0xF000** wraps to the smallest size; only row 0 can have such a scale
   (hazards at row 0 are drawn at the crest line with the smallest shape, under the hood).
8. **Mirror pixel writes** (centre line / lane marks) are not clipped to x ≥ 0xF0.
9. **FORMATS.md corrections**: car +17A/+324 "direction 0" is a vertical bar clipped from the top (x0 is the
   bottom y); the needle-box sprites are confirmed (sprites 0/1 tach at +176/+178, 2/3 speed at +172/+174);
   the DOS "flag" byte of the road records is a width code. Owners of FORMATS.md should update it.
10. **Sprite colours**: which palette the sprites use depends on the line (the copper split); the needles are
    below line 117 (dash palette), the knob too. The marker dot and knob colours were not checked against a
    screenshot.
11. `D:0DB0/0DB4/0DB8` (three more cloud positions) and the code at 0x1EA9A..0x1EADF are dead; `rpl0/1`,
    `rckF..H`, `bug0`, `bug2`, `bugE`, `cldC`, `cldD` are never drawn.
12. Whether `D:2842` (ViewPort DyOffset shake) is ever non-zero: no writer other than the clears in 0x24CE4
    was found in overlay 2; root code was not searched exhaustively. *Merge:* the whole image was searched for
   `d16(An)` writes to a ViewPort's +0x1E: besides the clears at 0x24CFE/0x24D06 there are only overlay 1's
   showroom scroll stores (0x1C6A2, 0x1C6EE, 0x1C720). 0x1D392 copies the shown ViewPort's DyOffset and zeroes
   it outside −10..10, so D:2842 is 0 in practice; indirect writes (e.g. through a computed pointer) were not
   ruled out.
13. **Ownership** (settled in the merge, port/amiga/symbols.csv): 0x1CCF6 traffic_reset and 0x1CD72
    knob_update → drive_sim; 0x247B2 update_wheel_marker, 0x1CF76 dealership_ending, the Road Drawer
    (0x1D484, 0x24E94, 0x24F3A, 0x24F9A) and the copper/palette helpers 0x24D68/0x24D8A/0x24E52 → drive_scene;
    0x24ACA stage_load / 0x24CE4 stage_unload → game_flow (drive_scene's names are aliases).
