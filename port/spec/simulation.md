# Simulation subsystem (TDEGA image 0x3B00–0x4940)

## 1. Overview

The whole driving simulation is **one hand-written assembly interrupt handler**, not a set of C functions.
That is why Ghidra has no functions between 0x3B18 and 0x4792: nothing calls this code directly.

* **0x4792 `stage_enter_install_isr`** (called once per stage by game_flow's `0x1DC0`) does four things:
  * sets up the cockpit gauge sprites;
  * calls `0x698C`, which programs PIT channel 0 to divisor **0x2E97 (≈100.0 Hz)** and installs the sound ISR 0x6A1F on int 8;
  * queues song 0xB05, which is the looping **engine sound** (see §4.2);
  * saves the int 8 vector (now 0x6A1F) into `CS:3B18`, installs **0x3B1F** as the new int 8 handler, and installs a divide-error handler at DGROUP:1423.
* **0x3B1F `sim_timer_isr`** runs 100 times a second:
  1. It far-calls the previous handler first (the sound ISR, which sends the EOI).
  2. It slews `rpm_smooth` toward `rpm`.
  3. On every 8th interrupt it runs the **simulation tick (12.5 Hz)** at 0x3BEA.

  The tick covers input, shifting, steering, engine, road motion, look-ahead/spawning, traffic, the police state machine, radar trap and hazards. It returns through the `iret` at 0x4673.
* The **frame loop** belongs to game_flow (`0x1DC0`). It runs as fast as the renderer allows, independent of the ISR. Each frame it:
  1. snapshots the simulation state (`0x2013`);
  2. renders (scene_render);
  3. calls `rng_next` once (0x8BAF), so spawn randomness is also advanced per frame;
  4. checks `run_state` DS:0929 and `demo_mode`.
* **Exits** (handled in `0x1DC0`, driven by DS:0929):

  | Value / condition | Result |
  |---|---|
  | `1` (Esc, or any key in demo) | returns -1 |
  | `2` (road byte 0xFF seen 40 units ahead) | the sim auto-brakes, auto-downshifts and pulls over; when `speed == 0` the loop ends the stage (gas station, or the dealership via `0x38EB` on stage 4) |
  | `3` (crash) | the ISR freezes. The loop adds 240 ticks (`0xF0`) to the clock, plays the crash sequence `0x392C`, and does `cars_left--`. At 0 → game over; otherwise `0x1F93` resets the car in place (road position kept) and the song restarts |
  | demo and clock > 0x2D0 (720 ticks) | returns -1 |

```
int8 --> 0x3B1F sim_timer_isr (100 Hz)
          |-- far call old int8 (0x6A1F sound/PIT, BIOS chain)
          |-- rpm_smooth slew, engine note divisor DS:64FC
          `-- every 8th: clock; 0x3BEA sim_tick (12.5 Hz)
                 |-- 0x5C24 read_controls (platform)
                 |-- char keys 0x3BB4 / auto-pilot (demo, stage end)
                 |-- 0x3CB8 fire+direction: gate graph | gear delta | steer/throttle
                 |-- 0x3D7D steering
                 |-- 0x3DDB knob animation -> shift completion (rpm clash / clutch dump)
                 |-- 0x3EAA engine: idle decay, skid, brake, free rev, torque-drag  (0x3FAD update_rpm)
                 |-- 0x3FE8 motion: sub-unit, grip/skid, 0x40FE unit advance loop
                 |        |-- lateral drift, road edge, speed-limit signs
                 |        `-- 0x4241 look-ahead -> 0xFF stage end | 0x467D spawn (rng 0x8BAF)
                 `-- 0x427F grind timer, oncoming list, same-dir list, 0x438A cop FSM,
                     0x455F removal, radar trap, hazard expiry, iret
```

**Units.**

| Quantity | Global | Encoding |
|---|---|---|
| Speed | DS:0927 | u16 in 8.8 fixed point; the high byte is **mph** (the digital speedo prints DS:0928) |
| Distance | DS:0906 / DS:0912 | one road unit = 90 sub-units. Each tick subtracts round(speed/256), i.e. the mph value. At 12.5 Hz, 1 unit ≈ 7.2 mph·s ≈ 3.2 m |
| Traffic and cop speeds | — | the same sub-units per tick, i.e. mph |
| Lateral position | `car_x` DS:0910 | positive is **left** (the oncoming lane) |

## 2. Function table

Entries are code labels inside one ISR unless a signature is given.

| image addr | proposed name | signature | purpose | confidence |
|---|---|---|---|---|
| 0x3AF7 | scene_flip_page_3af7 | void(void) | Boundary helper: select page and show it (see scene_render) | verified |
| 0x3B18 | (data) old_int8_vector | far ptr | Stored by 0x4792 and called by the ISR | verified |
| 0x3B1C | sim_isr_exit_jmp | label | `jmp 0x4673` | verified |
| 0x3B1F | sim_timer_isr | interrupt | 100 Hz handler: chain, rpm slew, 1/8 gate, clock | verified |
| 0x3BB4 | sim_input_charkey | label | D and O keys | verified |
| 0x3BEA | sim_tick | label | 12.5 Hz tick: input fetch and auto-pilot overrides | verified |
| 0x3CB8 | sim_input_direction | label | Shift/steer/throttle decode | verified |
| 0x3D7D | sim_steering | label | Steering angle | verified |
| 0x3DDB | sim_shift_knob_anim | label | Knob movement and shift completion | verified |
| 0x3EAA | sim_engine | label | Engine and longitudinal speed | verified |
| 0x3FAD | sim_update_rpm | near proc, returns DX | rpm from ratio×speed, idle floor, over-rev | verified |
| 0x3FE8 | sim_motion | label | Sub-unit step, grip check | verified |
| 0x40FE | sim_advance_unit | label | Per-unit lateral motion, road read | verified |
| 0x4241 | sim_lookahead | label | 40-unit look-ahead | verified |
| 0x427F | sim_traffic_update | label | Traffic lists | verified |
| 0x438A | sim_cop_fsm | label | Police state machine | verified |
| 0x455F | sim_object_cleanup | label | Removal, trap, hazard, iret | verified |
| 0x467D | sim_spawn_object | label (AL = object byte, BX = look-ahead pos) | Spawning | verified |
| 0x4792 | stage_enter_install_isr | void(void) | Stage setup and vector hooks | verified (sprite lookups `0x94C7` likely) |
| 0x493D | car_data_ptr | u16(void) | Returns 0x268F | verified |
| 0x5C24 | read_controls | u16(void) | **platform**: see §4.1 | verified |
| 0x8BAF | rng_next | u8(void) | **platform**: see §4.9 | verified |

Related (other specs): `0x1DC0` stage_drive_loop, `0x1F4E` stage_reset_position, `0x1F93` car_reset_state,
`0x1F7B` wait_fire (game_flow); `0x2013` snapshot, `0x349D` police/ticket overlay, `0x351A` shifter panel,
`0x35C6` gauges, radar detector and steering wheel, `0x392C` crash sequence (scene_render); `0x698C` PIT/sound init, `0x6A1F` sound ISR (platform).

## 3. Globals table

Car fields are cited from FORMATS.md (base DS:268F).

| DS | name | type | meaning | written by | read by |
|---|---|---|---|---|---|
| 0084 | demo_mode | u16 | Attract autopilot | game_flow | ISR, 1DC0 |
| 08BE | gearbox_display_toggle | u8 | D key toggle | ISR | 351A |
| 08F4 | grind_timer | u8 | Clash/dump effect ticks | ISR, 1F93 | ISR |
| 0906 | road_pos | u16 | Road stream address | ISR, 1F4E | all |
| 0908 | road_pos_prev | u16 | At start of tick | ISR | ISR |
| 090A | yaw_lateral | i16 | Heading for lateral motion | ISR | ISR |
| 090C | view_heading | i16 | Renderer heading | ISR | 2054, 2478 |
| 0910 | car_x | i16 | Lateral position (start -0x75) | ISR, 1F93 | ISR, renderer |
| 0912 | sub_unit | i16 | 0..89 | ISR | ISR, 2013 |
| 0914 | steer_angle | i16 | ±0xEC0 | ISR | ISR, 35C6 (wheel) |
| 0916 | cur_ratio | u16 | Ratio of the engaged gear | ISR | ISR |
| 0919 | road_curve | i16 | curve×64 | ISR | ISR |
| 091B | rpm | u16 | Engine rpm (init 800) | ISR | ISR, 35C6 |
| 091D | rpm_smooth | u16 | Slewed rpm | ISR | ISR |
| 091F | dash_timer | u8 | Panel redraw countdown | ISR | 351A |
| 0920 | gate_node | u8 | Shift-gate node (init 1) | ISR | ISR |
| 0921 | gate_shift_mode | u8 | O key | ISR | ISR |
| 0922/0923 | gearbox_dirty / gauges_dirty | u8 | Redraw flags | ISR | 351A / 35C6 |
| 0924 | skidding | u8 | Grip exceeded | ISR | ISR |
| 0925 | accel_mag | u16 | \|Δspeed\| last tick | ISR | ISR |
| 0927 | speed | u16 8.8 | mph×256 | ISR | ISR, 35C6, 1DC0 |
| 0929 | run_state | u8 | 0 drive, 1 quit, 2 stage end, 3 crash | ISR, 1F93 | ISR, 1DC0, 349D |
| 092A | stage_end_pos | u16 | Address of 0xFF | ISR | ISR, renderer |
| 093A | pit_tick_count | u16 | 100 Hz counter | ISR | ISR |
| 093C | clock_running | u8 | Clock enabled | ISR, 1DC0, 1F93 | ISR |
| 0941 / 0945 | oncoming_count / list | u8 / 5×8 B | {pos, sub, ?, type×40} | ISR | ISR, 2013 |
| 0942 / 096D | samedir_count / list | u8 / 5×8 B | Same layout | ISR | ISR, 2013 |
| 0995 | spill_slot | 8 B | Unused | (bug) | – |
| 099D | radar_trap | 8 B | +0 position | ISR | ISR, 2013 |
| 09A5 | hazard | 8 B | +0 pos, +6 lo = type<<4, hi = lane | ISR | 2013 → renderer 0x2C57 |
| 0A21 | speed_limit_idx | u16 | 0/2/4 | ISR, 1F4E | ISR |
| 0A23–0A2F | cop_* | see CSV | Police car | ISR | ISR, 2013, 349D |
| 0A77–0A83 | fire_held, gear, throttle_in, steer_in, knob_anim, shift_latch, knob_xy, knob_target | u8/i8/u16 | Controls | ISR, 1F93 | ISR, 351A |
| 1433 | road_anim_counter | u8 | ++ per unit | ISR | 28C5, 2F7A |
| 1447 | cop_light_timer | u16 | = 10 at chase start | ISR | 28C5, 2F7A |
| 6424 | isr_busy | u8 | Skip ISR | platform | ISR |
| 64FC / 64FE / 6500 | tone divisors | u16 | Note divisor slots for notes 0x55/0x56/0x57 (DS:6452 + 2·note): engine, squeal/grind, radar beep | ISR, 1F93 | sound ISR 0x6A1F (song 0xB05 / 0xB0F) |
| 6520 / 6522 | rng_index / rng_table | u16 / u8[256] | RNG | 8BAF | 8BAF |
| 66E8 | joystick_enabled | u8 | Ctrl-J / Ctrl-K | platform | ISR, A12F |
| 78E6 | cars_left | u16 | Lives | game_flow, ISR (=1) | 1DC0 |
| 80A4 | clock_ticks | u16 | Elapsed ticks | ISR, 1DC0 | game_flow scoring, renderer blink |

## 4. Pseudocode

Types: `u8/i8/u16/i16/u32`. All arithmetic wraps at the stated width.
`SINQ` = `tables/sim_sinq.json`; `CAR` = the car `.BIN` at DS:268F (FORMATS.md);
`ROAD[a]` = byte at DS address a; `REC(c)` = `&DS[0x2B70 + (i8)c*4]` (flag, curve, pitch, object).
Signed comparisons are marked `(i16)`/`(i8)` where the original used `jl/jg`; unmarked ones are unsigned `jb/ja`.

### 4.1 Controls: `read_controls` 0x5C24 (platform, summarised)

Returns AX:

* **No key in the BIOS buffer.** `bits = joystick_read()` (0xA12F; returns 0 when `joystick_enabled == 0`).
  Then `AL = JOY_DIR[bits & 0xF]`, plus `0x10` if `bits & 0x30` (either fire button). `AH = 0`.
* **Key(s) present.** The buffer is drained and **only the last key** is used.
  * `p`/`P`: pause (0x67DD, with `isr_busy` set), then returns `AH = 0xFF`.
  * `a`/`A` → `0x11` (fire+up); `z`/`Z` → `0x15` (fire+down).
  * `'0'..'9'` → `DIGIT_MAP` (fire+direction).
  * Other printable characters → `AH = 0xFF, AL = char`.
  * Extended keys (ASCII 0): scan 0x47..0x51 → `EXT_DIR[scan-0x46]`, anything else → 0.
  * Control characters: Ctrl-J joystick on (calibrates first if needed), Ctrl-K joystick off, Ctrl-P pause, Ctrl-Q sound off, Ctrl-S sound on. Each returns `AH = 0xFF, AL = scan code`.
  * Esc → `0xFFFF`.

Directions: 1 up, 2 up-right, 3 right, 4 down-right, 5 down, 6 down-left, 7 left, 8 up-left.
**Keyboard input is edge-based:** a held key only acts through BIOS typematic repeat, at most one event per 12.5 Hz tick. Emulate typematic behaviour (≈250–500 ms delay, ~10 cps), or deliberately choose held-key semantics.

### 4.2 ISR prologue (0x3B1F)

```c
void sim_timer_isr(void) {            /* int 8, 100.0 Hz (PIT divisor 0x2E97) */
    push_all(); pushf(); far_call(old_int8);   /* sound ISR 0x6A1F; EOI there. IF stays 0 below */
    if (isr_busy_6424) goto iret;
    if (run_state == 3) goto iret;              /* frozen after a crash until 1DC0 resets */
    u16 r = rpm_smooth;                         /* 0x3B43 */
    if (r != rpm) {
        if ((i16)r > (i16)rpm) { r -= 0x40; if (!((i16)r > (i16)rpm)) r = rpm; }
        else                   { r += 0x40; if (!((i16)r < (i16)rpm)) r = rpm; }
    }
    rpm_smooth = r;
    engine_tone_64FC = ENGINE_NOTE_DIV[(r >> 6)];  /* word at DS:2077 + ((r>>5)&~1) */
    /* DS:64FC is the divisor of note 0x55 (table DS:6452 + 0x55*2). Song 0xB05 = FE 00, 55 dur 3,
       56 dur 1, FF (loop): engine note alternating with the effect tone DS:64FE (0xFFFF = silent,
       0x8E8 skid squeal, 0x474 grind). Radar beep song 0xB0F plays note 0x57 = DS:6500 (900),
       then resumes the engine loop. Sound driver: platform (tables/sound_effects.json). */
    if ((++pit_tick_count & 7) != 0) goto iret;
    clock_ticks++;  if (!clock_running) clock_ticks--;   /* 0x3B8A */
    sim_tick();
iret: pop_all(); iret();
}
```

### 4.3 Tick input stage (0x3BEA–0x3D7C)

```c
void sim_tick(void) {
    accel_mag = 0; steer_in = 0; throttle_in = 0;
    u16 ax = read_controls(); u16 raw_dx = DX_after_read_controls;   /* see quirk Q3 */
    u8 al = ax, ah = ax >> 8;
    if ((ax != 0 && demo_mode != 0) || al == 0xFF) { run_state = 1; goto motion; }  /* 0x3BA5 */
    if (ah == 0xFF) {                                     /* 0x3BB4 character key */
        if (al == 'd' || al == 'D') gearbox_display_toggle ^= 1;
        else if (al == 'o' || al == 'O') {
            gate_shift_mode ^= 1;
            if (gate_shift_mode) {
                if (gear == 0) gate_node = 1;
                else { int n = 0; while (n < 16 && CAR.node_gear[n] != gear) n++; gate_node = (n < 16) ? n : 15; }
            }
        }
        al = 0;
    }
    if (run_state == 2) {                                 /* 0x3C4D stage-end autopilot */
        al = 5;  clock_ticks--;                           /* brake; clock frozen */
        if (!((i16)rpm > 3000) && knob_anim != 1 && (i8)gear > 1) al |= 0x10;  /* downshift */
    } else if (demo_mode != 0) {                          /* 0x3C99 */
        dash_timer = 10;
        al = 1;
        if (!((i16)(rpm + 1000) < (i16)CAR.rpm_limit) && knob_anim != 1) al = 0x11;
    }
    /* 0x3C1E: fire released while fire_held and not animating -> check clash */
    if (!(al & 0x10) && fire_held == 1 && knob_anim != 1) {
        fire_held = 0;
        u16 before = rpm;
        u16 now = sim_update_rpm(raw_dx);                 /* returns DX */
        i16 diff = (i16)(before - now);
        if (diff < -2500)      { grind_timer = 3;    speed -= 0x500;  }   /* u16 wrap possible */
        else if (diff > 3500 && gear == 1) { grind_timer = 0x12; speed += 0x1E00; }
        goto steering;
    }
    u8 dir = al & 0x0F;                                   /* 0x3CB8 */
    if (al & 0x10) {
        fire_held = 1; gearbox_dirty = 1; dash_timer = 13;
        u8 latch = 0;
        if (gate_shift_mode && run_state == 0 && joystick_enabled == 1) {
            if (dir) {
                latch = 1;
                gate_node = CAR.gate_next[dir*16 + gate_node];     /* DS:270B */
                gear      = CAR.node_gear[gate_node];              /* DS:279B */
                set_knob_target(gate_node + 7);                    /* = gate_node_xy[node] */
            }
        } else {
            i8 dg = GEAR_DELTA[dir];
            if (dg) {
                u8 g = gear + dg;
                if (g <= CAR.num_gears) {                          /* unsigned: -1 fails */
                    latch = 1;
                    if (shift_latch != 1 && knob_anim != 1) { gear = g; set_knob_target(g); }
                }
            }
        }
        shift_latch = latch;
    } else {
        shift_latch = 0;
        if (knob_anim == 0) { fire_held = 0; steer_in = STEER_DIR[dir]; throttle_in = THROTTLE_DIR[dir]; }
    }
steering: ...
}
void set_knob_target(u16 i) { knob_target_x = CAR.knob_xy[i].x; knob_target_y = CAR.knob_xy[i].y; knob_anim = 1; }
```

### 4.4 Steering (0x3D7D)

There is **no self-centring**. With no input the angle is kept. `-road_curve` is the angle that tracks the road.

```c
    i16 s = steer_angle, n = -road_curve, a;
    if ((i8)steer_in > 0) {
        if (s < n) { a = s + 230; steer_angle = (a < n) ? a : n; }          /* toward neutral: fast, snaps */
        else       { a = s + 115; goto clamp; }
    } else if ((i8)steer_in < 0) {
        if (s > n) { a = s - 230; steer_angle = (a > n) ? a : n; }
        else       { a = s - 115; goto clamp; }
    }
    goto knob;
clamp: if (a > 0x0EC0) a = 0x0EC0; else if (a < -0x0EC0) a = -0x0EC0; steer_angle = a;
```

### 4.5 Knob animation and shift completion (0x3DDB)

```c
knob:
    if (knob_anim == 1) {
        gearbox_dirty = 1; clock_running = 1;           /* clock starts at first shift */
        i16 x = knob_x, y = knob_y, ny = CAR.knob_xy[0].y;  /* neutral row */
        if (x == knob_target_x) y += ((i16)y < (i16)knob_target_y) ? 6 : -6;
        else if (y == ny)       x += ((i16)x < (i16)knob_target_x) ? 6 : -6;
        else                    y += ((i16)y > ny) ? -6 : 6;
        knob_x = x; knob_y = y;
        if (x == knob_target_x && y == knob_target_y) {
            knob_anim = 0; fire_held = 0;
            if (gear != 0) {
                cur_ratio = CAR.gear_ratio[gear];
                u16 before = rpm; sim_update_rpm(); i16 diff = (i16)(before - rpm);
                if (diff < -2500) { grind_timer = 3;  speed_hi = (u8)(speed_hi - 5);   goto brake; }
                if (diff > 3500)  { if (gear == 1) { grind_timer = 0x12; speed_hi = (u8)(speed_hi + 0x1E); } goto brake; }
                goto motion;                                  /* engine skipped this tick */
            }
        }
    }
```

In neutral, `cur_ratio` is **not** updated; it keeps the ratio of the previous gear.

### 4.6 Engine (0x3EAA) and `sim_update_rpm` (0x3FAD)

```c
    if (fire_held == 1 || gear == 0) {                   /* clutch in / neutral: idle decay */
        i16 r = (i16)(rpm - 300);
        if (r <= 800) { if (rpm != 800) { rpm = 800; gauges_dirty = 1; } }
        else          { rpm = r; gauges_dirty = 1; }
    }
    u16 dec, force;
    if (skidding == 1) { dec = 0x30; goto decel; }       /* no throttle while skidding */
    if (throttle_in == 0) { force = 0; goto coast; }
    if ((i8)throttle_in < 0) goto brake;
    if (cop_state != 7 && (i8)cop_state >= 3) goto motion;   /* being pulled over */
    if (gear == 0) {                                      /* free revving */
        rpm += 800;
        if ((i16)rpm > (i16)CAR.rpm_limit) run_state = 3;     /* blown engine = crash */
        force = 1; goto coast;
    }
    u16 idx = (u16)(rpm << 1) >> 8;  if ((i16)idx > 0x50) idx = 0x50;   /* rpm/128; [80] reads car+16C */
    u8  rh  = (u8)((cur_ratio >> 8) + ((cur_ratio & 0x80) != 0));       /* rounded ratio/256 */
    force = (u16)CAR.torque[idx] * rh;
    if (gear == 1) force = (force >> 1) + force;          /* x1.5 */
    goto apply;
coast:
    if (!(fire_held == 1 || gear == 0)) goto motion;      /* in gear, no gas: speed held, NO drag */
apply: {
    u16 drag = (u16)DRAG[speed_hi >> 2] << 6;             /* DS:0AC5 */
    i16 dv = (i16)(force - drag) >> 6;                    /* arithmetic shift */
    speed += dv;                                          /* u16 wrap, no clamp */
    accel_mag = (dv > 0) ? dv : -dv;
    sim_update_rpm(); goto motion; }
brake:  dec = 0x304;                                      /* 3.02 mph per tick */
decel:  accel_mag = dec; speed = (speed < dec) ? 0 : speed - dec; sim_update_rpm(); goto motion;

u16 sim_update_rpm(void) {                                /* 0x3FAD, result in DX */
    gauges_dirty = 1;
    if (gear == 0 || fire_held == 1) return DX_unchanged;  /* Q3 */
    u16 r = ((u32)cur_ratio * speed) >> 16;
    if (r < 800) { rpm = 800; return 800; }
    rpm = r;
    if (r > CAR.rpm_limit) run_state = 3;                 /* unsigned */
    return r;
}
```

### 4.7 Motion, grip, lateral drift, look-ahead (0x3FE8–0x427E)

```c
static u8 sinq(u8 i, u8 f) { u8 a = SINQ[i]; u8 d = SINQ[i+1] - a; if (d) a += ((d + 1) * f) >> 8; return a; }
/* the (d+1) multiplier is exact: jump tables DS:205F/206B implement f*2, f*3 ... f*6 >> 8 */

motion:
    road_pos_prev = road_pos;
    u8  step = (u8)((speed >> 8) + ((speed & 0x80) != 0));       /* wraps at 0xFF80 */
    i16 s = sub_unit - step;
    sub_unit = s;
    if (s >= 0) { unit_advanced = 0; goto traffic; }
    unit_advanced = 1;
    effect_tone_64FE = 0xFFFF; skidding = 0;
    if ((u8)(steer_angle >> 8) != 0) {                   /* small positive angles never skid */
        u16 v = ((i8)(steer_angle >> 8) > 0) ? steer_angle : -steer_angle;
        u8  a = sinq(v >> 8, v & 0xFF);
        u16 load = (u16)((u16)a * speed_hi) << 1;
        load += accel_mag; load += accel_mag;
        load += load >> 2;
        if ((i16)load >= (i16)CAR.grip_limit) { skidding = 1; effect_tone_64FE = 0x8E8; }
    }
    if (demo_mode == 1) goto hold;
    if (run_state == 2 || (cop_state != 7 && (i8)cop_state >= 3)) {   /* auto pull-over to right */
        if (car_x >= -100) car_x -= 40; else if (car_x <= -150) car_x += 40;
    hold:
        skidding = 0; yaw_lateral = 0; steer_angle = -road_curve;
    }
advance:                                                  /* 0x40FE, loops */
    sub_unit += 90;
    i16 h;
    if (skidding != 1) { h = steer_angle + road_curve; view_heading = h; }
    else {
        i16 t = (i16)((u16)CAR.skid_drift << 8); if (steer_angle < 0) t = -t; t >>= 3;
        view_heading = t + (steer_angle + road_curve);
        h = (i16)((u16)(road_curve << 1) + steer_angle) >> 1;
    }
    yaw_lateral = h;
    u8 hi = h >> 8, lo = h;
    if (hi != 0) {
        if ((i8)hi < 0) { hi = -hi; lo = -lo; }           /* byte-wise negate: Q4 */
        i16 a = sinq(hi, lo); if (h < 0) a = -a;
        car_x += a * 2;
        if (car_x > 0x264 || car_x < -0x236) run_state = 3;   /* off the road */
    }
    if (yaw_lateral < -0x4B00) yaw_lateral = -0x4B00; else if (yaw_lateral > 0x4B00) yaw_lateral = 0x4B00;
    road_pos++;
    u8 c = ROAD[road_pos];
    if (run_state == 2 && (i16)road_pos >= (i16)stage_end_pos) c = 0;
    road_curve = (i16)((u16)(i8)REC(c)[1] << 8) >> 2;     /* curve*64 */
    i8 o = REC(c)[3];
    if (o < 0x10 && (i8)(o - 5) >= 0 && (o - 5) < 3) speed_limit_idx = (o - 5) * 2;  /* signs 5,6,7 (not 0x8x) */
    road_anim_counter++;
    if (run_state != 2) {                                 /* 0x4241 look-ahead */
        u16 la = road_pos + 40;
        if (ROAD[la] == 0xFF) { run_state = 2; stage_end_pos = la; goto traffic; }
        u8 ob = REC(ROAD[la])[3];
        if (ob) sim_spawn_object(ob, la);
    }
    if (sub_unit < 0) goto advance;                       /* grip check & pull-over NOT repeated */
traffic: ...
```

Lateral motion and object spawning happen **per road unit crossed**, not per tick.

### 4.8 Spawning (0x467D)

```c
void sim_spawn_object(u8 ob, u16 la) {
    u8 k = ob & 0x3F, thr = ob & 0xC0;
    if (k == 1) {                                         /* radar trap */
        if (cop_state == 0 && rng_next() >= thr) radar_trap.pos = la + 40;
    } else if (k < 0x18) {
        if (k < 0x10 || k - 0x10 >= 5) return;            /* 0x10..0x14 oncoming */
        if (oncoming_count == 2 || cop_state != 0 || rng_next() < thr) return;
        memmove(&DS[0x094D], &DS[0x0945], 32);            /* head insert, 5th entry dropped */
        oncoming[0].pos = la + 15; oncoming[0].sub = 0; oncoming[0].type = (k - 0x10) * 40;  /* +4 left stale */
        oncoming_count++;
    } else if (k < 0x20) {
        if (k - 0x13 >= 10) return;                       /* 0x18..0x1C same direction, type 5..9 */
        if (samedir_count == 5 || (i8)cop_state >= 3 || demo_mode != 0 || rng_next() < thr) return;
        memmove(&DS[0x0975], &DS[0x096D], 32);
        samedir[0].pos = la + 15; samedir[0].sub = 0; samedir[0].type = (k - 0x13) * 40;
        samedir_count++; cop_block_idx++;
    } else if (k - 0x20 < 4) {                            /* hazard 0x20..0x23, always */
        hazard.pos = la; hazard.w6 = ((k - 0x20) << 4) | ((ob >> 6) << 8);   /* lane = top 2 bits */
    }
}
```

`thr` is 0, 0x40, 0x80 or 0xC0, so the spawn probability is 100%, 75%, 50% or 25%.

### 4.9 RNG (0x8BAF)

```c
u8 rng_next(void) { rng_index--; u8 i = (u8)rng_index; u8 v = RNG_TAB[i];
                    v = (u8)(v << 1) | (v < 0x80); RNG_TAB[i] = v; return v; }   /* seed: index 0, tables/rng_table.json */
```

Callers: the three spawn sites, plus **once per rendered frame** in `0x1DC0` (0x1E50). The sequence therefore depends on the frame rate. There is no time-based seeding.

### 4.10 Traffic lists (0x427F–0x4389)

```c
traffic:
    if (run_state != 2 && grind_timer) { grind_timer--; effect_tone_64FE = 0x474; }
    for (int i = 0; i < oncoming_count; i++) {            /* oncoming, drive toward player */
        Ent *e = &oncoming[i];
        i16 bp = e->pos - road_pos_prev;
        u16 pos = e->pos; i16 sub = e->sub - TRAFFIC_SPEED[speed_limit_idx / 2];
        if (sub < 0) { pos--; sub += 90; }
        i16 d = road_pos - pos;
        if ((d == 0 || (d ^ bp) >= 0) && car_x >= 0x25) { pos = road_pos + 1; sub = sub_unit; run_state = 3; }
        if (i != oncoming_count - 1) { u16 lim = oncoming[i+1].pos + 8; if (!((i16)pos > (i16)lim)) pos = lim; }
        e->sub = sub; e->pos = pos;
    }
    for (int k = 0; k < samedir_count; k++) {             /* same direction */
        Ent *e = &samedir[k];
        i16 bp = e->pos - road_pos_prev;
        u16 spd = (cop_state != 7 && (i8)cop_state >= 3) ? 120 : TRAFFIC_SPEED[speed_limit_idx / 2];
        u16 pos = e->pos; i16 sub = e->sub - spd;
        if (sub < 0) { pos++; sub += 90; if (sub < 0) { pos++; sub += 90; } }
        if (k != 0) { u16 lim = samedir[k-1].pos - 6; if (!((i16)lim > (i16)pos)) pos = lim; }
        i16 d = road_pos - pos;
        if (bp <= 0) { if (d <= 6) pos = road_pos - 6; }         /* cars behind never hit you */
        else if (d >= -1 && car_x <= 0x6C) { pos = road_pos + 1; sub = sub_unit; run_state = 3; }
        e->sub = sub; e->pos = pos;
    }
```

`TRAFFIC_SPEED[idx/2]` is the word at DS:0A1B+idx.

Collision lanes are simple bands: an oncoming car hits you if `car_x ≥ 37`; a same-direction car hits you if `car_x ≤ 108`.

### 4.11 Police state machine (0x438A–0x455E)

`bx = cop_pos`, `dx = cop_sub`. `adv(n)` means: `dx -= n; if dx < 0 { bx++; dx += 90; if dx < 0 { bx++; dx += 90; } }`.

| state | code | behaviour |
|---|---|---|
| 0 | – | Idle; skip to cleanup |
| 1 chase | 0x43A4 | `adv(cop_speed); cop_speed += 2; if cop_speed >= 120: cop_speed -= 2`. If `cop_block_idx` is set: `lim = samedir[idx-1].pos - 3; if lim <= bx { bx = lim; state = 2 }`. Then `lim = road_pos - 3`; if `lim <= bx` { `bx = lim; dx = sub_unit`; if `speed == 0` or `--cop_tail_timer == 0` → state 3 } else `cop_tail_timer = 120` |
| 2 pass car | 0x4414 | Wait while `oncoming_count != 0` (still stores). Otherwise `cop_timer += 2; cop_lateral = LANE[cop_timer]; bx = (cop_timer >> 3) - 3 + blk.pos; dx = blk.sub`. At `cop_timer == 0x30`: state 1, `cop_timer = 0`, `cop_block_idx--` |
| 3 pass player | 0x4467 | `cop_timer++`; lateral from table; `bx = (cop_timer >> 3) - 3 + road_pos; dx = sub_unit`. At 0x30: state 5, `cop_timer = 0x3C`, `cop_speed = (u8)(speed_hi + 5)` |
| 4, 5 lead and stop | 0x44A8 | If `cop_timer` → `cop_timer--`; else `if (--cop_speed <= 0)` { state 6, `cop_timer = 0x3C`, `speed = 0`, `cop_speed = 0` }. Then `adv(cop_speed)`. If `road_pos >= bx` → **hit the cop**: `run_state = 3, cars_left = 1` (**game over**), `bx = road_pos + 1, dx = sub_unit`. Else if `road_pos + 13 <= bx`: `bx = road_pos + 13`; if `!((i8)speed_hi > (i8)low(cop_speed))` then `low(cop_speed) = speed_hi`; `dx = sub_unit` |
| 6 stopped, ticket | 0x4526 | If `cop_timer` → `cop_timer--` (no move); else `cop_speed++`, `adv(cop_speed)`. The ticket is drawn by 0x349D while `state == 6 && cop_timer == 0` |
| 7 trap armed | 0x451B | Nothing (no store, no range check) |

For states 1–6 the code then stores `cop_pos = bx, cop_sub = dx`, and `if (bx - road_pos < -36 || bx - road_pos > 60) cop_state = 0`.

While `cop_state` is 3–6 (7 excluded):
* throttle is ignored;
* the car auto-steers to the shoulder (§4.7);
* no same-direction traffic spawns;
* same-direction traffic moves at 120.

### 4.12 Cleanup, radar trap, hazard (0x455F–0x4672)

```c
    if (oncoming_count) { Ent *l = &oncoming[oncoming_count-1];
        if ((i16)(road_pos - l->pos) > 40) { l->pos = 0; oncoming_count--; } }
    if (samedir_count)  { Ent *l = &samedir[samedir_count-1];
        if ((i16)(road_pos - l->pos) > 40) { l->pos = 0; samedir_count--; } }
    if (samedir_count && (i16)(road_pos - samedir[0].pos) < -60) {        /* head too far ahead */
        u8 n = --samedir_count;
        u16 di = 0x096D;
        if (n) { copy_forward(&DS[0x096D], &DS[0x0975], n * 16 /* words*2: BUG, should be n*8 */); di += n * 16; }
        DS_word[di] = 0;     /* n=3 clears radar_trap.pos; n=4 shifts trap<-hazard<-snapshot (Q1) */
    }
    if (radar_trap.pos) {
        i16 d = radar_trap.pos - road_pos;
        if (d < 0) {
            radar_trap.pos = 0;
            if (cop_state != 0) {                              /* was 7: start chase */
                u16 start = road_pos - 10; u8 n = 0;
                while (n != samedir_count && !((i16)start > (i16)samedir[n].pos)) n++;
                cop_pos = start; cop_state = 1; cop_speed = 60; cop_block_idx = n;
                cop_lateral = 0; cop_sub = 0; cop_timer = 0; cop_light_timer = 10;
            }
        } else if (d <= 8 && TRAP_SPEED[speed_limit_idx / 2] <= speed) cop_state = 7;
    }
    if (hazard.pos && hazard.pos < road_pos) hazard.pos = 0;            /* signed compare */
```

**Hazards (oil, potholes, gravel) have no effect on the simulation in TDEGA.** Only the renderer draws them (0x2C57, from the snapshot). No code outside the ISR and `0x1F4E`/`0x1F93` writes `speed`, `car_x`, `skidding`, `run_state` or `steer_angle` (verified by a disassembly sweep).

**Radar detector.** Scene_render `0x35C6` uses the snapshot of `radar_trap.pos` (DS:0A05):
* when `clock_ticks & 8` is set and `0 <= trap - 1 - road_pos`, it beeps (song 0xB0F);
* it lights `rad` sprite index `((trap-1-road_pos) >> 2) & 0xFC` / 4.

### 4.13 Car reset values (game_flow 0x1F93, for reference)

| Field | Value |
|---|---|
| speed | 0 |
| car_x | -0x75 |
| rpm, rpm_smooth | 800 |
| steer_angle, yaw_lateral, view_heading, DS:090E, DS:19CB, DS:19DD | 0 |
| run_state, gear, skidding, clock_running, DS:0938, cop_state, list counts, grind_timer | 0 |
| 13 object slots (DS:0945–09AC) | position word cleared |
| DS:64FC | `[DS:208F]` |
| DS:6500 | 900 |
| DS:64FE | 0xFFFF |
| knob_xy | `CAR.knob_xy[0]` |
| dash_timer | 13 |
| gearbox_dirty, gauges_dirty | 1 |
| gate_node | 1 |

At stage start, `0x1F4E` also sets:
* `road_pos = stage_ptr[stage] + 45`;
* `sub_unit = 0`, `clock_ticks = 0`, `speed_limit_idx = 0`;
* DS:1445 = 1, DS:1446 = 0.

## 5. Hardware / DOS dependencies

| Dependency | Where | SDL3 replacement |
|---|---|---|
| int 21h/35h, 25h: get/set int 8 → 0x3B1F; int 0 → DGROUP:1423 (divide-error handler: `add [bp+2],2`, skips the faulting 2-byte DIV) | 0x4908–0x493A | Drop. Drive `sim_timer_isr` logic from a fixed-step accumulator (100 Hz sub-steps, sim every 8th). Guard divisions in the renderer instead |
| PIT ch0 divisor 0x2E97 (via 0x698C) | platform | `SDL_GetTicksNS` accumulator |
| Chained far call to old int 8 with pushf | 0x3B28 | Call the sound tick function |
| `CLI` semantics: sim runs with interrupts off, and the frame loop reads its globals asynchronously | – | Run sim steps on the main thread before `0x2013`'s snapshot each frame |
| int 16h keyboard, port 201h joystick (0x5C24/0xA12F) | platform | SDL keyboard events with typematic emulation; SDL gamepad axes thresholded to the 4 bits |

## 6. Timing

| What | Rate | Notes |
|---|---|---|
| `rpm_smooth` slew, `engine_tone` store | 100 Hz | Engine note follows the slewed rpm, not `rpm` |
| Input poll, shifting, steering, engine, motion, traffic, police | 12.5 Hz (every 8th PIT tick) | Must be exact: every constant is per tick |
| `clock_ticks` DS:80A4 | 12.5 Hz while `clock_running` and `run_state != 2` | Crash penalty +240 (19.2 s); demo limit 720 (57.6 s) |
| Knob animation | 6 px per tick | A shift takes several ticks, and throttle/steering are ignored meanwhile |
| Cop timers 0x3C, 0x78 | 4.8 s, 9.6 s | |
| Rendering, snapshot, `rng_next` per frame | Frame rate | **Frame-rate dependent:** spawn probabilities are consumed per frame, and the renderer sees the ISR state only at snapshot time |

The ISR does nothing while `run_state == 3` (crash) or `isr_busy`. During `run_state` 1/2 it keeps running.

## 7. Open questions and quirks

* **Q1 – samedir head-removal bug** (0x45D1). The copy length is `count*8` words instead of `count*4`.
  * With 3 remaining cars it zeroes the radar trap.
  * With 4 it moves the hazard into the trap slot and snapshot bytes into the hazard slot.

  To stay faithful, keep DS:0945–0A14 as one byte array.
* **Q2** – In-game sound is data-driven. The simulation only writes the divisor slots DS:64FC (engine), DS:64FE (squeal 0x8E8 / grind 0x474 / off 0xFFFF) and DS:6500. Songs 0xB05 (engine loop) and 0xB0F (radar beep) reference them as notes 0x55–0x57. There is no crash or siren sound in the ISR; any such sound comes from game_flow/scene_render songs (`0x8A08` stops, `0x8A0E` queues). Two points unconfirmed:
  * whether the divisor slot is re-read on every note repeat (assumed yes);
  * the effect tone is set to 0xFFFF only on a unit advance, so it can persist while the car is stationary.
* **Q3** – In the fire-release path with `gear == 0`, `sim_update_rpm` returns DX unchanged, i.e. the raw DX left by `read_controls` (joystick bits or BIOS scan/ASCII). The clash test then uses garbage. Suggested approach: pass the last raw input word.
* **Q4** – Byte-wise negation in the lateral step: for `h` in -0xFF..-1 the car still drifts (`hi` becomes 1), and for other negative values with a nonzero low byte `hi` is one larger than `|h|>>8`. Positive `h < 0x100` gives no drift, so the motion is asymmetric. The grip test has the same pattern (`steer_angle` -0xFF..-1 is evaluated, 0..0xFF is not).
* **Q5** – In gear with no throttle, speed is held constant (no drag). This looks like a design choice.
* **Q6** – The exact meaning of the D-key toggle DS:08BE (shifter overlay vs. dashboard detail) is unconfirmed; see scene_render `0x351A`.
* **Q7** – Two unresolved details in `stage_enter_install_isr`:
  * `0x94C7` (called with far archive pointer, name string DS:0B16/0CEB/0DB4/0EFD/0F62, destination) is assumed to be a resource lookup;
  * the `0x5150(0x28,0x70,7)` buffer purpose is unknown.
* **Q8** – Cop state 4 is never assigned (it shares the state-5 handler).
* **Q9** – `cop_block_idx` is not adjusted when a head car is removed (Q1 path), so the cop may then treat the wrong car as its blocker.
* **Q10** – Road bytes ≥ 0x80 would index REC with a negative offset (cbw). They cannot occur in the shipped streams.
* **Q11** – Keyboard feel depends on BIOS typematic rate versus the 12.5 Hz poll. The choice of emulation is a port decision.
