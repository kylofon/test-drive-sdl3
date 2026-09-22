# drive_sim — Amiga driving simulation (overlay 2)

Target: `td` (Amiga, Aztec C). Addresses are image addresses (base 0x10000); globals `D:xxxx` are offsets into the
data hunk (A4 = 0x1FC0E, `d16(A4)` = `D:(0x7FFE + d16)`). `int` is 16 bits, `long` 32 bits, big-endian.
Confidence as in `port/RE_GUIDE.md`. Ground truth is `tools/amigaidx.py dis`; `port/amiga/decomp/td.c` was used
as a cross-check only. **Almost all of this code is hand-written assembly with register conventions** (A2 = road
record, D7 = road unit, results in D0-D3), which the Ghidra output hides, so every pseudocode block below was
written from the disassembly. DOS reference: `port/spec/simulation.md` (cited as "DOS §n").

## 1. Overview

The Amiga simulation is **not** a timer interrupt like DOS. It is ordinary code called from the drive loop
`0x1C900` (game_flow) once per **drive frame**, and the frame is paced to **5 vertical blanks**: after the
simulation of a frame the loop calls `WaitTOF()` (graphics LVO −0x10E) `last + 5 − tick_count` times, then sets
`last = tick_count` (D:03D8, +1 per VBL in the Ticks server). The frame is therefore 5 VBL whenever the main task
finishes its work inside that time. The work is small, because **drawing runs in a separate exec task**, `Road
Drawer` (0x24F9A → 0x1D484, priority −1, created by 0x24E94), which renders a snapshot of the simulation state as
fast as the CPU allows and is not synchronised with the frame.

**Tick rate.** 5 VBL = **12 Hz on NTSC** (10 Hz on a PAL machine). The game was designed for NTSC:
* the stage time shown on the results screen is `frames / 12` seconds (0x1C900 → 0x16ED8(frames, 12) → 0x147E4
  "it took you %2d seconds");
* the sample and note periods use the NTSC colour clock 0x369E99 (platform_audio);
* the per-tick constants that exist in both versions are the DOS ones unchanged (DOS runs 12.5 Hz, §6).

On a PAL machine the whole drive runs at 10/12 speed and the displayed times are 20 % too short. The port runs
the NTSC rates: 60 Hz VBL, 12 Hz drive frames (port/amiga/README.md, *Decisions* 1; all specs use 60 Hz). All
code timing is in VBLs, so it is one host constant.

**Units** (all new; none is the DOS encoding):

| Quantity | Global | Encoding |
|---|---|---|
| Speed | D:28A6 | signed long 16.16 **mph**; clamped ≥ 0 after each engine update |
| Advance per frame | D:28B6 | `speed >> 6` (16.16 road units). One road unit per frame = 64 mph |
| Road position | D:28AE | long 16.16 road units; high word = index into the stage's road byte stream |
| Lateral position | D:2896 | long 16.16; high word `x`, **positive = right**; start 100 (0x640000); 0 = centre line; same-direction lane at +0xE0/2, oncoming lane at −0xE0/2 (see §4.11) |
| Steering angle | D:28AA | long 16.16 **degrees**; `curve/2` tracks the road (D:19B8) |
| rpm | D:191A | the **high word** is rpm; the low word is a fraction left over from `mulu` |
| Heading | D:28C6 | long 16.16 degrees, 0..359, sum of `curve/8` per unit (scenery only) |

The road data are identical to DOS: the record table at 0x20F08 (0x6E × `[flag, curve, pitch, object]`) and the
five stage streams (0x210C0, 0x218F2, 0x22454, 0x22F72, 0x239E5) are byte-for-byte the DOS tables at DS:2B70 and
DS:2D28.. (verified by comparison). Only their interpretation differs.

**Call graph (per drive frame, main task):**

```
0x1C900 drive_main (game_flow) ── frame loop
 ├─ D:0D70 / D:0D72 autopilot flags
 ├─ if D:0D74 == 0: 0x20CB0 sim_controls
 │     ├─ 0x20826 engine_update ── 0x207A4 shift_effects ── 0x2076C rpm_from_speed / 0x20780 speed_from_rpm
 │     │                        └─ 0x26D4E engine_sound_update (platform_audio)
 │     ├─ 0x153E4 joy_read_fire / 0x153EC joy_read_dir
 │     ├─ fire held: 0x1EDCE shift_gear(±1)          (no physics this frame)
 │     ├─ else: 0x2484C lateral_physics
 │     │     ├─ 0x24924 steering ── 0x2498E steer_steps ── 0x249CC edge_kicks
 │     │     │                   └─ 0x247B2 steering-wheel marker (drive_scene)
 │     │     ├─ 0x24A04 grip_check ── 0x12056 abs, 0x24AA8 skid_drift, 0x2076C
 │     │     ├─ 0x1D31A clamp_word
 │     │     └─ 0x1DB36 road_edge_check
 │     └─ road_pos += advance
 ├─ 0x1E53A road_advance ── per unit crossed: 0x1D32A road_record, 0x1DC2E road_object, 0x1DCDC heading_step,
 │                          0x2481C curve_integral
 │        0x1DC2E ── 0x1DC08 radar_zone_start, 0x1DCA0 speed_sign, 0x1DB90 traffic_spawn (0x1530E rng),
 │                   hazard test, 0x1E6A6 shoulder_bump ── 0x1E73A marker_test, 0x1E720 rumble_slow
 ├─ 0x1DDEA traffic_update (same-direction cars, police car, oncoming cars)
 ├─ WaitTOF until 5 VBL
 ├─ 0x1CD72 knob_update (shift completion; drawing part: drive_scene)
 ├─ 0x1544E break check, 0x10462 poll_input (keys, game_flow/platform)
 ├─ D:0B2E = near stage end
 └─ 0x1EC1A radar_zone (police spawn)

Ticks VBLInt 0x118B2 (every VBL, platform): tick_count++; gate-mode shifting → 0x1EE76 gate_select, 0x20826
Road Drawer task 0x1D484 (drive_scene): snapshot → render → writes D:0D94/D:0D96 road widths and the
  traffic lateral positions D:0CC2/D:0D28 that the collision tests above read; 0x1EC94 radar lamp/beep
```

## 2. Function table

"DOS equivalent" names come from `port/symbols.csv`. Functions of other specs are listed with "see".

| Amiga addr | name | signature | purpose | DOS equivalent | confidence |
|---|---|---|---|---|---|
| 0x1C900 | drive_main | int(int car) | Stage loop, frame pacing, clock, exits. **See game_flow**; timing/sim parts in §4.1 | 0x1DC0 run_stage | verified |
| 0x1CCF6 | traffic_reset | void(void) | Clears 0x1E89A[256], traffic slots, police state, radar | part of 0x1F93 reset_car_state | verified |
| 0x1CD72 | knob_update | void(void) | Moves the knob 4 px (x) / 8 px (y) per frame; ends the shift; hides the gearbox | 0x3DDB sim_shift_knob_anim | verified (drawing: drive_scene) |
| 0x1D31A | clamp_word | asm(d0 lo, d1 hi, a3 *w) | `*a3` (word) clamped to [d0, d1] | – | verified |
| 0x1D32A | road_record | asm(d7 unit) → a2 | `a2 = &REC[ROAD[d7]]`; record 0 outside the stage; 0xFF moves the stage end | inline REC(ROAD[pos]) in 0x40FE | verified |
| 0x1DB36 | road_edge_check | asm | Off-road crash tests against the renderer's road widths; wide-road slow lane | off-road test in 0x40FE sim_advance_unit | verified |
| 0x1DB90 | traffic_spawn | asm(a2, d2, d7) | Spawn a same-direction or oncoming car 40 units ahead (with the slot-index bug, fixed by default: README bug 1) | 0x467D sim_spawn_object (traffic part) | verified |
| 0x1DC08 | radar_zone_start | asm(a2) | Radar trap object: chance test, starts the radar zone D:0DBE | 0x467D (k == 1 part) | verified |
| 0x1DC2E | road_object | asm(a2 rec, d7 unit) | Object dispatch for the unit just entered | 0x467D sim_spawn_object + sign test in 0x40FE | verified |
| 0x1DCA0 | speed_sign | asm | Speed-limit sign: sets the limit and every traffic speed | sign test in 0x40FE | verified |
| 0x1DCDC | heading_step | asm(a2) | D:28C6 += curve/8 degrees, wrapped 0..359 | – (DOS keeps heading in the renderer) | verified |
| 0x1DD10 | pitch_step | asm(a2) | D:28CA += pitch, clamp ±30. **No caller (dead)** | – | verified |
| 0x1DDEA | traffic_update | void(int unit) | Same-direction cars, police FSM, oncoming cars, collisions, removal | 0x427F sim_traffic_update + 0x438A sim_cop_fsm + 0x455F sim_object_cleanup | verified |
| 0x1E53A | road_advance | void(void) | Walks the units crossed this frame: objects, heading, curve integral | 0x40FE sim_advance_unit loop | verified |
| 0x1E5C6 | row_road_widths | asm | Road half-widths per row from REC[0]; row 0 → D:0D94/D:0D96. **See drive_scene** | – | verified |
| 0x1E6A6 | shoulder_bump | asm(d7) | Lane-marker and shoulder tests (bump sound flag, rumble slow-down) | – | verified |
| 0x1E720 | rumble_slow | asm | speed −= 0x3000; rpm from speed unless shifting | – | verified |
| 0x1E73A | marker_test | asm(d2) | D:0D9A = −1 if 0x4C ≤ \|d2 − 10\| ≤ 0x70 | – | verified |
| 0x1EC1A | radar_zone | void(long pos) | Advances the radar zone; speeding → police car spawn | 0x455F (trap trigger / chase start) | verified |
| 0x1EC94 | radar_lamp | void(void) | Radar detector lamp and beep (Road Drawer). **See drive_scene** | part of 0x35C6 | verified |
| 0x1EDCE | shift_gear | void(int delta) | gear += delta (clamped 0..num_gears); knob target; D:26FC | 0x3CB8 gear-delta branch + set_knob_target | verified |
| 0x1EE76 | gate_select | void(int node) | Gate-mode shift: gear, ratio, knob target, gate row/col | 0x3CB8 gate branch | verified |
| 0x2076C | rpm_from_speed | asm | D:191A = ((D:28A6 >> 8) & 0xFFFF) × ratio (rpm = high word) | 0x3FAD sim_update_rpm | verified |
| 0x20780 | speed_from_rpm | asm | speed high word = (rpm << 8) / ratio | – | verified |
| 0x207A4 | shift_effects | asm | On shift completion: clutch dump (neutral→1st), 1st→2nd chirp, rpm resync | 0x3DDB shift completion (clash / dump) | verified |
| 0x20826 | engine_update | asm | rpm, torque/drag, brake, neutral, speed, advance; sound update | 0x3EAA sim_engine | verified |
| 0x20CB0 | sim_controls | void(void) | Over-rev, autopilot/demo, fire=shift, joystick → pedal, physics, position | 0x3BEA sim_tick + 0x3CB8 | verified |
| 0x20D68 | car_record_copy | void(void) | Car record (D:2548) → D:1924..D:1982 (FORMATS.md) | DOS 0x10E2 car loader (RE_GUIDE) | verified |
| 0x20E70 | stage_road_select | void(int stage) | Road stream, stage end D:1984, par tables | 0x1F4E stage_init_road_ptr | verified |
| 0x2481C | curve_integral | asm(a2) | D:19AA += curve × distance on this unit | – (DOS: road_curve per unit) | verified |
| 0x2484C | lateral_physics | asm | Curve drift, steering force, grip, lateral position, view heading | 0x3FE8 sim_motion + lateral part of 0x40FE | verified |
| 0x24924 | steering | asm | Steering angle from the joystick, wheel marker | 0x3D7D sim_steering | verified |
| 0x2498E | steer_steps | asm → d0..d3 | Steering step sizes and edge kicks | – | verified |
| 0x249CC | edge_kicks | asm → d2, d3 | 0x60000 kicks, zeroed near the road edges | – | verified |
| 0x24A02 | (rts) | – | Empty stub called from the renderer | – | verified |
| 0x24A04 | grip_check | asm | Hazard grip reduction, skid amount, skid clamp and slow-down | grip part of 0x3FE8 | verified |
| 0x24AA8 | skid_drift | asm | View heading += skid × car+00A >> 8 | skid drift in 0x40FE | verified |
| 0x24ACA | stage_load | void(int car) | Loads the stage; initial x/steer/speed/heading. **See game_flow** | 0x4792 stage_enter_install_isr | verified (init values) |
| 0x118B2 | ticks_vbl_server | VERTB server | tick_count++, gearbox hide, **gate-mode shifting at 60 Hz**. Installed by 0x1180E (platform_video) | – | verified |
| 0x11872 | vbl_read_fire | asm → d0 | CIA-A PRA bit 7 inverted (port-2 fire) | – | verified |
| 0x11886 | vbl_read_dir | asm → d0 | JOY1DAT → direction via D:03DC | – | verified |
| 0x153E4 | joy_read_fire | int(void) | CIA-A PRA bit 7 inverted → D:2858 | 0x5C24 input_poll_drive (part) | verified |
| 0x153EC | joy_read_dir | int(void) | JOY1DAT → 0..8 via table 0x1543E → D:2512 | 0x5C24 input_poll_drive (part) | verified |
| 0x1530E | rng_next | int(void) | `s = (s·0x1AFB + 0x1FCCD) ^ VHPOSR`, seeded from VHPOSR | 0x8BAF rand8 | verified |
| 0x12056 | abs_w | asm d0 → d0 | \|d0\| (word); d1 untouched | – | verified |
| 0x1205E | abs_l | asm | \|d0\| (long) | – | verified |
| 0x12108 | sin_deg | asm(d0 16.16 deg) → d0 | Interpolated sine from the table at 0x1216C; fold >90° | DS:22F2 sine use | verified |
| 0x12146 | cos_deg | asm(d0 int deg) → d0 | Cosine from the same table | – | verified |
| 0x16ED8 | ldiv | asm(d0, d1) → d0 | Signed long division (Aztec runtime) | CRT | verified |
| 0x247B2 | wheel_marker | asm | Steering-wheel marker angle 2×steer clamped ±35°. **See drive_scene** | 0x35C6 wheel part | verified |
| 0x1D484 / 0x24F9A | road_drawer_loop / entry | task | **See drive_scene** | – | verified |
| 0x1D560 | stage_score | long(long frames, long par, int base) | **See game_flow** | – | verified |
| 0x1FBD8 | crash_sequence | void(void) | **See drive_scene** | 0x392C crash_windscreen_sequence | likely |
| 0x26C50 / 0x26C70 / 0x26D16 / 0x26D4E | radar_beep / engine_sound_start / engine_sound_fade_out / engine_sound_update | | **See platform_audio** | | |

## 3. Globals table

"W" = written by, "R" = read by. BSS globals start at 0 at program start and are reset only where stated.

| D: | name | type | meaning | W | R | DOS equiv |
|---|---|---|---|---|---|---|
| 28A6 | speed | long 16.16 mph | Car speed | 20826, 24A04, 1E720, 20780, 1C900 | all | DS:0927 |
| 28B6 | advance | long 16.16 units | speed >> 6, per frame | 20826, 1C900 | 20CB0, 2484C, 1EC1A, 1DDEA | – |
| 28AE | road_pos | long 16.16 units | Position; starts at 0x1E0000 each stage | 20CB0, 1DDEA, 1C900 | all | DS:0906 + DS:0912 |
| 28CE | road_pos_done | long | Position already processed by 1E53A; −1 = none | 1E53A, 1C900 | 1E53A | DS:0908 |
| 2896 | car_x | long 16.16 | Lateral position, + = right; 0x640000 at stage load | 2484C, 24ACA | sim, renderer | DS:0910 (sign flipped) |
| 289A | car_x_snap | long | Renderer's copy of car_x (0x1D392) | drive_scene | 1DB36 | – |
| 28AA | steer | long 16.16 deg | Steering angle, unclamped | 24924, 24ACA | 2484C, 247B2, 2498E | DS:0914 |
| 28C6 | heading | long 16.16 deg | 0..359 | 1DCDC, 24ACA | scenery (1E758) | – |
| 28CA | pitch_acc | long | Cleared only (writer 1DD10 is dead) | 24ACA | – | – |
| 191A | rpm | word (+ fraction word) | rpm (high word) | 2076C, 20826, 207A4 | 20CB0, gauges, sound | DS:091B |
| 191E | gear | int | 0 = neutral .. num_gears | 1EDCE, 1EE76, 1C900 | 20826, 207A4, sound | DS:0A78 |
| 1920 | ratio | int | car ratio of `gear` (updated in neutral too) | 1EDCE, 1EE76 | 2076C, 20780, 20826 | DS:0916 |
| 1922 | pedal | int | +1 gas, −1 brake, 0; set **after** the physics, used by the next frame's engine update | 20CB0 | 20826, 207A4, sound | DS:0A79 |
| 1604 | overrev_frames | int | Consecutive frames with rpm > rev limit | 20CB0 | 20CB0 | – |
| 15FE | squeal_env | int | Chirp envelope start (0 dump, 0xB 1st→2nd) | 207A4 | platform_audio | DS:08F4 |
| 1600 / 1602 | prev_gear / prev_shifting | int | Gear and D:26FC of the last engine update | 207A4 | 207A4 | – |
| 26FC | shifting | int | Knob moving to a new gear (clutch in) | 1EDCE, 1EE76, 1CD72 | 20826, 207A4, 20CB0, 1E720 | DS:0A7B |
| 24B6 / 24B2 | knob_target_x / _y | int | Knob target (car +020 or gate +03C, +0x80/+0x2C − dash origin D:257C+4/+6) | 1EDCE, 1EE76 | 1CD72, 118B2 | DS:0A81 / DS:0A83 |
| 24B8 / 24B4 | knob_x / knob_y | int | Current knob position | 1CD72, 1EDCE, 1C900 | 1CD72, 118B2 | DS:0A7D / DS:0A7F |
| 24B0 | gate_mode | int | O key: gate shifting in the VBL server | 0x10462 | 20CB0, 118B2 | DS:0921 |
| 03EE / 03F0 | gate_row / gate_col | int | Gate node = row×4 + col; reset 0/1 per stage | 1EE76, 1C900 | 118B2 | DS:0920 |
| 03EC | gate_last_dir | int | Last joystick direction seen by 118B2 | 118B2 | 118B2 | – |
| 0B34 | gearbox_always | int | D key: gearbox permanently shown | 0x10462 | 118B2, 1CD72 | DS:08BE |
| 0B30 / 0B31 | gearbox_show | byte ×2 | Show gearbox (per view buffer) | 20CB0, 1EDCE, 118B2, 1CD72 | drive_scene | – |
| 24BA | gearbox_hide_delay | int | 7 after a shift; −1 per frame at rest | 20CB0, 1CD72 | 1CD72, 118B2 | DS:091F |
| 1916 | fire_prev | int | Fire was held last frame | 20CB0 | 20CB0 | DS:0A77 |
| 1918 | dir_prev | int | Joystick direction of the last frame | 20CB0 | 20CB0 | – |
| 2512 | joy_dir | int | 0 none, 1 up .. 8 up-left (title_select) | 153EC, 20CB0 | 20CB0, 24924 | – |
| 2858 | joy_fire | int | Last fire read | 153E4 | – | – |
| 19AA | curve_acc | long 16.16 | Σ curve × distance over this frame's travel | 1E53A, 2481C | 2484C | DS:0919 (per unit) |
| 0D8A | seg_frac | int | Distance fraction for 2481C (0 = whole unit) | 1E53A | 2481C | – |
| 19A2 | yaw_force | long | curve_acc − lat_force/4 | 2484C | 2484C | DS:090A |
| 19A6 | lat_force | long 16.16 | Lateral force: steer × advance × 8 + kicks, clamped to ±grip | 2484C, 24924, 24A04 | 24A04, 2484C | – |
| 19AE | car_x_new | long | Candidate car_x (clamped ±1000) | 2484C | 2484C | – |
| 19B2 | lat_sign | int | High word of lat_force before the grip test | 24A04 | 24A04, 24AA8 | – |
| 19B4 | view_yaw | long 16.16 | Heading offset of the view (skid drift + yaw_force/16) | 24A04, 24AA8, 2484C | renderer 2472A | DS:090C |
| 19B8 | steer_track | long 16.16 deg | Steering that exactly compensates the curve drift (= curve/2) | 2484C | 2498E | −road_curve |
| 19BC | skid_amount | int | clamp(\|lat\| − grip, 0, 0x40); squeal volume | 24A04 | 24AA8, platform_audio | DS:0924 |
| 19BE | bump_edge | int | {1,0,−1,0}[hazard & 3] for the bump sound | 24A04 | platform_audio | – |
| 19C4 | steer_prev | long | steer before 24924 (dead path only) | 24924 | 24924 | – |
| 0B36 | steer_lock | int | **Never written** (init 0): autopilot steering branch in 24924/2484C is dead | – | 2484C, 24924 | – |
| 0D80 | hazard_hit | int | Hazard object byte hit on this frame's units | 1DC2E | 24A04 (clears) | DS:09A5 |
| 0D94 / 0D96 | road_left_w / road_right_w | int | Road half-widths at the car's row (0x140 + 0x40·n from REC[0]) | drive_scene 1E5C6 | 1DB36, 1E6A6, 249CC | – |
| 0D9A | bump_flag | int | Lane marker / shoulder touched | 1E6A6, 1E73A | platform_audio | – |
| 0D9C | first_unit | int | −1 at frame start; only the first unit tests the shoulder | 1E53A, 1E6A6 | 1E6A6 | – |
| 282E | crash | int | 0; 1 crash; 2 hit the police car (game over) | 20CB0, 1DB36, 1DDEA, 1C900 | 1C900 | DS:0929 = 3 |
| 0B2E | near_end | int | stage_end − unit < 0x50 → autopilot to the gas station | 1C900 | 20CB0, 1D484 | DS:0929 = 2 |
| 0D70 | autopilot | int | demo or near_end: traffic ahead pushes the car back instead of crashing | 1C900 | 1DDEA | – |
| 0D72 | lane_hold | int | autopilot, or police tailing ≥ 0x46 frames: x steered to 0x50, squeal muted | 1C900 | 2484C, platform_audio | – |
| 1984 | stage_end | int | Unit of the 0xFF terminator − 45 | 20E70, 1D32A | 1C900, 1DDEA, 1D32A | DS:092A |
| 1986 / 198A | road_stream / road_records | ptr | 0x210C0.. / 0x20F08 | 20E70 | 1D32A | DS:6361 / DS:2B70 |
| 198E / 1992 / 1996 | stage_par / stage_par2 / stage_base | long / long / int | {700,1100,1200,1100,1500}, {3000,2800,3500,4000,4500}, stage+4 (scoring, game_flow) | 20E70 | 1C900 | – |
| 0C6E | sd_pos | long[6] | Same-direction car positions (16.16); **slot 5 = police car**; 0 = empty | 1DB90, 1DDEA, 1EC1A | 1DDEA, renderer | DS:096D |
| 0C92 | sd_speed | long[6] | Advance per frame; init 0xAAAA 0xCAAA 0xEAAA 0x9AAA 0x7AAA, 0 | 1DCA0, 1DB36, 1DDEA, 1EC1A | 1DDEA | DS:0A1B |
| 0CAA | sd_dodge | int[6] stride 4 | Sideways dodge offset (police pushing cars); decays in the renderer | 1DDEA, drive_scene | drive_scene | DS:0A29 |
| 0CC2 | sd_lane | {int lat, int flag}[6] | lat written by the renderer (see §4.11); flag = car placed behind the player | drive_scene, 1DDEA | 1DDEA | – |
| 0CF2 | on_pos | long[5] | Oncoming car positions | 1DB90, 1DDEA | 1DDEA, renderer | DS:0945 |
| 0D14 | on_speed | long[5] | Init 0xAAAA 0xCAAA 0xEAAA 0xAAAA 0xAAAA | 1DCA0 | 1DDEA | DS:0A1B |
| 0D28 | on_lane | {int lat, int pad}[5] | lat = −0xE0 (renderer) | drive_scene | 1DDEA | – |
| 0C82 / 0CA6 | cop_pos / cop_speed | long | = sd_pos[5] / sd_speed[5] | 1EC1A, 1DDEA | 1DDEA | DS:0A2D / DS:0A25 |
| 0CD8 | cop_tailing | int | = sd_lane[5].flag | 1DDEA | 1DDEA | – |
| 0D76 | cop_tail_frames | int | Frames the police car has sat behind the player | 1DDEA | 1DDEA, 1C900, 1DB90 | DS:0A28 |
| 0D78 | cop_timer | int | Pass/lead/stop animation counter | 1DDEA | 1DDEA, renderer | DS:0A27 |
| 0D7A | cop_mode | int | 0 chase, 10 passing, 15 braking | 1DDEA | 1DDEA, renderer | DS:0A23 |
| 0D74 | ticket_frames | int | Frames stopped by the police; ≥ 0x1E: ticket shown, car released | 1DDEA | 1C900 (skips 20CB0), 1E63A | DS:0A23 = 6 |
| 0DBE | radar_zone_ctr | long | High word 0 = off, 1..7 through the trap zone | 1DC08, 1EC1A, 1DDEA | 1EC1A, 1EC94 | DS:099D |
| 0DBC | speed_limit | int | 30/55/65 from the last sign; 0 until the first sign | 1DCA0 | 1EC1A, 1DB36 | DS:0A21 |
| 0D86 | speed_limit_table | u8[3] | {0x1E, 0x37, 0x41} = 30, 55, 65 for signs 5, 6, 7 | data | 1DCA0 | DS:0A1B |
| 0DC4 | radar_blink | int | Lamp period 0x32 VBL (constant) | 1EC1A | 1EC94 | – |
| 1606 | drag_table | u8[64] | Identical to DOS DS:0AC5 | data | 20826 | DS:0AC5 |
| 1924.. | car fields | | +000 num_gears D:1924, +002 D:1926, +004 rev_limit D:1928, +006 D:192A, +008 grip D:192C, +00A skid_drift D:192E, +010 D:1934, ratios D:1936, knob xy D:193A, gate xy D:193E, gate table D:1942, node→gear D:1946, torque D:194A | 20D68 | sim | DS:268F.. |
| 2816 | demo_mode | int | Attract mode (title_select) | game_flow | 20CB0, 1DB90, 1EC1A, 1C900 | DS:0084 |
| 24C6 | cars_left | int | 5 per game; −1 per crash, 0 when hitting the police | 1C900 | 1C900 | DS:78E6 |
| 24CC | stage | int | 0..4 (demo starts at 3) | 1C900 | 1EC1A, 20E70 | – |
| 2848 / 284A | sd_enable / on_enable | int | Set to 1 per stage, never cleared (debug switches) | 1C900 | 1DB90 | – |
| 2830 | no_crash | int | **Never written** (BSS 0): crash-cancel in 1C900 is dead | – | 1C900 | – |
| 1BD6 / 1BD8 | rng_state / rng_seeded | int | RNG | 1530E | 1530E | DS:6520 |
| 1C900 locals −$24, −$2C | stage_frames / speed_sum | long | Clock (starts at 1) and Σ mph while the clock runs | 1C900 | 1C900 | DS:80A4 |

## 4. Pseudocode

Types: `i16/u16/i32/u32`; `HI(l)` = high word of a long, `LO(l)` = low word. Word writes to `HI()` keep the low word.
`g_original_bugs` is the port's `--original-bugs` flag (not an Amiga global): where the pseudocode tests it, the
`g_original_bugs` branch is the original behaviour and the other branch the default fix (port/amiga/README.md,
*Original bugs*; this spec owns bugs 1 and 7).
Comparisons are signed unless marked `(u)`.

### 4.1 Frame loop (sim parts of 0x1C900, game_flow)

```c
/* per stage (0x1C94A) */           road_pos = 0x1E0000; speed_sum = 0; stage_frames = 1; stage_road_select(stage);
/* per stage and after a crash (0x1C968) */
traffic_reset(); near_end = 0; clock_on = 0; pedal = 0; crash = 0; advance = 0; speed = 0; rpm_l = 0;
D:1900 = -1; gear = 0; gate_row = 0; gate_col = 1; road_pos_done = -1;
stage_load(car);                     /* 0x24ACA: car_x = 0x640000, steer = heading = speed = 0 */
shift_gear(0); knob = target; road drawer released (D:24AE = 0);
song_stop(); engine_sound_start(); last = tick_count;
do {
    if (cop_tail_frames < 0x46) { autopilot = (demo_mode || near_end); lane_hold = autopilot; }
    else lane_hold = 1;
    if (ticket_frames == 0) sim_controls();          /* no controls, physics or motion while stopped */
    road_advance();
    if (gear != 0) clock_on = 1;                    /* sticky */
    if (clock_on) { speed_sum += (i32)speed >> 16; stage_frames++; }
    traffic_update();
    for (i = 0, n = (i16)(last + 5 - tick_count); i < n; i++) WaitTOF();
    last = tick_count;
    knob_update();
    if (break_pressed()) { quit = 1; break; }        /* 0x1544E */
    poll_input();                                    /* 0x10462: keys S M D O Ctrl-R ... */
    near_end = ((i32)stage_end - HI(road_pos) < 0x50);
    radar_zone(road_pos);
    if (no_crash && crash) crash = 0;               /* dead: no_crash is never set */
} while (HI(road_pos) < stage_end && !crash && !abort_key_D0346
         && !(demo_mode && (joy_read_fire() || ldiv(stage_frames, 0x226) != 0))
         && (speed > 0x110000 || !near_end));
engine_sound_fade_out();
/* crash: stage_frames += 0xF0; cars_left--; if (crash > 1) cars_left = 0; crash_sequence(); ...
   stage done: score = stage_score(stage_frames, stage_par, stage_base); time shown = stage_frames / 12 s;
   average speed = speed_sum / stage_frames (game_flow) */
```

### 4.2 Controls — `sim_controls` 0x20CB0

The code at 0x20C1E / 0x20C78 / 0x20C94 (inside the 0x20AF4 range of the index) belongs to this function.
`DIR_PEDAL[10]` at 0x20D5E = {0, 1, 1, 0, −1, −1, −1, 0, 1, 0} (up, up-right and up-left = gas; the three down
directions = brake; left/right = none).

```c
void sim_controls(void) {
    engine_update();                                 /* uses last frame's pedal */
    pedal = 0;
    if ((i16)rev_limit < (i16)HI(rpm)) {            /* D:1928 < rpm */
        if ((u16)++overrev_frames < 10) goto no_reset;
        crash = 1;                                   /* blown engine after 10 frames */
    }
    overrev_frames = 0;
no_reset:
    if (near_end) {                                  /* autopilot: brake, then downshift */
        if (!shifting && (i16)HI(rpm) <= 0xFA0) goto downshift;
        joy_dir = 5;  d0 = 5;
    } else if (demo_mode) {
        if (!shifting && gear < num_gears && (i16)HI(rpm) > 6000) goto upshift;
        joy_dir = 1;  d0 = 1;
    } else {
        if (joy_read_fire()) goto fire;
        d0 = joy_read_dir();
    }
    dir_prev = d0;
    lateral_physics();
    if (DIR_PEDAL[joy_dir]) pedal = DIR_PEDAL[joy_dir];
    fire_prev = 0;
    road_pos += advance;
    return;
fire:                                                 /* 0x20C1E: clutch, joystick shifting */
    pedal = 0; gearbox_hide_delay = 7; gearbox_show = 0xFFFF;
    if ((!fire_prev || !dir_prev) && !gate_mode) {   /* one shift per stick deflection */
        dir_prev = joy_read_dir();
        if (DIR_PEDAL[joy_dir]) shift_gear(DIR_PEDAL[joy_dir]);   /* up = +1, down = -1 */
    }
    fire_prev = 1;
    dir_prev = joy_read_dir();
    road_pos += advance;                             /* no lateral physics while fire is held */
    return;
upshift:   pedal = 0; gearbox_hide_delay = 7; gearbox_show = 0xFFFF; shift_gear(+1);  return; /* no motion */
downshift: pedal = 0; gearbox_hide_delay = 7; gearbox_show = 0xFFFF; shift_gear(-1);  return; /* no motion */
}
```

Quirks: while fire is held the lateral physics are skipped, so this frame's curve drift is lost (the car does not
drift on curves while shifting). Frames that auto-shift (demo, stage end) do not move the car at all.

### 4.3 Shifting — `shift_gear` 0x1EDCE, `gate_select` 0x1EE76, `knob_update` 0x1CD72, Ticks server 0x118B2

```c
void shift_gear(int delta) {
    gear += delta; if (gear < 0) gear = 0; if (gear > num_gears) gear = num_gears;
    knob_target_x = KNOB_XY[gear].x + 0x80 - dash->x;   /* car +020, dash origin D:257C +4/+6 */
    knob_target_y = KNOB_XY[gear].y + 0x2C - dash->y;
    ratio = RATIO[gear];                              /* car +012; also for neutral */
    if (delta) { gearbox_show = 0xFFFF; }             /* knob keeps its position, it animates */
    else       { knob_x = knob_target_x; knob_y = knob_target_y; }
    shifting = (delta != 0);                          /* set even if the clamp left gear unchanged */
}
void gate_select(int node) {                          /* gate (O) mode */
    gear = NODE_GEAR[node];                           /* car +10C */
    knob_target_x = GATE_XY[node].x + 0x80 - dash->x; /* car +03C */
    knob_target_y = GATE_XY[node].y + 0x2C - dash->y;
    ratio = RATIO[gear]; gate_col = node & 3; gate_row = node >> 2;
    if (knob_x != knob_target_x || knob_y != knob_target_y) shifting = 1;
}
/* Ticks VBLInt 0x118B2, every VBL (is_Data = &tick_count) */
tick_count++;
if (!vbl_read_fire()) { if (!gearbox_hide_delay && !gearbox_always) gearbox_show = 0; return; }
if (gate_mode != 1) return;
gearbox_show = 0xFFFF;
d = vbl_read_dir(); p = gate_last_dir; gate_last_dir = d;
if (p == d && (knob_y != knob_target_y || knob_x != knob_target_x)) return;
if (d == 0) return;
gate_select(GATE_NEXT[d*16 + gate_row*4 + gate_col]);       /* car +07C */
engine_update();                                              /* from the interrupt (quirk) */
/* knob_update 0x1CD72, once per frame, only while the gearbox is on screen in both buffers (D:0B32 && D:0B33) */
dx = knob_target_x - knob_x; knob_x = dx > 4 ? knob_x + 4 : dx < -4 ? knob_x - 4 : knob_target_x;
dy = knob_target_y - knob_y; knob_y = dy > 8 ? knob_y + 8 : dy < -8 ? knob_y - 8 : knob_target_y;
if (knob at the drawn position && D:284C) {
    shifting = 0;
    if (gearbox_hide_delay) gearbox_hide_delay--;
    if (!gearbox_hide_delay && !gearbox_always) { gearbox_show = 0; D:2832 = 0; }
} else draw the knob sprites (drive_scene), gearbox_hide_delay = 7;
```

Quirks: x and y move independently (a diagonal path, not via the neutral row as DOS §4.5). The knob moves only
once the renderer has put the gearbox on both buffers, so the shift time depends on the render rate. In gate mode,
holding fire and a direction with the knob at rest re-selects the next gate node **every VBL** and runs
`engine_update` from the interrupt each time (neutral deceleration and rpm decay then run at 60 Hz).

### 4.4 Engine — `engine_update` 0x20826 and helpers

```c
void rpm_from_speed(void) { rpm_l = (u32)(u16)((u32)speed >> 8) * (u16)ratio; }   /* mulu.w; rpm = HI */
void speed_from_rpm(void) { u16 r = ratio ? ratio : 1;
                            HI(speed) = (u16)(((i32)(i16)HI(rpm_l) << 8) / r); }   /* divu.w: overflow leaves
                                                                                   the dividend (not reached) */
void shift_effects(void) {                            /* 0x207A4 */
    if (!shifting) {
        if (prev_shifting) {                          /* the shift completed since the last update */
            if (gear == 1 && prev_gear == 0 && pedal >= 0 && (i16)HI(rpm_l) > 0xFA0) {
                HI(rpm_l) = (u16)HI(rpm_l) >> 1;      /* clutch dump: half the revs go into speed */
                speed_from_rpm(); squeal_env = 0;
            } else {
                if (gear == 2 && prev_gear == 1 && pedal >= 0) {
                    i16 old = HI(rpm_l); rpm_from_speed(); i16 d = HI(rpm_l) - old; HI(rpm_l) = old;
                    if (d < -1600) squeal_env = 0xB;  /* 0xF9C0 */
                }
                rpm_from_speed();
            }
        }
        prev_gear = gear;
    }
    prev_shifting = shifting;
}
void engine_update(void) {
    i32 f;
    shift_effects();
    if (shifting) goto clutch;
    if (gear == 0) {
        speed -= 0x7FFF;                              /* no clamp here */
        if (pedal <= 0) goto clutch;
        HI(rpm_l) += 500; f = 0; goto apply;          /* free revving */
    }
    if (pedal > 0) {
        rpm_from_speed();
        u32 t = (u32)(TORQUE[(u16)HI(rpm_l) >> 7] << 4) * (u16)ratio;   /* car +11C; index NOT clamped */
        if (gear == 1) t = (t + (t << 1)) >> 1;       /* x1.5, logical shift */
        f = t; goto apply;
    }
    if (pedal == 0) goto sound;                       /* in gear, no pedal: speed and rpm untouched */
    speed -= 0x42000; if (speed < 0) speed = 0;       /* brake 4.125 mph/frame */
    rpm_from_speed(); f = 0; goto apply;
clutch:                                               /* 0x20834: shifting, or neutral without gas */
    HI(rpm_l) -= (u16)HI(rpm_l) >> 5;
    if (pedal < 0) { speed -= 0x42000; if (speed < 0) speed = 0; }
    f = 0;
apply:                                                /* 0x208C2 */
    {   u32 drag = (u32)DRAG[((u16)HI(speed) >> 2) & 0x3F] << 18;   /* + (caller d1.hi << 2), see note */
        speed += (i32)(f - drag) >> 10; }
    if ((i16)HI(rpm_l) <= 0) HI(rpm_l) = 0;
    if (speed >= 0) advance = (u32)speed >> 6;
    else { speed = 0; advance = 0; }
sound:
    engine_sound_update();                            /* 0x26D4E, platform_audio */
}
```

Note: the drag term is built with `swap d1; lsl.l #2,d1` on a register whose upper word is whatever the caller
left in D1; that adds up to 0x3FFFC before the `>> 10`, i.e. below 0.004 mph. The port may use 0.

Per tick, the torque/drag formula is the DOS one exactly: `(torque·16·ratio − drag·2^18) >> 10` in 16.16 equals
`torque·ratio/64 − drag·256`, which is DOS `((torque·rh − drag·64) >> 6)` in 8.8 scaled by 256, except that the
Amiga uses the full ratio instead of `rh = round(ratio/256)` (DOS §4.6).

### 4.5 Lateral physics — `lateral_physics` 0x2484C, `steering` 0x24924, `grip_check` 0x24A04

```c
void lateral_physics(void) {
    yaw_force = 0; car_x_new = car_x;
    i32 c = curve_acc & 0xFFFF0000;                   /* integer part (floor) */
    car_x_new -= c - (c >> 2);                        /* drift outward by 3/4 of the curve integral */
    yaw_force += c;
    i32 t = c;
    if (c) { i32 a = advance >> 8;                   /* asr.l */
             if (a) {                                /* divs.w d1,d0 */
                 i32 q = c / (i16)a;
                 if (q >= -0x8000 && q <= 0x7FFF) t = q << 16;          /* swap d0; clr.w d0 */
                 else if (g_original_bugs) t = 0;    /* bug 7: V set, D0 = c unchanged; c's low word is 0,
                                                        so swap + clr.w leave 0 */
                 else t = (q < 0 ? -0x8000 : 0x7FFF) << 16;  /* fixed: saturate the quotient */
             }
             t = t >> 9; }
    steer_track = t;                                  /* = curve/2 degrees: the steering that cancels the drift */
    lat_force = 0;
    steering();
    lat_force += (i32)(i16)(steer >> 8) * (i16)(advance >> 8) << 3;   /* muls.w */
    yaw_force -= lat_force >> 2;
    grip_check();
    car_x_new += (lat_force >> 2) - (lat_force >> 4);
    clamp_word(-1000, 1000, &HI(car_x_new));
    view_yaw += (yaw_force >> 4) + 1;                 /* grip_check cleared it first */
    if (lane_hold) {
        i16 d = HI(car_x) - 0x50, m = abs(d); if (m > 10) m = 10;   /* cmp: keep 10 if |d| >= 10 */
        if (d) HI(car_x) -= (d > 0) ? m : -m;         /* steering has no effect */
    } else if (!steer_lock) car_x = car_x_new;        /* steer_lock is never set */
    road_edge_check();
}
static const i8 DIR_STEER[10] = {0,0,1,1,1,0,-1,-1,-1,0};   /* 0x24984 */
void steering(void) {
    steer_prev = steer;
    steer_steps(&stepL, &stepR, &kickL, &kickR);
    if (DIR_STEER[joy_dir] < 0) { steer -= stepL; lat_force -= kickL; }
    else if (DIR_STEER[joy_dir] > 0) { steer += stepR; lat_force += kickR; }
    if (steer_lock) { ... dead: car_x ±= 0xC0000 on change; steer = steer_track; }
    wheel_marker();                                   /* 0x247B2, drive_scene */
}
void steer_steps(i32 *L, i32 *R, i32 *kL, i32 *kR) {  /* 0x2498E + 0x249CC */
    *kL = *kR = 0x60000;
    if ((i16)(0x15E - road_left_w - HI(car_x)) > 0) *kL = 0;       /* near the left edge */
    else if ((i16)(road_right_w - 0x15E - HI(car_x)) < 0) *kR = 0; /* near the right edge */
    i32 d = steer - steer_track;
    *L = *R = 0x10000;                                /* 1 degree per frame away from the road angle */
    if (d > 0)      { *kR = 0; if (d > 0x10000) *L = d < 0x60000 ? d : 0x60000; }
    else if (d < 0) { *kL = 0; d = -d; if (d > 0x10000) *R = d < 0x60000 ? d : 0x60000; }
}   /* back toward the road angle: up to 6 degrees per frame (snaps); the kick adds 6.0 to lat_force when
       steering from, or back through, the road angle */
static const u16 HAZ_GRIP[4] = {0xCCCC, 0x9999, 0xCCCC, 0xBFFF};   /* 0x24AA0 */
static const i16 HAZ_EDGE[4] = {1, 0, -1, 0};                      /* 0x24A98 */
void grip_check(void) {
    view_yaw = 0; u16 g = grip; bump_edge = 0;        /* grip = car +008 */
    if (hazard_hit) { hazard_hit &= 3; bump_edge = HAZ_EDGE[hazard_hit];
                      g = (u16)(((u32)g * HAZ_GRIP[hazard_hit]) >> 16); }   /* 80/60/80/75 % grip */
    lat_sign = HI(lat_force);
    i16 a = abs(HI(lat_force));
    i16 s = a - g; if (s < 0) s = 0; if (s > 0x40) s = 0x40;
    skid_amount = s;
    if (s) { i32 k = (i32)s * (i16)skid_drift; if (lat_sign < 0) k = -k; view_yaw += k >> 8; }  /* 0x24AA8 */
    if (a >= (i16)g) {                                /* skid */
        lat_force = (i32)g << 16;
        speed -= 0x4000; if (speed < 0) speed = 0;
        rpm_from_speed();
        if (lat_sign < 0) HI(lat_force) = -HI(lat_force);
    }
    hazard_hit = 0;
}
```

**Grip limit +008.** The skid test is `|steer_deg × advance × 8| + kick ≥ grip`, with advance = mph/64, i.e.
`steer_deg × mph / 8 ≥ grip` (plus the 6.0 kick). DOS tests `2.5 × (sinq(steer) × mph + accel) ≥ grip` with
`sinq ≈ 4.45 × degrees` for small angles (DOS §4.7), i.e. about `11.1 × steer_deg × mph ≥ grip`. The same car
therefore needs a factor ≈ 89 between the two limits for the same steer×speed threshold; the data have exactly
DOS / 72.6 (4864/67 = 5009/69 = 4792/66 = 5082/70 = 72.6, 4939/68 = 72.63). So the Amiga cars skid at a
steer×mph about 23 % higher than a literal conversion would give, and the DOS accel term has no Amiga
counterpart (the kick replaces it). No formula that produces 72.6 was found; it looks like a hand retune (or the
DOS values were derived from the Amiga ones ×72.6: 67·72.6 = 4864.2, 70·72.6 = 5082). Unlike DOS, the Amiga
also clamps the force to the limit (the car slides at the limit instead of drifting by +00A) and slows by
0.25 mph per skidding frame; +00A only turns the view.

### 4.6 Road edges — `road_edge_check` 0x1DB36

```c
void road_edge_check(void) {                          /* uses the renderer's snapshot car_x_snap */
    if ((i16)(-road_left_w - HI(car_x_snap)) >= -0xDC) crash = 1;          /* 0xFF24 */
    if ((u16)road_right_w >= 0x258)                   /* wide road: slot 0 at 3/4 of the limit */
        sd_speed[0] = (((i32)speed_limit << 16) >> 6) - ((((i32)speed_limit << 16) >> 6) >> 2);
    if ((i16)(road_right_w - HI(car_x_snap)) <= 0xC0) crash = 1;
}
```

`road_left_w/right_w` are written by the Road Drawer (0x1E5C6, drive_scene) for its nearest row:
`0x140 + 0x40 × nibble` of the record's flag byte (high nibble left, low nibble right; 0xFF = unchanged). The
shipped roads use 0x22 (0x1C0/0x1C0) and 0x29 (right 0x380). With 0x1C0 the car crashes at x ≤ −0xE4 or
x ≥ 0x100.

### 4.7 Road advance — `road_advance` 0x1E53A, `road_record` 0x1D32A, `curve_integral` 0x2481C

```c
a2_t *road_record(i16 unit) {                         /* 0x1D32A */
    if (unit >= 0 && (unit < stage_end || unit + 45 < stage_end)) {
        u8 b = road_stream[unit];
        if (b != 0xFF) return &REC[b];
        stage_end = unit - 45;
    }
    return &REC[0];                                   /* REC[0] = FF 00 00 00: no curve, no object */
}
void curve_integral(rec) {                            /* 0x2481C */
    i16 cv = (i8)rec->curve;
    if (seg_frac == 0) curve_acc += (i32)cv << 16;
    else if (cv) curve_acc += (cv < 0) ? -(i32)((u16)-cv * (u32)seg_frac) : (i32)((u16)cv * (u32)seg_frac);
}
void road_advance(void) {
    first_unit = -1; curve_acc = 0;
    if (road_pos_done < 0) goto out;
    i16 u = HI(road_pos_done);
    if (u == HI(road_pos)) {
        if (road_pos - road_pos_done) { seg_frac = LO(road_pos - road_pos_done); curve_integral(road_record(u)); }
    } else {
        i32 r = 0xFFFF - LO(road_pos_done);           /* 0xFFFF, not 0x10000 */
        if (r) { seg_frac = r; curve_integral(road_record(u)); }
        do {
            HI(road_pos_done) = ++u; seg_frac = 0;
            rec = road_record(u);
            road_object(rec, u); heading_step(rec);
            if (u == HI(road_pos)) seg_frac = LO(road_pos);
            curve_integral(rec);
        } while (u < HI(road_pos));
    }
out:
    road_pos_done = road_pos;
}
void heading_step(rec) { heading += ((i32)(i8)rec->curve << 16) >> 3;
                         while (HI(heading) < 0) HI(heading) += 360; while (HI(heading) >= 360) HI(heading) -= 360; }
```

Objects are handled **when the car enters the unit** (DOS: 40 units ahead). Traffic is then placed 40 units
ahead, so traffic appears at the same distance as in DOS, but the stage end (autopilot) is decided by
`stage_end = FF − 45` and objects in the last 45 units are never processed.

### 4.8 Objects — `road_object` 0x1DC2E and its branches

```c
void road_object(rec, i16 d7) {
    u16 k = rec->object & 0x3F;
    if (k == 1) {                                     /* radar trap, 0x1DC08 */
        if ((rec->object & 0xC0) <= (rng_next() & 0xC0)) HI(radar_zone_ctr) = 1;
        return;
    }
    if (k >= 5 && k <= 7) {                           /* speed-limit sign, 0x1DCA0; other-side signs 0x85-0x87 count */
        speed_limit = (i8)D0D86[k - 5];
        i32 v = ((i32)speed_limit << 16) >> 6;
        for (i = 0; i < 5; i++) sd_speed[i] = on_speed[i] = v;
        sd_speed[1] += v >> 2;                        /* slot 1 drives 25 % faster; police speed untouched */
        return;
    }
    if (k >= 0x10 && k <= 0x1D) {                     /* traffic, 0x1DB90 */
        if ((rec->object & 0xC0) > (rng_next() & 0xC0)) return;   /* chance 100/75/50/25 % */
        u16 b = g_original_bugs ? rec->object         /* bug 1: full byte, threshold bits included */
                                : k;                  /* fixed: the slot number 0x10..0x1D */
        if (b >= 0x18) {
            if (sd_enable && !demo_mode && WORD(D:0C6E + (b - 0x18)*4) == 0)
                WORD(D:0C6E + (b - 0x18)*4) = d7 + 40;   /* high word of sd_pos[b-0x18] */
        } else {
            if (on_enable && !cop_tail_frames && WORD(D:0CF2 + (b - 0x10)*4) == 0)
                WORD(D:0CF2 + (b - 0x10)*4) = d7 + 40;
        }
        return;
    }
    if (k >= 0x20 && k <= 0x23) {                     /* hazard: full byte = lane in the top bits */
        i16 d = rec->object * 2 - HI(car_x) - 10; if (d < 0) d = -d;
        if ((u16)d >= 0x4C && (u16)d <= 0x70) hazard_hit = rec->object;
    }
    shoulder_bump(d7);                                /* 0x1E6A6: every other object, and hazards */
}
```

**Traffic slot bug (verified).** Only objects without chance bits (0x10–0x14, 0x18–0x1C, 100 %) reach a real slot.
Every traffic object with chance bits (0x50–0x5C, 0x90–0x9C, 0xD1–0xDA in the shipped roads, 86 of the 148 traffic
objects) takes the `b ≥ 0x18` branch with index `b − 0x18`, so it writes `d7 + 40` into a word far past the
same-direction array if that word is 0:

| Objects | Word written | Effect |
|---|---|---|
| 0x50–0x54 | D:0D4E..D:0D5E | Low words of the renderer's traffic snapshot D:0D40/D:0D58; overwritten at the next render |
| 0x58 | D:0D6E | Unused word |
| 0x59 | D:0D72 lane_hold | Recomputed by the loop before it is next used by the physics; the squeal update in the same frame sees it |
| 0x5A | D:0D76 cop_tail_frames | Cleared by traffic_update the same frame unless the police car is tailing; then ≥ 0x46 immediately and the police pass/stop sequence starts |
| 0x5B | D:0D7A cop_mode | Cleared the same frame when no police car is active; otherwise changes the police mode |
| 0x5C | D:0D7E | Renderer temporary, overwritten |
| 0x90–0x9C, 0xD1–0xDA | D:0E4E..D:0F76 | Inside the renderer's per-scanline table D:0DE6[0x192]; rewritten by the next render |

So on the Amiga the "sometimes" traffic never appears. **Port (README bug 1):** by default the index is the masked
code `k = object & 0x3F` (the value the branch test already uses), so the chance-gated cars spawn in slots
0x10–0x14 / 0x18–0x1C (all the shipped codes land there: 0x50–0x5C → 0x10–0x1C, 0x90–0x9C → 0x10–0x1C, 0xD1–0xDA
→ 0x11–0x1A) and nothing past the slot arrays is written. With `g_original_bugs` the full byte is used and the
stray words above are written; since the port keeps these globals at their `D:xxxx` offsets in `mem[]`, the
same writes reproduce the original's effects (only D:0D76/D:0D7A with an active police car matter; the others are
overwritten before use). The disassembly (0x1DB9C–0x1DBFA) reads `move.b 3(a2),d2` once and never masks it
before `sub.w #$18 / #$10`, while the probability test just above masks the same byte with 0xC0: the slot index
was evidently meant to be the low six bits.

```c
void shoulder_bump(i16 d7) {                          /* 0x1E6A6 */
    if ((i16)HI(speed) <= 0x17) return;
    if (road_right_w > 0x210) { if (d7 & 4) marker_test(HI(car_x)*2 - 0x1C0); marker_test(HI(car_x)*2); }
    else if (d7 & 4) marker_test(HI(car_x)*2);
    if (!first_unit) return;
    first_unit = 0;
    if ((i16)(HI(car_x)*2 + road_left_w - 0x7F) <= 0 ||
        (i16)(road_right_w - HI(car_x)*2 - 0x50 + 0x4D) <= 0) { rumble_slow(); bump_flag = -1; }
}
void marker_test(i16 v) { v -= 10; if (v < 0) v = -v; if (v >= 0x4C && v <= 0x70) bump_flag = -1; }
void rumble_slow(void) { speed -= 0x3000; if (speed < 0) speed = 0; if (!shifting) rpm_from_speed(); }
```

### 4.9 Radar and police spawn — `radar_zone` 0x1EC1A

```c
void radar_zone(i32 pos) {
    if (!HI(radar_zone_ctr)) return;
    radar_zone_ctr += (u32)advance >> 5;                  /* the high word climbs 2 per road unit */
    if (HI(radar_zone_ctr) < 5) return;
    if ((i16)(HI(speed) - speed_limit - 15) > 0 && !demo_mode && sd_pos[5] == 0) {
        sd_pos[5] = pos; HI(sd_pos[5]) -= 30;         /* police car 30 units behind */
        sd_speed[5] = 0x1B000 + (((i32)stage << 16) >> 4);   /* 108 mph + 4 mph per stage */
    }
    if (HI(radar_zone_ctr) >= 7) { radar_zone_ctr = 0; radar_blink = 0x32; }
}
```

The zone starts when the car enters the trap unit, the speed check runs on each frame between 2 and 3 units
later. The radar detector lamp shows `min(HI(radar_zone_ctr), 5)` and beeps (drive_scene 0x1EC94, platform_audio).
`speed_limit` is 0 until the first sign of the game (it is never reset), so a trap before any sign triggers at
16 mph or more.

### 4.10 Traffic and police — `traffic_update` 0x1DDEA

```c
void traffic_update(void) {                           /* argument unused */
    i16 unit = HI(road_pos);
    for (s = 0; s < 6; s++) {                         /* D6 = 5..0; s = 5 (D6 = 0) is the police car */
        if (HI(sd_pos[s]) == 0) continue;
        i32 np = sd_pos[s] + sd_speed[s];
        for (j = 0; j < 6; j++) {                     /* cars ahead within 7 units, same lane band */
            i32 d = np - sd_pos[j];
            if (d >= 0 || d + 0x70000 < 0) continue;
            i16 dl = sd_lane[j].lat - sd_lane[s].lat; if (dl > 0xE6 || dl < -0xE6) continue;
            if (s == 5 && (u16)cop_mode < 10) {       /* chasing police pushes the car aside and back */
                sd_dodge[j] += 0x38; HI(sd_pos[j]) -= 1; sd_dodge[5] -= 0x38;
            } else { np = sd_pos[j] - 0x70000; sd_pos[s] = np; }   /* queue 7 units behind */
        }
        sd_lane[s].flag = 0;
        if (s == 5) { if (cop_mode == 10) goto store; }
        else { i16 dx = HI(car_x) - sd_lane[s].lat; if (dx > 0xE6 || dx < -0xE6) goto store; }
        i32 r = np - road_pos;
        if (r <= 0x60000 && r >= -0xC0000) {
            if (r < 0x20000) { sd_lane[s].flag = 1; np = road_pos - 0xC0000; }   /* never hits from behind */
            else if (autopilot) road_pos = np - 0x60000;                          /* held back */
            else crash = (s == 5) ? 2 : 1;                                        /* rear-ended it */
        }
    store:
        sd_pos[s] = np; if (np == 0) HI(sd_pos[s]) += 2;
        i16 rel = HI(sd_pos[s]) - unit;
        if (rel >= 0x46) sd_pos[s] = 0;
        if ((i16)(rel + 0x28) < 0) sd_pos[s] = 0;
    }
    /* police FSM (slot 5) */
    if (HI(sd_pos[5]) == 0) { cop_mode = ticket_frames = cop_tail_frames = cop_timer = 0; }
    else if (ticket_frames >= 0x1E) { radar_zone_ctr = 0 /* word */; sd_speed[5] += 0x600; }  /* drives away */
    else {
        if (cop_timer == 0) {
            if (!cop_tailing) { cop_tail_frames = 0; cop_timer = 0; goto oncoming; }
            cop_tail_frames++;
            if ((u16)(stage_end - unit) <= 0x190) goto oncoming;   /* never near the stage end */
            if ((u16)cop_tail_frames < 0x46) goto oncoming;         /* tails 70 frames */
        }
        if ((u16)++cop_timer <= 0x3C) {               /* passing: from 14 behind to 15 ahead */
            cop_mode = 10;
            i16 o = (i16)(cop_timer - 0x1E) >> 1; if (o > 15) o = 15; if (o <= -12) o = -14;
            HI(sd_pos[5]) = unit + o; sd_speed[5] = advance;
        } else {
            if ((i16)(unit + 15) <= HI(sd_pos[5])) HI(sd_pos[5]) = unit + 15;
            if ((u16)cop_timer > 0x5A) {              /* braking in front of the player */
                cop_mode = 15; sd_speed[5] -= 0x600;
                if (sd_speed[5] <= 0) { sd_speed[5] = 0; if (advance <= 0) ticket_frames++; }
            }
        }
    }
oncoming:
    for (s = 0; s < 5; s++) {
        if (on_pos[s] == 0) continue;
        i32 np = on_pos[s] - on_speed[s];
        for (j = 0; j < 5; j++) { i32 d = np - on_pos[j];
            if (d > 0 && d - 0x70000 < 0) { np = on_pos[j] + 0x70000; on_pos[s] = np; } }
        i16 dx = HI(car_x) - on_lane[s].lat;
        if (dx <= 0xE6 && dx >= -0xE6) { i32 r = np - road_pos; if (r <= 0x60000 && r >= 0x20000) crash = 1; }
        on_pos[s] = np; if (np == 0) HI(on_pos[s]) -= 2;
        if ((i16)(HI(on_pos[s]) + 0x28 - unit) <= 0) on_pos[s] = 0;
    }
}
```

While `lane_hold` is set by `cop_tail_frames ≥ 0x46`, the car is steered to x = 0x50 (pull-over). Once both cars
stand still `ticket_frames` counts; `sim_controls` is skipped from the first count (no controls, no physics, no
motion). At 0x1E the ticket is drawn (0x1E63A, drive_scene), the police car accelerates by 0x600/frame, and when
it leaves the window (70 ahead) its slot is freed and every police counter clears.

### 4.11 Lateral coordinates of traffic (renderer-owned)

`sd_lane[].lat` and `on_lane[].lat` are written by the Road Drawer when it draws each car (0x1E062–0x1E19E):
same-direction slots 0, 2, 3, 4 at `D:0D7E − 0xE0 + dodge` after D:0D7E has been set to the row's right half-width
(so +0xE0 on a 0x1C0 road, +0x2A0 on a 0x380 road), slot 1 and the police car at `0 + 0xE0 + dodge`, oncoming
cars at `−0xE0`. The collision band ±0xE6 around them means: a same-direction car can hit the player when
x ≥ −6, an oncoming car when x ≤ 6 (standard road). The values persist between draws and start at 0 for cars
never drawn. That the simulation depends on the renderer's per-row values (and on its `car_x` snapshot for the
edge test) is a real coupling: the port must run the renderer's lane/width computation for the sim, even when
nothing is drawn. (Renderer side checked in the merge against drive_scene §4 and the code: 0x1E142 writes
`slot_lateral[slot] = D:0D7E + d5` and 0x1E1E4 writes `oncoming_lateral[k] = D:0D7E − 0xE0` with D:0D7E = 0 at
that point; the arrays are only written there, so undrawn cars keep their old value.)

### 4.12 Stage setup — `stage_road_select` 0x20E70

```c
void stage_road_select(int stage) {
    road_records = 0x20F08;
    road_stream = {0x210C0, 0x218F2, 0x22454, 0x22F72, 0x239E5}[stage];   /* stage >= 4 -> 0x239E5 */
    stage_base = stage + 4;
    i = 0; do i++; while (road_stream[i] != 0xFF);    /* starts at index 1 */
    stage_end = i - 45;
    stage_par = {700,1100,1200,1100,1500}[stage]; stage_par2 = {3000,2800,3500,4000,4500}[stage];
}
```

### 4.13 RNG — `rng_next` 0x1530E

```c
u16 rng_next(void) { if (!rng_seeded) { rng_state = VHPOSR; rng_seeded = -1; }
                     rng_state = (u16)((i32)(i16)rng_state * 0x1AFB + 0x1FCCD);
                     rng_state ^= VHPOSR; return rng_state; }
```

The beam position makes it non-deterministic. Users here: the traffic and radar chance tests (the high 2 bits).
Other callers: 0x1E7D2 (renderer scenery), 0x10230, 0x14450, 0x146AA (game_flow).

## 5. Hardware / OS dependencies

| Dependency | Where | SDL3 replacement |
|---|---|---|
| graphics.library `WaitTOF` (−0x10E) × (last+5−tick) | 0x1C900 | Fixed-step: one drive frame per 5 host VBL ticks at 60 Hz (12 Hz) |
| Ticks VBLInt server (tick_count, gate shifting, `engine_update` from the interrupt) | 0x118B2 | Run once per 60 Hz tick before the frame logic, on the main thread |
| `Road Drawer` exec task (pri −1) rendering asynchronously from snapshots | 0x24E94, 0x1D484 | Run the renderer once per host frame after the sim; compute row-0 road widths and traffic lanes every frame (they feed the sim) |
| JOY1DAT `$DFF00C` via table 0x1543E / D:03DC | 0x153EC, 0x11886 | Gamepad/keyboard → 4 direction bits, same table |
| CIA-A PRA `$BFE001` bit 7 (fire) | 0x153E4, 0x11872 | Gamepad button / key |
| VHPOSR `$DFF006` | 0x1530E | Seed and per-call mix from a host RNG (or an emulated beam counter) |
| Keys D, O (D:0B34, D:24B0), Ctrl-C break | 0x10462, 0x1544E | platform input |

## 6. Timing

| What | Rate | Notes |
|---|---|---|
| tick_count D:03D8, gearbox hide, gate-mode shifting | every VBL (60 Hz, NTSC) | Gate mode can also run `engine_update` per VBL |
| sim_controls, engine, physics, road advance, objects, traffic, police, radar | once per drive frame = 5 VBL | **12 Hz** (NTSC); longer only if the main task overruns |
| Stage clock | +1 per frame once a gear was engaged | Shown as frames/12 s; crash +0xF0 frames (20 s); demo ends at 0x226 frames (45.8 s) |
| Rendering, radar lamp and beep, lane/width values | Road Drawer, as fast as the CPU allows | Asynchronous; the knob moves only after the gearbox is on screen |
| Over-rev tolerance | 10 frames | 0.83 s |
| Police: tail 0x46 frames, pass 0x3C, brake from 0x5A, ticket after 0x1E standing frames | frames | 5.8 s, 5 s, 7.5 s, 2.5 s at 12 Hz |

Compared with DOS's 12.5 Hz, the per-tick engine constants that exist in both are unchanged (torque, drag, x1.5
in first gear), so at 12 Hz the car accelerates about 4 % slower per second. Road motion is **not** comparable:
DOS moves speed/90 units per tick, the Amiga speed/64 per frame, so at 12 Hz the Amiga covers a stage (same road
data) about 1.35 times faster at the same mph.

## 7. Differences from DOS

Behaviour:
* Structure: no interrupt handler; the simulation is called from the drive loop at 5 VBL per frame (12 Hz,
  NTSC) instead of every 8th 100 Hz PIT tick (12.5 Hz). Rendering is a separate asynchronous exec task.
* All state is new fixed point: speed 16.16 mph (DOS 8.8), road position 16.16 units advanced by speed>>6 per
  frame (DOS: sub-units 0..89, −mph per tick), steering in 16.16 degrees (DOS ±0xEC0 fixed 8.8), lateral
  position positive = right (DOS positive = left).
* Lateral model: the curve pushes the car outward by 3/4 of `curve × distance` every frame and steering pushes it
  back by 3/16 of `steer × advance × 8`; DOS moves the car by `sinq(heading)` per unit crossed.
* Steering: no ±0xEC0 clamp; 1°/frame away from the road angle, up to 6°/frame back to it (DOS 115/230 per tick
  toward `-road_curve`), plus a 6.0 lateral "kick" when steering from or through the road angle (none in DOS).
* Grip: force clamped at the limit with 0.25 mph/frame loss; excess 0..0x40 = squeal volume and view yaw
  (`× +00A >> 8`, +00A read as a word); DOS sets `skidding`, disables throttle, decelerates 0x30 and drifts the
  view. Grip values are DOS / 72.6 (§4.5).
* Hazards (oil, potholes, gravel) **do** act on the Amiga: for the frame, the grip limit drops to 80/60/80/75 %
  and the bump sound triggers. DOS hazards are visual only.
* Road edges: crash tests use the renderer's row-0 half-widths and its car_x snapshot (−0xDC / +0xC0 margins);
  DOS uses fixed ±0x264/−0x236. The Amiga adds rumble strips (−0x3000 speed near the edges, first unit of each
  frame only) and lane-marker bumps (sound only).
* Engine: no rpm idle floor or slew (DOS 800 floor, 0x40/tick slew); neutral/clutch decay `rpm −= rpm/32`
  (DOS −300 to 800); free rev +500/frame (DOS +800); neutral speed loss 0x7FFF + drag per frame (DOS drag only);
  brake 0x42000 (4.125 mph) + drag per frame (DOS 0x304 = 3.02 mph, no drag); torque index `rpm >> 7`
  **unclamped** (DOS clamps to 0x50); full ratio in the force (DOS ratio rounded to /256).
* In gear with no pedal, speed and rpm are held (same as DOS Q5).
* Blown engine: rpm above +004 for 10 consecutive frames (DOS: immediately, and only rpm from speed or free
  revving).
* Shift completion: clutch dump neutral→1st above 4000 rpm halves the rpm and converts it to speed (DOS: rpm rise
  > 3500 in 1st adds 0x1E mph); 1st→2nd with an rpm drop > 1600 only starts the squeal chirp (DOS: drop > 2500
  in any gear subtracts 5 mph). rpm is resynchronised from speed after every other shift.
* Knob moves 4 px/8 px per frame diagonally (DOS 6 px/tick via the neutral row) and only while the gearbox is on
  screen. Joystick shifting: fire + up/down one gear per deflection (DOS GEAR_DELTA table; keyboard A/Z/digits
  have no Amiga counterpart: driving is joystick only). Gate mode (O) runs in the VBL interrupt at 60 Hz.
* While fire is held, lateral physics are skipped (no curve drift). Auto-shift frames (demo, stage end) do not
  move the car.
* Objects are processed when the car enters a unit (DOS: 40 units ahead); traffic is still placed 40 ahead.
  Speed-limit signs on the other side of the road (0x85–0x87) count on the Amiga (DOS ignores them).
* **Traffic with a chance threshold never spawns** in the original (slot index bug, §4.8); DOS spawns it with
  75/50/25 % probability, and so does the port by default (README bug 1; `--original-bugs` restores the bug).
* Traffic: 5 fixed same-direction slots + police slot, 5 oncoming slots, indexed by object code (DOS: head-inserted
  lists of 5, max 2 oncoming). Speeds come from the last sign (limit mph, slot 1 ×1.25, slot 0 ×0.75 on wide
  roads) with initial 42.7/50.7/58.7/38.7/30.7 mph; DOS uses TRAFFIC_SPEED 25/50/60 per tick. Cars queue 7 units
  apart; cars within 2 units ahead to 12 behind are moved 12 units behind the player; collisions only 2–6 units
  ahead. Removal at 70 ahead / 40 behind (DOS 60 ahead / 40 behind). The DOS head-removal bug (Q1) does not exist.
* In demo/stage-end autopilot a car ahead pushes the player back 6 units instead of crashing.
* Police: spawned 30 units behind when passing a radar trap zone more than 15 mph over the last limit (DOS trap
  speeds 35/65/75 with limits 25/50/60, trap armed 8 units before); speed 108 + 4·stage mph constant (DOS 60
  rising by 2 to 120); pushes blocking cars aside; tails 12 units behind, passes after 70 frames (never within
  400 units of the stage end), brakes in front, ticket after 30 standing frames, then drives away. Hitting it
  from behind = game over (as DOS). No time or money penalty besides the stop.
* Stage end: autopilot starts 125 units before the 0xFF (stage_end + 80), brakes and downshifts at ≤ 4000 rpm,
  and the stage ends at stage_end or when the speed drops to ≤ 17 mph; DOS: 40 units before, pulls over to the
  right and ends at speed 0. Lane hold steers to x = 0x50 by ≤ 10 per frame.
* Crash penalty 0xF0 frames (DOS 240 ticks); demo limit 0x226 frames (DOS 720 ticks); lives 5 in both.
* RNG: LCG mixed with the video beam position, called only by spawn tests (DOS: 256-byte table, also advanced per
  rendered frame).
* Sound triggers: the simulation writes skid_amount, squeal_env, bump_flag, bump_edge, lane_hold and the engine
  state that `engine_sound_update` reads once per frame (platform_audio); DOS writes note divisors.

Constants and tables:
* Same: road record table, stage streams, drag table (64 bytes), torque/ratio/knob/gate car data, first-gear ×1.5,
  torque/drag scaling per tick, lives 5.
* New tables: DIR_PEDAL 0x20D5E, DIR_STEER 0x24984, HAZ_EDGE 0x24A98, HAZ_GRIP 0x24AA0, speed limits D:0D86
  {30,55,65}, initial traffic speeds D:0C92/D:0D14, road half-width table 0x1E45A (0x140 + 0x40·n), par tables
  0x20EE0/0x20EF4, sine table 0x1216C.
* Car +008 rescaled (÷72.6), +00A read as a word, +004 Rossa 8600 (FORMATS.md).

## 8. Open questions

* NTSC vs PAL: *resolved*, the port uses NTSC 60 Hz (port/amiga/README.md, *Decisions* 1).
* The frame is exactly 5 VBL only if the main task's work fits; on a real A500 with the Road Drawer at lower
  priority this should hold, but it was not measured. `WaitTOF` count off-by-one (tick incremented by a VBL
  server vs graphics' own TOF wakeup) could make some frames 4 or 6 VBL.
* The traffic lane values (§4.11) come from the renderer; drive_scene should confirm the row where each car's lane
  is written (D:0D7E at call time) and whether cars not yet drawn keep lat = 0 (same-direction slots start at 0,
  which puts them on the centre line for the collision test until first drawn). *Merge:* confirmed from
  drive_scene's queue routines (0x1E142, 0x1E1E4; no other writers), see §4.11.
* The unit relation between `car_x` and the road half-widths (the edge tests use x, the rumble and marker tests
  2·x) suggests half-width units = 2 × x units; not confirmed from the renderer's projection. *Merge note:* in
  drive_scene's walker (0x1DA14) row 0 has centre `160 − HI(lat)·s` and edges `± half·s` (both scaled by the same
  row scale), i.e. the same unit at row 0; the 2·x tests remain unexplained. Still open.
* Whether the stray words of the traffic slot bug ever cause visible effects (D:0D76/D:0D7A with a police car
  present, the snapshot low words, the scanline table) was reasoned, not observed. It matters only with
  `--original-bugs`.
* Gate mode calling `engine_update` from the VBL interrupt races with the main task (both write speed/rpm). Port
  proposal: run it on the main thread at the VBL rate, which keeps the effect without the race.
* `lateral_physics` divs overflow (README bug 7, *resolved*): a quotient c / (advance >> 8) outside −0x8000..0x7FFF
  sets V and leaves the dividend in D0; since `c` has a zero low word, `swap; clr.w` then give **0**, so
  steer_track = 0 for that frame (not garbage). It needs `advance >> 8` < 2·|HI(c)|, which with |curve| ≤ 127 only
  the floor of a small negative integral reaches (HI(c) = −1): a = 1, i.e. advance 0x100–0x1FF (0.25–0.5 mph). Its
  neighbours do not overflow and give the extreme values themselves (a = 2: q = −0x8000, steer_track −64°; a = 3:
  −42.7°). The fix saturates the quotient to −0x8000..0x7FFF, which continues that sequence; `--original-bugs`
  keeps the 0 (§4.5).
* D:1604 (over-rev count) is not reset at stage start or after a crash.
* The meaning of the police "dodge" array D:0CAA as seen on screen (sideways offset) is drive_scene's to confirm.
  *Merge:* confirmed: the renderer (0x1E124) takes `min(dodge − 0x38, 0xE0)` when positive, stores it back and
  adds it to the car's lateral, so the car slides sideways and returns by 0x38 per rendered frame.
