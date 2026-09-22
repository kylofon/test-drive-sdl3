# platform_audio — Amiga sound effects, SMUS song player, Paula

Target: `td` (Amiga, Aztec C). Addresses are image addresses (base 0x10000), globals `D:xxxx` are offsets into the
data hunk (A4 = 0x1FC0E, `d16(A4)` = `D:(0x7FFE + d16)`). `int` is 16 bits. Confidence as in `port/RE_GUIDE.md`.
Sources: `tools/amigaidx.py dis` (ground truth), `port/amiga/decomp/td.c`, the sample/SMUS files on the disk.
File formats (sample header, SMUS chunks) are in `FORMATS.md` → "Amiga release" → "Samples" and "Songs"; this spec
does not repeat them and cites them where needed.

## 1. Overview

All Amiga sound is sampled 8-bit audio played by Paula's four DMA channels. The code writes the hardware
directly (`$DFF0A0-$DFF0DF`, DMACON `$DFF096`, INTENA/INTREQ `$DFF09A/$DFF09C`, ADKCON `$DFF09E`), takes over the
level-4 autovector (`$70`) for the audio interrupts, and uses exec only to add two vertical-blank interrupt servers
and for `Delay()`. There are two cooperating engines in the root hunk plus game-side triggers in overlays 1 and 2.

**Sfx engine** (0x12304–0x12612, handlers 0x12616 and 0x126AE). One 0x1E-byte record per Paula channel at D:0446.
`start_channel` only fills the record and marks it *pending*; the `Sfx VBLInt` server (priority 0x1E) writes
AUDxLC/LEN/PER/VOL and turns the DMA on at the next vertical blank, but never less than 2 VBL ticks after that
channel was last stopped. The level-4 audio interrupt counts sample repeats and stops the channel after the
requested number of passes (−1 = loop forever). The VBL server also runs a per-channel linear volume slide in
16.16 fixed point. `set_period_vol` writes the period/volume registers immediately.

**Song player** (0x1278C–0x12F1A, server 0x12A54). An IFF SMUS interpreter run by the `Song VBLInt` server
(priority 0x20, so it runs before the sfx server in the same vertical blank). Fixed tempo (quarter note = 24 VBL
ticks), up to 4 tracks, track k on Paula channel k. Each track has a caller-chosen instrument: either a looped
waveform written straight to Paula (the channel is then excluded from the sfx engine's audio interrupt) or a
one-shot sample played through the sfx engine. Songs loop forever until stopped. A global 16.16 song volume with
its own slide gives fade in/out.

**Triggers.** Title (overlay 1): `TestDrive` song, `Sfx/Accolade` (music ducked to 7 while it plays) and
`Sfx/Starter`, all on channel 3. Showroom drive-away: `Sfx/Starter` on channel 3. Car select: `Test2`; gas
station: `TestGas`; ending: `EndSuccess`; high-score screen: `TestDrive` again. During the drive (overlay 2) the
four channels are fixed: 0 = one-shots `Radar` and `Bump`, 1 = `Squeal` loop, 2 = `TheTurbo` loop, 3 =
`TheEngine` loop. The loops run for the whole stage; the engine code only changes their period and volume once
per drive frame.

Keys (handled in 0x10462, see game_flow): `S` toggles sound effects (D:0344; turning them off stops all four
channels), `M` toggles music (D:04CC; turning it off stops the song).

```
main 0x10018
 ├─ 0x12304 sfx_init ──────────── installs 0x12616 (level-4 vector) + Sfx VBLInt 0x126AE
 ├─ 0x1278C song_init ─────────── installs Song VBLInt 0x12A54, song volume 0x10
 ├─ 0x12E12 / 0x12E58 play TestDrive / Test2 ─┐
 │      0x147E4 → 0x12E8A TestGas             ├─ 0x12CF4 song_play ─┬─ 0x12DB0 song_stop (other song loaded)
 │      0x1C900 → 0x12EBE EndSuccess          │                     ├─ 0x149D2 load_file("songs/<f>")
 │      (0x12EF6 Loser: no caller)           ─┘                     ├─ 0x12826 song_load_instruments
 │                                                                  ├─ 0x12432 sfx_set_song_channels(mask)
 │                                                                  ├─ 0x12942 song_set_volume
 │                                                                  └─ 0x12972 song_start → 0x1299C, 0x129BA
 ├─ 0x1AED0 title:  0x1246A play_sample(Accolade/Starter, 3, 0x40), 0x1258E busy(3), 0x12942 duck
 ├─ 0x1C244 showroom: 0x1246A(Starter, 3, 0x40) … 0x12546 sfx_stop_channel(3)
 ├─ 0x1C900 drive: 0x26B7A load sfx · 0x12DB0 · 0x26C70 engine_sound_start · per frame
 │      0x20CB0 → 0x20826 → 0x26D4E engine_sound_update ─┬─ 0x26E26 squeal_update → 0x125A6
 │                                                       ├─ 0x26EE2 bump_update → 0x1258E, 0x1246A
 │                                                       └─ 0x125A6 set_period_vol, 0x125F4 slide
 │      0x1EC94 radar lamp → 0x26C50 radar_beep → 0x1246A
 │      stage end / crash: 0x26D16 engine_sound_fade_out · end of drive: 0x26C02 free sfx
 └─ exit: 0x12DB0, 0x127F4 song_shutdown, 0x123EC sfx_shutdown

VBL (60 Hz): Song VBLInt 0x12A54 (pri 0x20) → Sfx VBLInt 0x126AE (pri 0x1E) → … → Ticks VBLInt 0x118B2 (pri −0x50)
Level 4:     0x12616 audio interrupt (channels in D:1E9E only)
```

## 2. Function table

"DOS equivalent" gives the DOS function (port/symbols.csv) with the same *role*. No Amiga audio function is
the same logic as a DOS one: the DOS game drives the PC speaker from a bytecode interpreter in the 100 Hz timer
ISR (port/spec/platform.md §4.6), so only the triggers map across.

| image addr | proposed name | signature | one-line purpose | DOS equivalent | confidence |
|---|---|---|---|---|---|
| 0x12304 | sfx_init | `void (void)` | Clears channel records, audio DMA/INT off, ADKCON 0xFF, hooks `$70` → 0x12616, AddIntServer(VERTB, Sfx VBLInt pri 0x1E) | 0x69CF timer_install_common (sound init part) | verified |
| 0x123EC | sfx_shutdown | `void (void)` | Stops all, Delay(5), RemIntServer, audio INT/DMA off, restores `$70` | 0x694A timer_restore | verified |
| 0x12432 | sfx_set_song_channels | `void (int mask)` | D:1E9E = `(~mask & 0xF) << 7`; channels in `mask` lose the audio interrupt (song waveforms) | — | verified |
| 0x1246A | play_sample | `void (sample *s, int ch, int vol)` | period = 0x369E99 / rate; start_channel(s+6, s->len, ch, period, vol, 1) | 0x8A3E snd_play_oneshot (role) | verified |
| 0x124C4 | start_channel | `void (u8 *data, long len, int ch, int period, int vol, int repeats)` | Stops the channel if busy, fills the record, marks it pending | — | verified |
| 0x1252A | snd_stop_all | `void (void)` | sfx_stop_channel(0..3) | 0x8A08 snd_stop_all | verified |
| 0x12546 | sfx_stop_channel | `void (int ch)` | DMA off, AUDxVOL 0, record idle, stop tick = D:04C2 | — | verified |
| 0x1258E | sfx_channel_busy | `int (int ch)` | −1 if the record has a data pointer, else 0 | 0x8A02 snd_oneshot_active | verified |
| 0x125A6 | sfx_set_period_vol | `void (int ch, int period, int vol)` | Immediate AUDxPER (if ≥ 0) / AUDxVOL + record volume, cancels slide (if ≥ 0) | — (DOS patches DS:64FC–6500) | verified |
| 0x125F4 | sfx_slide_volume | `void (int ch, int target, long step)` | Starts a 16.16 volume slide run by the VBL server | — | verified |
| 0x12612 | (data) saved_a4 | long | A4 saved for the level-4 handler (written by 0x12304) | — | verified |
| 0x12616 | sfx_audio_int | level-4 autovector | Per sfx channel: count repeats, stop when done; acks INTREQ | — | verified |
| 0x126AE | sfx_vbl_server | exec VERTB server (A0 = custom, A1 = A4) | Tick D:04C2, start pending channels, run volume slides | 0x6A1F timer_isr (sound part) | verified |
| 0x1278C | song_init | `void (void)` | AddIntServer(VERTB, Song VBLInt pri 0x20); volume 0x10 immediately | 0x699E timer_install_menu (role) | verified |
| 0x127F4 | song_shutdown | `void (void)` | song_request_stop, Delay(3), free instruments, RemIntServer | 0x694A timer_restore (role) | verified |
| 0x12826 | song_load_instruments | `void (char *names[4], int oneshot[4])` | Loads `songs/<name>` into chip RAM per track; name ≤ 10 = copy slot n | — | verified |
| 0x128FE | song_free_instruments | `void (void)` | Frees the owned instrument samples | — | verified |
| 0x12942 | song_set_volume | `void (int vol, long step)` | Target D:1EF8 = vol<<16, step D:1EF0 (0 = jump) | — | verified |
| 0x1295E | song_get_volume | `int (void)` | D:1EF4 high word, or 0 when the player is idle | — | verified |
| 0x12972 | song_start | `void (u8 *smus)` (stack) | If server installed and music on: request stop, then 0x129BA with d0 = 6 | — | verified |
| 0x1299C | song_request_stop | asm, saves all | State 1/2 → 3 (does not really wait, see §4.9) | 0x89F0 snd_stop_oneshot (role) | verified |
| 0x129BA | song_setup | asm: a0 song, a1 inst[4], a2 oneshot[4], d0 base | Copies instruments to the track records, builds the duration table, state = 1 | — | verified |
| 0x12A40 | song_is_active | `int (void)` | −1 if state is 1 or 2 | — | verified |
| 0x12A54 | song_vbl_server | exec VERTB server (A1 = A4) | Volume slide; state 1 parse, 2 play one tick, 3 stop | 0x6AA8 snd_fetch (+ 0x6A1F) | verified |
| 0x12C98 | song_volume_slide | asm | Moves D:1EF4 toward D:1EF8 by D:1EF0 | — | verified |
| 0x12CDC | smus_find_long | asm: a0 base, d0 start, d1 limit, d2 id | Searches for a long in 2-byte steps; carry = found | — | verified |
| 0x12CF4 | song_play | `void (char *file, char *inst[4], int oneshot[4], int mask, int vol)` | Starts a song (or just fades in if it is already loaded) | 0x8A3E snd_play_oneshot (game_flow "song_play") | verified |
| 0x12DB0 | song_stop | `void (void)` | Fade out at 0x5400/tick, wait, stop, Delay(2), free everything | 0x89F0 snd_stop_oneshot (game_flow "song_stop") | verified |
| 0x12E12 | song_play_testdrive | `void (void)` | `TestDrive.Iff.Sng`, inst D:08C6, oneshot D:08D6, mask 1, vol 0x20 | intro sng2 (0x037A) and high-score sng3 (0x1482) calls of 0x8A3E | verified |
| 0x12E58 | song_play_test2 | `void (void)` | `Test2.Iff.Sng`, D:08DE/D:08EE, mask 3, vol 0x16 | car-select sng4 call (0x098C) | verified |
| 0x12E8A | song_play_testgas | `void (void)` | `TestGas.Iff.Sng`, same instruments, mask 3, 0x16 | gas-station sng1 call (0x1993) | verified |
| 0x12EBE | song_play_endsuccess | `void (void)` | `EndSuccess.Iff.Sng`, same, mask 3, 0x16 | — (DOS ending has no song) | verified |
| 0x12EF6 | song_play_loser | `void (void)` | `Loser.Iff.Sng`, same; **no caller** | — | verified |
| 0x26B7A | sfx_load_drive | `void (void)` | Loads `sfx/Radar`, `TheEngine`, `TheTurbo`, `Squeal`, `Bump` (chip) into D:1BAE–D:1BBE | 0x4792 stage_enter_install_isr (sound part) | verified |
| 0x26C02 | sfx_free_drive | `void (void)` | Frees the five samples (channels not stopped) | — | verified |
| 0x26C50 | radar_beep | `void (void)` (saves regs) | If sfx on: play_sample(Radar, 0, 0x40) | 0x35C6 draw_dashboard_dynamic (beep at 0x35E2) | verified |
| 0x26C70 | engine_sound_start | `void (void)` | Starts Squeal/TheTurbo/TheEngine loops at volume 0, fades the engine in | 0x8A0E snd_set_loop(DS:0B05) | verified |
| 0x26D16 | engine_sound_fade_out | `void (void)` | Slides channels 1–3 to 0 at 0x7000/tick | 0x8A08 snd_stop_all (stage end/crash) | verified |
| 0x26D4E | engine_sound_update | `void (void)` (saves regs) | Per drive frame: squeal, bump, engine period, turbo volume/period | 0x3B1F sim_timer_isr (engine divisor part) | verified |
| 0x26E26 | squeal_update | asm (no frame) | Squeal volume = skid amount, or the shift-chirp envelope | DOS DS:64FE writes (0x40A7/0x40D5, 0x4269) | verified |
| 0x26E7E | squeal_env_volume | `int[25]` table | 18 × 0x40, 0x3C, 0x32, 0x2D, 0x20, 0x14, 0x0A, 0 | — | verified |
| 0x26EB0 | squeal_env_period | `int[25]` table | 0x15C … 0x18B … 0x14F (see §4.13) | — | verified |
| 0x26EE2 | bump_update | asm (no frame) | If D:0D9A or D:19BE and channel 0 idle and sfx on: play Bump | — | verified |
| 0x10018 | main | | Calls the init/shutdown and song functions | see game_flow | — |
| 0x10462 | poll_hotkeys | | `S` / `M` toggles (§4.16); rest see game_flow | 0x6846 getkey_kbd_ctrl | see game_flow |
| 0x1042E / 0x1044C | (blitter priority, see platform_video) | | Writes `$BFF096` (not a CIA, not the filter; §5) | — | see platform_video |
| 0x1AED0 | title | | Sound calls in §4.15 | see title_select | — |
| 0x1C244 | showroom_drive_away | | Starter on channel 3 | see title_select | — |
| 0x1C900 | drive | | Calls 0x26B7A, 0x12DB0, 0x26C70, 0x26D16, 0x12EBE, 0x26C02 | see game_flow | — |
| 0x147E4 | gas_station | | Calls 0x12E8A | see game_flow | — |
| 0x1EC94 | radar_lamp | | Calls 0x26C50 | see drive_scene | — |
| 0x207A4, 0x20826, 0x20CB0 | gearbox/engine sim | | Set D:15FE, call 0x26D4E | see drive_sim | — |
| 0x24A04 | skid | | Sets D:19BC (skid volume) and D:19BE | see drive_sim | — |
| 0x1E6A6, 0x1E73A | road-edge check | | Set D:0D9A | see drive_sim | — |
| 0x175EA | Delay | `void (long ticks)` | dos.library Delay (−0xC6), 1/50 s | 0x6C3B delay_ticks | verified |
| 0x1769A / 0x1794C | AddIntServer / RemIntServer | `(long intnum, Interrupt *)` | exec glue | — | likely |
| 0x16ED8 | ldiv | `long (long a, long b)` in d0/d1 | Signed 32-bit division (Aztec runtime) | — | verified |

## 3. Globals table

| D: offset | proposed name | type | meaning | written by | read by |
|---|---|---|---|---|---|
| D:0344 | sfx_enabled | int, init 1 | `S` key. Gates only play_sample calls and the engine fade-in (§4.17) | 0x10462 | 0x1AED0, 0x1C244, 0x26C50, 0x26C70, 0x26EE2 |
| D:0444 | sfx_installed | int | sfx_init done | 0x12304, 0x123EC | 0x12432 |
| D:0446 + 0x1E·ch | sfx_chan[4] | struct ×4 (to D:04BE) | see layout below | sfx functions, 0x12616, 0x126AE | same |
| D:04BE | old_level4_vector | long | saved `$70` | 0x12304 | 0x123EC |
| D:04C2 | sfx_tick | long | +1 per VBL in the sfx server | 0x12304, 0x126AE | 0x12546, 0x12616, 0x126AE |
| D:04C6 | sfx_dma_set | int | DMACON value built by the VBL server (0x8000 \| channels to start) | 0x126AE | 0x126AE |
| D:04C8 | sfx_saved_intena | int | INTENAR & 0x780 while the VBL server runs | 0x126AE | 0x126AE |
| D:04CA | song_installed | int | Song server added | 0x1278C, 0x127F4 | 0x12972 |
| D:04CC | music_enabled | int, init 1 | `M` key | 0x10462 | 0x12972, 0x129BA, 0x12CF4 |
| D:04CE | song_inst_loaded | int | Instruments loaded | 0x12826, 0x128FE | same |
| D:0500 | note_period_table | long[132] | `0x369E99 / f(note)`, note 69 = 440 Hz; notes 0–23 = octave 24–35. Indexed as D:05F0 + 4·(note − 0x3C) | const | 0x12A54 |
| D:0710 | note_ticks | int[16] | Ticks per SMUS duration code; codes 0–4 and 8–12 rebuilt by 0x129BA (§4.10); init 256,128,64,32,8,0,0,0,368,184,92,48,24,12,0,0 | 0x129BA | 0x12A54 |
| D:0732 | song_state | int | 0 idle, 1 (re)start, 2 playing, 3 stop request | 0x1278C, 0x1299C, 0x129BA, 0x12A54 | 0x1295E, 0x12A40, 0x12A54 |
| D:0734 | song_any_active | int | Set by the tick when a processed track is active | 0x1278C, 0x12A54 | 0x12A54 |
| D:0736 | song_data | long (u8 *) | SMUS file buffer | 0x1278C (clr), 0x129BA | 0x12A54 |
| D:073A + 0x18·k | song_track[4] | struct ×4 (to D:079A) | see layout below | 0x129BA, 0x12A54 | 0x12A54 |
| D:08BA | song_dma_on | int | Channels whose DMA must be switched on this tick | 0x12A54 | 0x12A54 |
| D:08BC | song_dma_off | int | Channels whose DMA must be switched off this tick | 0x12A54 | 0x12A54 |
| D:08BE | smus_tempo | int | SHDR tempo — never used | 0x12A54 | — |
| D:08C0 | smus_volume | int | SHDR volume byte (sign-extended) — never used | 0x12A54 | — |
| D:08C2 | song_buffer | long | Loaded SMUS file (0 = none) | 0x12CF4, 0x12DB0 | same |
| D:08C6 | testdrive_inst | char *[4] | "BuzzSynth", "Drum2", "Drum", 0 | const | 0x12E12 |
| D:08D6 | testdrive_oneshot | int[4] | 0, 1, 1, 0 | const | 0x12E12 |
| D:08DE | song_inst | char *[4] | "BuzzSynth", 0, "Drum", 0 (0 = copy slot 0) | const | 0x12E58–0x12EF6 |
| D:08EE | song_oneshot | int[4] | 0, 0, 1, 0 | const | same |
| D:1E9A | sfx_server_a4 | long | is_Data of the sfx server (= A4) | 0x12304 | 0x12304 |
| D:1E9E | sfx_int_channels | int | INTENA bits (7–10) of the channels the audio interrupt handles | 0x12432 | 0x12432, 0x12616 |
| D:1EA0 | sfx_vbl_interrupt | struct Interrupt (0x16) | ln_Type D:1EA8 = 2, ln_Pri D:1EA9 = 0x1E, ln_Name D:1EAA, is_Data D:1EAE, is_Code D:1EB2 = 0x126AE | 0x12304 | exec |
| D:1EB6 | song_server_a4 | long | is_Data (= A4) | 0x1278C | 0x1278C |
| D:1EBA | song_vbl_interrupt | struct Interrupt | ln_Pri D:1EC3 = 0x20, name D:1EC4, is_Data D:1EC8, is_Code D:1ECC = 0x12A54 | 0x1278C | exec |
| D:1ED0 | song_inst_ptr | long[4] | Instrument sample per track | 0x12826 | 0x128FE, 0x12972 |
| D:1EE0 | song_inst_owned | int[4] | 1 = loaded here (freed by 0x128FE) | 0x12826 | 0x128FE |
| D:1EE8 | song_inst_oneshot | int[4] | Copied from the caller | 0x12826 | 0x12972 |
| D:1EF0 | song_vol_step | long 16.16 | Slide step (0 = jump) | 0x12942 | 0x12C98 |
| D:1EF4 | song_volume | long 16.16 | Current song volume; notes use the high word | 0x12C98 | 0x1295E, 0x12A54 |
| D:1EF8 | song_vol_target | long 16.16 | −1 = no slide | 0x12942, 0x12C98 | 0x12C98 |
| D:2E28 | song_name | char[] | Name of the loaded song (`sprintf "%s"`) | 0x12CF4 | 0x12CF4 (strcmp) |
| D:1BAE | sfx_radar | sample * | `sfx/Radar` | 0x26B7A, 0x26C02 | 0x26C50 |
| D:1BB2 | sfx_engine | sample * | `sfx/TheEngine` | same | 0x26C70 |
| D:1BB6 | sfx_turbo | sample * | `sfx/TheTurbo` | same | 0x26C70 |
| D:1BBA | sfx_squeal | sample * | `sfx/Squeal` | same | 0x26C70 |
| D:1BBE | sfx_bump | sample * | `sfx/Bump` | same | 0x26EE2 |
| D:1BC2 | engine_period | int | Last engine period (channel 3) | 0x26D4E | 0x26D4E |
| D:15FE | squeal_env | int | Chirp envelope index, −1 = off; set to 0 / 0x0B by 0x207A4 | 0x207A4, 0x26C70, 0x26E26 | 0x26E26 |
| D:19BC | skid_volume | int 0..0x40 | Skid excess = steady squeal volume | 0x24A04, 0x26C70, 0x26E26 | 0x24AA8, 0x26E26 |
| D:19BE | bump_edge | int | Nonzero when D:0D80 ≠ 0 and D:0D80 & 3 is 0 or 2, i.e. hazard objects 0x20 and 0x22 (table 0x24A98 = 1, 0, −1, 0) | 0x24A04, 0x26EE2 | 0x26EE2 |
| D:0D9A | bump_marker | int | Set −1 by the road-edge checks 0x1E6A6/0x1E73A | 0x1E6A6, 0x1E73A, 0x26EE2 | 0x26EE2 |
| D:0D72 | squeal_mute (drive_sim: `lane_hold`) | int | Demo, finishing zone (D:0B2E) or D:0D76 ≥ 0x46 (police tail frames); the autopilot / pull-over lane hold, which also mutes the squeal (see drive_sim) | 0x1C900, 0x2484C | 0x26E26 |

Read from other specs by 0x26D4E (names *likely*, owned by drive_sim): D:191A rpm (int), D:191E gear (0 =
neutral), D:1922 pedal (> 0 accelerate, 0 none, < 0 brake), D:28A6 speed (long 16.16; the high word = mph is
read), D:192A car record +006 (engine-sound flag, FORMATS.md "Car record").

**Channel record** (D:0446 + 0x1E·ch):

| off | type | field |
|---|---|---|
| +00 | long | data pointer (0 = idle) |
| +04 | long | sfx_tick of the last stop |
| +08 | int | start pending (−1) |
| +0A | int | length in words |
| +0C | int | period at start |
| +0E | long | volume 16.16 (high word = 0..64) |
| +12 | int | repeats (−1 = forever) |
| +14 | int | repeats left |
| +16 | long | slide target 16.16 (−1 = none; tested as a word) |
| +1A | long | slide step 16.16 |

**Track record** (D:073A + 0x18·k):

| off | type | field |
|---|---|---|
| +00 | int | active (−1) |
| +02 | long | instrument sample (header pointer) |
| +06 | int | one-shot flag |
| +08 | long | TRAK size in bytes |
| +0C | long | TRAK data pointer |
| +10 | long | read position (bytes) |
| +14 | int | countdown (ticks) |
| +16 | int | tie flag (not reset between songs in the original: bug 12) |

## 4. Pseudocode

Types: `int` = s16, `u16`, `long` = s32. `AUD[ch]` = the Paula register block `$DFF0A0 + 0x10·ch`
(`LC` long +0, `LEN` +4, `PER` +6, `VOL` +8). `DMACON` writes use bit 15 as set/clear.
`g_original_bugs` is the port's `--original-bugs` flag (not an Amiga global): its branch is the original
behaviour, the other the default fix (port/amiga/README.md, *Original bugs*; this spec owns bugs 8, 9, 10, 12).

### 4.1 sfx_init (0x12304) / sfx_shutdown (0x123EC)

```c
void sfx_init(void) {
    if (sfx_installed) return;
    sfx_set_song_channels(0);                 /* D:1E9E = 0x780 (no INTENA write: not installed yet) */
    saved_a4 = A4;  sfx_server_a4 = A4;       /* 0x12612 is a long inside the code hunk */
    sfx_tick = 0;
    for (ch = 0; ch < 4; ch++) {
        chan[ch].data = 0;
        *(long *)&chan[ch].pending = 0;       /* clr.l clears +08 pending and +0A len */
        chan[ch].target = -1;
    }
    INTENA = 0x0780;                          /* audio interrupts off */
    DMACON = 0x000F;                          /* audio DMA off */
    ADKCON = 0x00FF;                          /* no modulation */
    old_level4_vector = *(long *)0x70;  *(long *)0x70 = 0x12616;
    for (ch = 0; ch < 4; ch++) chan[ch].stop_tick = sfx_tick;   /* = 0 */
    INTENA = 0x8780;                          /* audio interrupts on */
    sfx_vbl_interrupt = { NT_INTERRUPT, pri 0x1E, "Sfx VBLInt", A4, 0x126AE };
    AddIntServer(INTB_VERTB /*5*/, &sfx_vbl_interrupt);
    sfx_installed = 1;
}
void sfx_shutdown(void) {
    if (sfx_installed) {
        snd_stop_all(); Delay(5);
        RemIntServer(5, &sfx_vbl_interrupt);
        INTENA = 0x0780; DMACON = 0x000F;
        *(long *)0x70 = old_level4_vector;
    }
    sfx_installed = 0;
}
```

### 4.2 sfx_set_song_channels (0x12432)

```c
void sfx_set_song_channels(u16 mask) {         /* mask: channels played as song waveforms */
    sfx_int_channels = (~mask & 0xF) << 7;      /* INTENA bits AUD0..AUD3 = 7..10 */
    if (sfx_installed) {
        u16 v = sfx_int_channels | 0x8000;
        INTENA = v;                             /* enable the sfx channels */
        INTENA = v ^ 0x8780;                    /* clear (bit 15 now 0) the other audio bits */
    }
}
```

### 4.3 play_sample (0x1246A), start_channel (0x124C4)

```c
void play_sample(sample *s, int ch, int vol) {
    if (!s) return;
    u16 rate = s->rate;                        /* +4 */
    if (rate < 100) rate = rate * 1000;        /* unsigned compare; mulu.w */
    int period = (int)ldiv(0x369E99, (long)rate);   /* 3579545 = NTSC Paula clock (the port's clock) */
    start_channel((u8 *)s + 6, s->len /*+0 long*/, ch, period, vol, 1);
}

void start_channel(u8 *data, long len, int ch, int period, int vol, int repeats) {
    if (!data) return;
    if (sfx_channel_busy(ch)) sfx_stop_channel(ch);
    c = &chan[ch];
    c->len_words = (int)((unsigned long)len >> 1);   /* odd last byte dropped */
    c->period = period;
    c->vol = (long)vol << 16;                  /* word write at +0E, clr.w +10 */
    c->repeats = repeats;
    c->data = data;
    c->target = -1;
    c->pending = -1;                           /* the VBL server starts it */
}
```
Period results (NTSC constant): Accolade 357, Starter 715, Radar 178, Bump 380, Drum 250, Drum2 357.

### 4.4 sfx_stop_channel (0x12546), snd_stop_all (0x1252A), sfx_channel_busy (0x1258E)

```c
void sfx_stop_channel(u16 ch) {
    chan[ch].pending = 0;
    DMACON = 1 << ch;                          /* clear */
    chan[ch].target = -1;
    AUD[ch].VOL = 0;
    chan[ch].stop_tick = sfx_tick;
    chan[ch].data = 0;
}
void snd_stop_all(void) { for (int ch = 0; ch < 4; ch++) sfx_stop_channel(ch); }
int  sfx_channel_busy(int ch) { return chan[ch].data ? -1 : 0; }
```

### 4.5 sfx_set_period_vol (0x125A6), sfx_slide_volume (0x125F4)

```c
void sfx_set_period_vol(int ch, int period, int vol) {
    if (period >= 0) AUD[ch].PER = period;     /* record +0C is NOT updated */
    if (vol >= 0) {
        chan[ch].target = -1;                  /* cancels a slide */
        chan[ch].vol = (long)vol << 16;
        AUD[ch].VOL = vol;
    }
}
void sfx_slide_volume(int ch, int target, long step) {
    chan[ch].step = step;
    chan[ch].target = (long)target << 16;      /* move.l 6(a7),d1 ; clr.w d1 */
}
```

### 4.6 sfx_audio_int (0x12616), level-4 autovector

```c
void sfx_audio_int(void) {                     /* rte; saves d0-d4/a0-a1/a4/a6, A4 = saved_a4 */
    u16 pend = INTREQR & INTENAR & 0x0780;
    INTREQ = pend & ~sfx_int_channels;         /* ack the song channels' requests */
    pend &= sfx_int_channels;
    for (ch = 0; ch < 4; ch++) {
        if (!(pend & (0x80 << ch))) continue;
        c = &chan[ch];
        if (c->data == 0 || (c->left >= 0 && --c->left < 0)) {   /* stops when left was 0 */
            c->target = -1;
            AUD[ch].VOL = 0;
            c->vol = 0;
            AUD[ch].PER = 0x96;
            DMACON = 1 << ch;
            c->stop_tick = sfx_tick;
            c->data = 0;
        }
        INTREQ = 0x80 << ch;
    }
}
```
Paula requests the channel's interrupt each time it (re)loads LC/LEN, i.e. at the start of every pass. The VBL
server sets `left = repeats` before enabling DMA, so the first interrupt makes it `repeats − 1` and the
interrupt at the start of pass `repeats + 1` stops the channel: `repeats = n` plays exactly n passes, a negative
count loops for ever (`left` stays negative).

### 4.7 sfx_vbl_server (0x126AE)

```c
int sfx_vbl_server(custom *A0, long A1 /* = A4 */) {
    sfx_tick++;
    sfx_saved_intena = A0->INTENAR & 0x0780;
    A0->INTENA = 0x0780;                        /* keep the audio interrupt out while editing records */
    sfx_dma_set = 0x8000;
    for (ch = 0; ch < 4; ch++) {
        c = &chan[ch];
        if (c->pending && sfx_tick - c->stop_tick >= 2) {         /* signed long compare */
            AUD[ch].LC = c->data;  AUD[ch].LEN = c->len_words;
            AUD[ch].PER = c->period;  AUD[ch].VOL = (int)(c->vol >> 16);
            c->left = c->repeats;
            sfx_dma_set |= 1 << ch;
            c->pending = 0;
        }
        if ((int)(c->target >> 16) >= 0) {                       /* tst.w on the high word */
            long v = c->vol;
            if (v == c->target)                     { v = c->target; c->target = -1; }
            else if (v > c->target) { v -= c->step; if (v <= c->target) { v = c->target; c->target = -1; } }
            else                    { v += c->step; if (v >= c->target) { v = c->target; c->target = -1; } }
            c->vol = v;
            AUD[ch].VOL = (int)(v >> 16);       /* written even when the channel is idle */
        }
    }
    if (sfx_saved_intena) A0->INTENA = sfx_saved_intena | 0x8000;
    if ((u8)sfx_dma_set) A0->DMACON = sfx_dma_set;               /* tst.b on the low byte */
    return 0;                                                     /* Z set: continue the chain */
}
```
Consequences: a start is delayed to the next VBL; a *restart* of a busy channel (start_channel stops it, stop_tick
= now) is delayed until `sfx_tick` has advanced twice, i.e. one full VBL of silence. A zero step with
`vol != target` never finishes (the engine callers never pass 0).

### 4.8 song_init (0x1278C), song_shutdown (0x127F4), instruments (0x12826, 0x128FE)

```c
void song_init(void) {
    if (!song_installed) {
        song_server_a4 = A4; song_state = 0; *(long *)&song_any_active = 0;  /* clr.l: D:0734-D:0737 */
        song_vbl_interrupt = { NT_INTERRUPT, pri 0x20, "Song VBLInt", A4, 0x12A54 };
        AddIntServer(5, &song_vbl_interrupt);
    }
    song_installed = 1;
    song_set_volume(0x10, 0);
}
void song_shutdown(void) {
    if (song_installed) { song_request_stop(); Delay(3); song_free_instruments(); RemIntServer(5, &song_vbl_interrupt); }
    song_installed = 0;
}
void song_load_instruments(char *names[4], int oneshot[4]) {
    if (!song_inst_loaded)
        for (int i = 0; i < 4; i++) {
            if ((unsigned long)names[i] <= 10) {             /* "same as slot n" */
                song_inst_ptr[i] = song_inst_ptr[(long)names[i]];
                song_inst_owned[i] = 0;
            } else {
                char path[40]; sprintf(path, "songs/%s", names[i]);
                song_inst_ptr[i] = load_file_chip(path);      /* 0x149E8; 0 on failure */
                song_inst_owned[i] = 1;
            }
            song_inst_oneshot[i] = oneshot[i];
        }
    song_inst_loaded = 1;
}
void song_free_instruments(void) {
    if (song_inst_loaded) for (i = 0; i < 4; i++) if (song_inst_owned[i]) free_mem(song_inst_ptr[i]);  /* 0x159FA */
    song_inst_loaded = 0;
}
```
(D:0734 is cleared as a long, which also clears the high word of the pointer D:0736.)

### 4.9 Volume and state helpers (0x12942, 0x1295E, 0x12972, 0x1299C, 0x12A40, 0x12C98)

```c
void song_set_volume(int vol, long step) { song_vol_step = step; song_vol_target = (long)vol << 16; }
int  song_get_volume(void)  { return song_state ? (int)(song_volume >> 16) : 0; }
int  song_is_active(void)   { return (song_state != 0 && song_state != 3) ? -1 : 0; }

void song_request_stop(void) {                 /* 0x1299C */
    if (song_state) song_state = 3;
    while (song_is_active()) ;                 /* returns at once: state is now 0 or 3 */
}
void song_start(u8 *smus) {                    /* 0x12972 */
    if (song_installed && music_enabled) {
        song_request_stop();
        song_setup(smus, song_inst_ptr, song_inst_oneshot, 6);
    }
}
void song_volume_slide(void) {                 /* 0x12C98, called by the server every tick */
    if ((int)(song_vol_target >> 16) < 0) return;
    long v = song_volume;
    if (song_vol_step != 0 && v != song_vol_target) {
        if (v < song_vol_target) { v += song_vol_step; if (v <  song_vol_target) { song_volume = v; return; } }
        else                     { v -= song_vol_step; if (v >  song_vol_target) { song_volume = v; return; } }
    }
    song_volume = song_vol_target; song_vol_target = -1;
}
```
Because song_start overwrites the state with 1 right after requesting 3, the server never sees the 3: the
restart path (state 1) reinitialises the tracks without stopping the channels first.

### 4.10 song_setup (0x129BA)

```c
void song_setup(u8 *smus /*a0*/, sample *inst[4] /*a1*/, int oneshot[4] /*a2*/, u16 base /*d0 = 6*/) {
    if (!music_enabled) return;
    song_data = smus;
    for (k = 0; k < 4; k++) { track[k].inst = inst[k]; track[k].oneshot = oneshot[k]; }
    note_ticks[4] = base;       note_ticks[3] = base << 1; note_ticks[2] = base << 2;
    note_ticks[1] = base << 3;  note_ticks[0] = base << 4;             /* 6, 12, 24, 48, 96 */
    u16 d = base + (base >> 1);                                        /* 9 */
    note_ticks[12] = d;  note_ticks[11] = d << 1; note_ticks[10] = d << 2;
    note_ticks[9]  = d << 3; note_ticks[8] = d << 4;                   /* 9, 18, 36, 72, 144 */
    song_state = 1;
}
```
Codes 5–7, 13–15 keep their initial values 0, 0, 0, 12, 0, 0 (a 0 would give a countdown of −1 = 65535 ticks);
the five songs only use codes 0–4 and 9–11.

### 4.11 song_vbl_server (0x12A54)

```c
int song_vbl_server(void /* A1 = A4 */) {
    if (song_state == 0) return 0;
    song_volume_slide();
    if (song_state == 1) {                                         /* (re)start: parse the file */
        ADKCON = 0x00FF;
        for (k = 0; k < 4; k++) {
            track[k].active = 0;
            if (!g_original_bugs) track[k].tie = 0;                 /* bug 12 fix: no tie carried into a song */
        }
        u8 *p = song_data; long limit = ((long *)p)[-4];            /* allocation size in the 0x10-byte header */
        int off = 0;
        if (smus_find_long(p, &off, limit, 'SHDR')) {
            smus_tempo  = *(u16 *)(p + off + 8);                    /* unused */
            smus_volume = (int)(s8)p[off + 10];                     /* unused */
            for (k = 0; k < 4; k++) {
                off += 2;
                if (!smus_find_long(p, &off, limit, 'TRAK')) break;
                track[k].active = -1;
                track[k].size = *(long *)(p + off + 4);
                track[k].data = p + off + 8;
                track[k].pos = 0;
                track[k].count = 0;                                 /* original: tie (+16) is NOT reset */
            }
        }
        song_state = 2;
        return 0;
    }
    if (song_state == 3) { snd_stop_all(); song_state = 0; return 0; }

    /* state 2: one tick */
    song_any_active = 0; song_dma_on = 0; song_dma_off = 0;
    for (k = 0; k < 4; k++) {                                       /* d5 = 3..0, channel k = 3 - d5 */
        T = &track[k];
        if (!T->active) break;                                      /* beq.w past the loop: later tracks are skipped */
        song_any_active = -1;
        if (T->count != 0) {
            T->count--;
            if (T->count == 1 && !T->tie) AUD[k].VOL = 0;           /* cut one tick early */
            continue;
        }
        u8 id, data;
        do {
            if (T->pos >= T->size) {                                /* end of track */
                AUD[k].VOL = 0; song_dma_off |= 1 << k; T->active = 0;
                goto next;
            }
            id = T->data[(int)T->pos]; data = T->data[(int)T->pos + 1];   /* word index */
            T->pos += 2;
        } while (id > 0x80);                                        /* 0x81..0xFF: skipped, take no time */
        T->count = note_ticks[data & 0x0F] - 1;                     /* chord (bit 7), tuplet bits ignored */
        if (id == 0x80) { AUD[k].VOL = 0; T->tie = 0; }             /* rest; DMA keeps running */
        else if (T->oneshot) {
            play_sample(T->inst, k, (int)(song_volume >> 16));      /* ignores the note number; tie untouched */
        } else {
            if (!T->tie) {                                          /* a tied note does not retrigger */
                sample *s = T->inst;
                AUD[k].VOL = 0;
                u16 len = (u16)s->len;                              /* low word of the length long */
                u16 div = g_original_bugs ? len                     /* bug 10: divu.w $2(a0): 17 */
                                          : (u16)((len >> 1) << 1); /* fixed: the 16 bytes Paula plays */
                int per = (int)(u16)(note_period_table[id] / div);  /* divu.w: 32/16, quotient */
                if (per < 0x7C) per = 0x7C;                         /* signed compare */
                AUD[k].PER = per;
                AUD[k].LC = (u8 *)s + 6;
                AUD[k].LEN = len >> 1;
                AUD[k].VOL = (int)(song_volume >> 16);
                song_dma_on |= 1 << k;
            }
            T->tie = (data & 0x40) ? -1 : 0;
        }
    next: ;
    }
    u16 on  = song_dma_on  & ~DMACONR & 0xF; if (on)  DMACON = on | 0x8000;   /* only channels now off */
    u16 off = song_dma_off &  DMACONR & 0xF; if (off) DMACON = off;
    song_state = song_any_active ? 2 : 1;                           /* track 0 finished: restart next tick */
    return 0;
}

int smus_find_long(u8 *base, int *off /*d0*/, long limit /*d1*/, long id /*d2*/) {   /* 0x12CDC */
    do { if (*(long *)(base + *off) == id) return 1; *off += 2; } while (*off < (int)limit);  /* cmp.w, signed */
    return 0;
}
```
Notes on the tick:

* An event read at tick t sets `count = ticks − 1`, so the next event is read at t + ticks. The volume cut at
  `count == 1` leaves `ticks − 2` sounding ticks for untied waveform notes (quarter = 22). The cut also hits
  one-shot tracks (whose tie flag is only changed by rests), which truncates a drum hit on a 6-tick note.
* The waveform retrigger only writes LC/LEN; when DMA is already running, Paula uses them at the next loop
  reload. The period and volume change at once.
* All three tracks of every song have the same length (TestDrive 14784, Test2 2016, TestGas 1920, EndSuccess
  12096, Loser 1152 ticks), so the break-on-inactive rule only matters in the tick where track 0 has ended:
  the next tick sees track 0 inactive, sets state 1, and the song restarts one tick later.
* `note_period_table[id]` for id ≤ 0x7F: all BuzzSynth notes in the songs (14–71) are far above the 0x7C clamp.
  BuzzSynth's length is 17, Paula plays `17 >> 1 = 8` words = 16 bytes per loop, so in the original every
  waveform note is 17/16 sharp (+1.05 semitone): frequency = clock / period / 16 with period = table / 17.
  **Bug 10 (README):** `note_period_table` is `0x369E99 / f(note)` (§3), so the period of one waveform cycle is
  `table / bytes played`; fixed by default, the divisor is the even length that LEN = `len >> 1` plays (16), and
  the notes sound at f(note). `--original-bugs` divides by 17.
* **Bug 12 (README):** the tie flag (+16) survives the parse, so in the original a song (or a loop restart)
  after a tied waveform note skips its first note's retrigger on that track, and a one-shot track keeps the
  flag and loses its early cut. Fixed by default: the parse clears all four tie flags (0x12A54 state 1, which
  runs at every song start and loop restart); `--original-bugs` keeps them.

### 4.12 song_play (0x12CF4), song_stop (0x12DB0), the five songs

```c
void song_play(char *file, char *inst[4], int oneshot[4], u16 mask, int vol) {
    if (song_buffer && strcmp(song_name, file) != 0) song_stop();      /* 0x169B0 */
    if (song_buffer == 0 && music_enabled) {
        snd_stop_all();
        char path[40]; sprintf(path, "songs/%s", file);
        sprintf(song_name, "%s", file);
        song_buffer = load_file(path);                                 /* 0x149D2, any memory */
        song_load_instruments(inst, oneshot);
        sfx_set_song_channels(mask);
        song_set_volume(vol, 0);                                       /* immediate */
        if (song_buffer) song_start(song_buffer);
    } else {
        song_set_volume(vol, 0x8000);                                  /* same song (or music off): fade to vol */
    }
}
void song_stop(void) {
    if (!song_buffer) return;
    song_set_volume(0, 0x5400);                                        /* 0x160000 / 0x5400 = 67 ticks from 0x16 */
    while (song_get_volume() != 0) ;                                   /* busy wait on the VBL server */
    song_request_stop();
    Delay(2);                                                          /* server: state 3 → snd_stop_all */
    song_free_instruments();
    free_mem(song_buffer); song_buffer = 0;
    sfx_set_song_channels(0);
}
void song_play_testdrive(void)  { song_play("TestDrive.Iff.Sng",  testdrive_inst, testdrive_oneshot, 1, 0x20); }
void song_play_test2(void)      { song_play("Test2.Iff.Sng",      song_inst, song_oneshot, 3, 0x16); }
void song_play_testgas(void)    { song_play("TestGas.Iff.Sng",    song_inst, song_oneshot, 3, 0x16); }
void song_play_endsuccess(void) { song_play("EndSuccess.Iff.Sng", song_inst, song_oneshot, 3, 0x16); }
void song_play_loser(void)      { song_play("Loser.Iff.Sng",      song_inst, song_oneshot, 3, 0x16); } /* never called */
```
Track instrument assignment (FORMATS.md "Songs" has the table): TestDrive = BuzzSynth (ch0, waveform), Drum2
(ch1, one-shot), Drum (ch2, one-shot); the others = BuzzSynth (ch0, ch1), Drum (ch2, one-shot). Track 3 is never
present in the files. If `M` has turned music off, song_play only sets the volume target; nothing is loaded.

### 4.13 Drive sounds: load, start, fade (0x26B7A, 0x26C02, 0x26C70, 0x26D16)

```c
void sfx_load_drive(void) {
    sfx_radar = load_file_chip("sfx/Radar");   sfx_engine = load_file_chip("sfx/TheEngine");
    sfx_turbo = load_file_chip("sfx/TheTurbo"); sfx_squeal = load_file_chip("sfx/Squeal");
    sfx_bump  = load_file_chip("sfx/Bump");
}
void sfx_free_drive(void) {        /* frees Bump, Squeal, TheTurbo, TheEngine, Radar; channels keep running */
    free_mem(sfx_bump); sfx_bump = 0; ... free_mem(sfx_radar); sfx_radar = 0;
}
void engine_sound_start(void) {
    sfx_set_song_channels(0);
    if (!sfx_enabled && !g_original_bugs) return;   /* bug 8 fix: S off = no drive loops, as after S mid-drive */
    int h = g_original_bugs ? 0 : 6;           /* bug 9: data = sample header, not +6: each loop plays the */
                                               /* 6 header bytes and drops the last 6 samples; fixed: +6   */
    start_channel((u8 *)sfx_squeal + h, sfx_squeal->len, 1, 0x166, 0, -1);
    start_channel((u8 *)sfx_turbo  + h, sfx_turbo->len,  2, 0x320, 0, -1);
    Delay(2);
    start_channel((u8 *)sfx_engine + h, sfx_engine->len, 3, 0x320, 0, -1);
    Delay(2);
    if (sfx_enabled) {                         /* original: only the fade-in is gated */
        sfx_slide_volume(3, 0x3F, 0x7000);     /* 0x3F0000 / 0x7000 = 144 ticks = 2.4 s */
        skid_volume = 0;
        squeal_env = -1;
    }
}
void engine_sound_fade_out(void) {             /* stage end, crash, quit */
    sfx_slide_volume(1, 0, 0x7000); sfx_slide_volume(2, 0, 0x7000); sfx_slide_volume(3, 0, 0x7000);
}
```

### 4.14 engine_sound_update (0x26D4E), squeal_update (0x26E26), bump_update (0x26EE2), radar_beep (0x26C50)

Called once per drive frame from 0x20826 (end of the engine/gearbox update, which 0x20CB0 runs when D:0D74 == 0).

```c
void engine_sound_update(void) {
    squeal_update();
    bump_update();
    int r = rpm; if (r < 0x320) r = 0x320;                      /* signed; 800 rpm floor */
    int per = (int)(u16)(0x249988UL / (u16)r);                  /* divu.w, quotient word; 2398600 */
    if (per < 0x82)  per = 0x82;
    if (per > 0x708) per = 0x708;                               /* reached below 1333 rpm */
    engine_period = per;
    sfx_set_period_vol(3, per, -1);

    int vol = 0;
    if (pedal < 0) goto out;                                    /* braking: turbo layer silent */
    if (pedal > 0) {
        if (gear == 0) goto out;
        int r2 = rpm;
        if (car_sound_flag == 0) r2 += 0x5DC;                   /* +1500 for the non-turbo cars */
        if (r2 <= 0x7D0) goto out;                              /* 2000 */
        if (r2 > 0xFA0) r2 = 0xFA0;                             /* 4000 */
        vol = (int)(((u32)(u16)(r2 - 0x7D0) * 0x831) >> 16);    /* mulu, swap: 0..63 */
    }
    {   int w = (int)(speed >> 16) - 0x5A;                      /* mph above 90 */
        if (w <= 0) goto out;
        if (w >= 0x20) w = 0x20;
        vol += w; if (vol > 0x40) vol = 0x40;
    }
out:
    sfx_slide_volume(2, vol, 0x10000);                          /* 1 volume step per VBL */
    int per2 = engine_period;
    if (car_sound_flag == 0) per2 <<= 1;                        /* one octave down for non-turbo cars */
    sfx_set_period_vol(2, per2, -1);
}

void squeal_update(void) {
    if (squeal_mute) { skid_volume = 0; squeal_env = -1; goto steady; }
    if (squeal_env < 0) goto steady;
    if (++squeal_env >= 0x19) { squeal_env = -1; goto steady; }
    sfx_set_period_vol(1, squeal_env_period[squeal_env], squeal_env_volume[squeal_env]);
    return;
steady:
    sfx_set_period_vol(1, 0x166, skid_volume);                  /* 0x166 ≈ native 10 kHz */
}
/* index:            1     2     3     4     5     6     7     8     9    10    11    12
   period 0x26EB0: 015C 015C 0172 017C 0182 0188 018B 0186 0186 0181 0181 0180
   index:           13    14    15    16    17    18    19    20    21    22    23    24
                   017F 017E 017D 017A 0177 0172 0168 015E 0154 014F 014F 014F     (entry 0 = 015C unused)
   volume 0x26E7E: entries 0..17 = 0x40, then 0x3C 0x32 0x2D 0x20 0x14 0x0A 0x00 (18..24) */

void bump_update(void) {
    if ((bump_marker || bump_edge) && !sfx_channel_busy(0) && sfx_enabled)
        play_sample(sfx_bump, 0, 0x40);
    bump_marker = 0; bump_edge = 0;                            /* requests are dropped if channel 0 is busy */
}
void radar_beep(void) { if (sfx_enabled) play_sample(sfx_radar, 0, 0x40); }
```

Triggers (details belong to drive_sim / drive_scene):

* **squeal_env = 0** (0x207A4): after a gear change from neutral into 1st with `pedal ≥ 0` and `rpm > 4000`
  (rpm is halved: clutch dump). The chirp runs entries 1–24 (24 drive frames).
* **squeal_env = 0x0B** (0x207A4): after 1st → 2nd when the new rpm is more than 0x640 (1600) below the old.
  Entries 12–24 (13 frames).
* **skid_volume** (0x24A04): steering/slip excess over the car's grip (+008), clamped 0..0x40, every frame.
* **bump_edge** (0x24A04): D:0D80 ≠ 0 and D:0D80 & 3 ∈ {0, 2}, i.e. hazard objects 0x20 / 0x22 (D:0D80 =
  hazard object byte hit this frame, set by 0x1DC2E; drive_sim `hazard_hit`); **bump_marker**
  (0x1E6A6/0x1E73A): road-edge markers at speed ≥ 0x18.
* **radar_beep** (0x1EC94): each time the radar-detector lamp relights after its 8-tick off phase while the
  detector is active (D:0DBE ≠ 0).

### 4.15 Menu triggers (overlay 1, root)

* **Title 0x1AED0** (TestDrive song already playing from main): after `Pics/Title2` is shown, if sfx on,
  `song_set_volume(7, 0x7000)` (duck), then `play_sample(Accolade, 3, 0x40)` if sfx on and busy-waits
  `while (sfx_channel_busy(3))`; then `song_set_volume(0x20, 0x9000)` and `Pics/Title4`. When 200 ticks have passed
  since Accolade started: `song_set_volume(7, 0x3500)` if sfx on, 0x50 ticks later `play_sample(Starter, 3, 0x40)` if sfx on, the
  title car animation (0x1B396), then `song_set_volume(0x20, 0x9000)` and `Pics/Title3`. On abort (key/fire),
  `song_set_volume(0, 0x7000)`; on normal completion the song keeps playing at 0x20.
* **Showroom 0x1C244**: `play_sample(Starter, 3, 0x40)` if sfx on when the animation starts; at the end
  `0x1C22A(10)` (waits 10 frames) then `sfx_stop_channel(3)` and the sample is freed.
* **main 0x10018**: `song_play_testdrive` before the title and before the high-score screen 0x12F28 (the
  second call only fades in if the song is still loaded), `song_stop` after the high scores and before a drive,
  `song_play_test2` before car select 0x1B8E6. Gas station 0x147E4 → TestGas, which keeps playing through the
  next stage's loading until 0x1C900 calls `song_stop`. Ending (stage counter D:24CC > 3) → EndSuccess, playing
  until main's next `song_play_testdrive` fades it out.

### 4.16 Hotkeys (inside 0x10462)

```c
case 'M': music_enabled = !music_enabled; if (!music_enabled) song_stop(); break;
case 'S': sfx_enabled   = !sfx_enabled;   if (!sfx_enabled)   snd_stop_all(); break;
case 'P': /* pause (only while driving): loops Delay(1) until a key; no audio calls */
```

### 4.17 Sound-off behaviour (verified)

* **Bug 8 (README):** in the original, engine_sound_start starts the three loops even when sfx are off (only
  the engine fade-in is gated, 0x26CF0), and engine_sound_update / squeal_update are not gated: with `S` off at
  stage start, the engine (ch 3) stays at volume 0 but the squeal (ch 1) and the TheTurbo layer (ch 2) are
  audible. Fixed by default: with `S` off, engine_sound_start starts no loop (§4.13), which is the state the
  game itself reaches when `S` is pressed mid-drive (`snd_stop_all`, nothing restarted); the per-frame updates
  then only write registers of stopped channels. `--original-bugs` keeps the leak.
* **Bug 9 (README):** the three drive loops start at the sample header instead of +6 (0x26C8A–0x26CDE pass
  `sfx_x`, not `sfx_x + 6`, with the full length), so each loop pass plays the 6 header bytes (length and rate,
  a click) and drops the last 6 samples. Fixed by default: start at +6 with the same length, as `play_sample`
  does; `--original-bugs` keeps the header in the loop.
* Turning `S` off mid-drive stops all channels; turning it back on restarts nothing until the next
  engine_sound_start (next stage or after a crash).
* `S` off during a song also stops the song's channels; the waveform channels come back at the next untied
  note (song_dma_on), one-shot tracks at their next hit.
* During the pause (`P`) the VBL servers keep running, so the engine loops keep sounding.

## 5. Hardware/OS dependencies and the SDL3 replacement

| Original | Where | SDL3 port |
|---|---|---|
| Paula AUDx LC/LEN/PER/VOL, DMACON bits 0–3 | 0x124C4 … 0x12A54 | A 4-channel Paula emulation (below); writes go to the emulated registers |
| Audio interrupts (INTENA/INTREQ bits 7–10, level-4 autovector `$70`) | 0x12304, 0x12616 | Callback `sfx_audio_int(ch)` from the mixer when a channel (re)loads, only if `sfx_int_channels & (0x80<<ch)` |
| ADKCON = 0xFF (no modulation) | 0x12304, 0x12A54 | Nothing to emulate (no modulation used) |
| exec AddIntServer/RemIntServer (VERTB, pri 0x20 song, 0x1E sfx) | 0x1278C, 0x12304 | Call `song_vbl_server()` then `sfx_vbl_server()` once per 60 Hz tick, before the Ticks counter (pri −0x50) |
| dos Delay(n) | 0x175EA | Advance n/50 s of host time (not VBL-based), running the 60 Hz ticks (servers and mixer) that fall into it |
| Chip-memory sample buffers (`load_file_chip`) | 0x149E8 | Any memory; the mixer reads the sample bytes through the port's `mem[]` pointers |
| CIA-A `$BFE001` bit 1 (LED/filter) | never written | Filter stays as the OS left it: **on** (power LED bright). Offer the A500 filters as an option (below) |
| `$BFF002`/`$BFF096` (0x1042E/0x1044C) | root | Not audio and not a CIA register (A12 and A13 both high select neither CIA): an attempt at DMACON BLTPRI that writes nowhere. Ignore; see platform_video |

**Paula model for the port.** Per channel: registers `lc, len, per, vol` and internal `ptr, remaining, pos`
(fractional), `dma` flag.

* DMA off → on (DMACON set): `ptr = lc; remaining = len` (len 0 = 65536 words), raise the channel's audio
  interrupt, start output.
* Each output byte lasts `per` Paula clocks. After `2·len` bytes the channel reloads `ptr = lc; remaining = len`
  from the *current* registers and raises the interrupt again (this is how a new LC/LEN written during playback
  takes effect, and how the sfx engine counts repeats; the interrupt may stop the channel before any byte of
  the new pass is heard).
* PER and VOL writes take effect immediately. VOL 0..64 (values > 64 act as 64). Periods used: ≥ 0x7C.
* DMA on → off: output stops (hold 0; VOL is always 0 when the game stops a channel).
* Output = s8 × vol, zero-order hold (no interpolation) — resample by stepping `clock / per` source bytes per
  second into the host rate. Stereo: channels 0 and 3 left, 1 and 2 right (engine left; squeal, turbo right;
  radar/bump left; song waveform on the left for TestDrive, both sides for the others). Mix: each side
  `Σ s8·vol` fits ±16384; scale to S16 by ×2 (or less for headroom).
* Paula clock: the NTSC clock **3579545 Hz**, the game's own constant 0x369E99, together with the 60 Hz tick
  (port/amiga/README.md, *Decisions* 1). (A PAL machine, 3546895 Hz, played everything 0.9 % = 16 cents flat.)
* Host side: SDL_AudioStream S16 stereo, 44100 or 48000 Hz. Follow the DOS port's host.c pattern: on each 60 Hz
  tick run `song_vbl_server`, `sfx_vbl_server`, the tick counter, then render exactly 1/60 s of Paula output (735
  samples at 44100, 800 at 48000, with a fractional accumulator) and queue it. The audio interrupt is raised inside
  that render at the exact sample where the reload happens. Game-code calls (start_channel, set_period_vol, …) run
  between ticks in the same thread, so no locking is needed.
* Optional filters: A500 fixed RC low-pass (≈ 4.4 kHz, 6 dB/oct) and the LED Butterworth (≈ 3.3 kHz, 12 dB/oct),
  on by default because the game never turns it off.

**Rates heard** (clock 3579545, as coded and as the port plays them):

| Sound | Channel | Period | Rate (Hz) | Length |
|---|---|---|---|---|
| Accolade | 3 | 357 | 10027 | 13122 B, 1.31 s, once |
| Starter | 3 | 715 | 5006 | 50000 B, 9.99 s, once |
| Radar | 0 | 178 | 20110 | 3354 B, 0.17 s, once |
| Bump | 0 | 380 | 9420 | 340 B, 36 ms, once |
| Squeal (loop; incl. header only with `--original-bugs`) | 1 | 0x166 = 358 (envelope 0x14F–0x18B) | 9999 (9062–10685) | 904 B |
| TheTurbo (loop) | 2 | engine period (×2 if car +006 = 0) | | 9261 B |
| TheEngine (loop) | 3 | `0x249988 / max(rpm,800)` in 0x82..0x708 | `clock·rpm/2398600` ≈ 1.492·rpm for 1333 ≤ rpm; 1988.6 below | 10825 B |
| Drum (song) | 2 | 250 | 14318 | 1704 B |
| Drum2 (song) | 1 | 357 | 10027 | 566 B |
| BuzzSynth (song) | 0/1 | `note_period_table[n] / 16` (`/ 17` with `--original-bugs`) | 16 × f(n) (16 × (17/16) f(n) original) | 16 B played |

## 6. Timing

* **60 Hz VBL** (NTSC, port/amiga/README.md *Decisions* 1) drives everything: the song server (pri 0x20) then
  the sfx server (pri 0x1E) each VBL; the game tick counter D:03D8 (Ticks VBLInt, pri −0x50) is separate from
  `sfx_tick` D:04C2.
* **Song tempo is fixed**: quarter = 24 ticks = 0.4 s (150 bpm); the SHDR tempo is ignored. Loop lengths: Summed
  note durations: TestDrive 14784 ticks (4:06), Test2 2016 (33.6 s), TestGas 1920 (32 s), EndSuccess 12096 (3:22),
  Loser 1152 (19.2 s). One loop lasts that sum + 3 ticks: the tick that finds the end, the tick that sees track 0
  inactive (state 1), and the parse tick; the first notes come on the tick after the parse (also after song_setup).
* **Sfx start latency**: next VBL; ≥ 2 ticks after the channel's last stop (a retrigger gap of one VBL).
* **Volume slides** step once per VBL: engine fade-in 144 ticks (2.4 s), fade-out 0x7000/tick, turbo 1 unit/tick,
  song stop 0x5400/tick (67 ticks from 0x16, 98 from 0x20), song fade-in 0x8000/tick.
* **Drive-frame rate**: engine_sound_update, squeal_update (envelope steps), bump_update and the radar run once
  per drive frame, which is at least 5 VBL ticks (0x1C900 waits until `start + 5`): engine pitch updates at most
  12 times a second, the shift chirp lasts ≥ 2 s (24 frames) or ≥ 1.08 s (13 frames).
* **Busy waits**: song_stop spins on the VBL-driven volume; the title spins on `sfx_channel_busy(3)` until
  Accolade ends. In the port these loops must keep the 60 Hz tick running (call the host tick inside them).

## 7. Differences from DOS

DOS reference: port/spec/platform.md §4.6 (timer, speaker driver, songs), simulation.md (grind/squeal/radar
divisors), game_flow.md (song calls). No function is shared logic; the table below lists behaviour.

| Topic | DOS (TDEGA) | Amiga (td) |
|---|---|---|
| Hardware | PC speaker, one square-wave voice (PIT ch 2) | Paula, 4 sampled 8-bit channels, stereo (0,3 L / 1,2 R) |
| Tick | 100.04 Hz PIT ISR 0x6A1F runs the song interpreter | 60 Hz VBL servers (song, sfx) + level-4 audio interrupt |
| Music data | TDSND.SND bytecode (notes/loops, articulation shift) | IFF SMUS files + instrument samples; tempo fixed, chords serialised, instruments fixed per caller, waveforms 17/16 sharp in the original (bug 10) |
| Songs per screen | intro sng2, car select sng4, high-score entry sng3, gas sng1; played once (one-shot streams) and stopped explicitly | title + high scores `TestDrive`, car select `Test2`, gas `TestGas`, ending `EndSuccess` (no DOS counterpart), `Loser` unused; songs loop until stopped, switching fades out (0x5400/tick) |
| Music across screens | stopped at each screen exit | TestDrive continues from title to high scores; TestGas continues through the next stage's loading; EndSuccess through the ending |
| Sound toggles | Ctrl-Q off / Ctrl-S on, one flag DS:643E bit 2, stops at next fetch | `S` toggles effects (D:0344, stops all channels at once), `M` toggles music (D:04CC, fades and unloads) |
| Engine | square wave `f = rpm_disp / 32` Hz, rpm slewed 0x40 per 100 Hz tick, pitch quantised to the 6-tick loop `55×4, 56×2` | TheEngine sample loop on ch 3, period `0x249988/max(rpm,800)` clamped 0x82..0x708, no slew, updated per drive frame (≥ 5 VBLs); fades in over 2.4 s at stage start |
| Second engine layer | none | TheTurbo loop on ch 2: volume from pedal, gear, rpm 2000..4000 (+1500 for cars with +006 = 0) and speed above 90 mph; period = engine period, ×2 when +006 = 0 |
| Tyre squeal | slot 0x56 = 0x08E8 (523 Hz) on/off while lateral load ≥ grip, alternating with the engine | Squeal sample loop on ch 1, volume = skid excess 0..0x40 |
| Gear clash / clutch dump | slot 0x56 = 0x0474 (1047 Hz) for `grind_timer` = 3 (rpm drop > 2500) or 0x12 (1st gear, rpm rise > 3500) sim ticks | squeal chirp envelope (period/volume tables 0x26EB0/0x26E7E): neutral→1st above 4000 rpm (24 frames), 1st→2nd with rpm drop > 1600 (13 frames) |
| Radar | 2-tick 1325.8 Hz beep song 0xB0F, retriggered every frame while the alert condition holds | Radar sample (ch 0) once per detector-lamp blink cycle |
| Bumps | none | Bump sample (ch 0) on road-edge markers / roadside contacts, dropped if ch 0 is busy |
| Crash / stage end | `snd_stop_all`, then `snd_set_loop(0xB05)` again after a crash | engine_sound_fade_out (0x7000/tick), then engine_sound_start again (2 × `Delay(2)` gaps, 2.4 s fade-in) |
| Pause | modal_pause silences the speaker | engine loops keep sounding |
| Intro effects | none | `Sfx/Accolade` with the music ducked to 7, `Sfx/Starter` at the title and at the showroom drive-away |
| Sound-off leak | none | original only: squeal and turbo audible with `S` off at stage start (§4.17, bug 8) |

## 8. Open questions

1. **PAL vs NTSC clock.** *Resolved*: NTSC, 3579545 Hz with the 60 Hz VBL (port/amiga/README.md, *Decisions* 1).
2. **First audio interrupt timing.** The model raises the interrupt at DMA start and at each reload, as Paula
   does; exact sub-sample timing is irrelevant for these samples, but one-pass sounds must not be cut before
   their last byte.
3. **Trigger meanings** owned by other specs: D:0D72/D:0D76 (squeal mute), D:0D80 values from 0x1DC2E and the
   road-edge geometry in 0x1E6A6 (bump), D:0DBE/D:0DC4 (radar), D:26FC/D:1600/D:1602 (gear-change event in
   0x207A4), and the exact pedal semantics of D:1922 — to be confirmed by drive_sim / drive_scene.
   *Resolved by drive_sim (merge):* D:0D72 = autopilot / pull-over lane hold; D:0D76 = frames the police car has
   tailed the player; D:0D80 = hazard object byte hit this frame (consumed by 0x24A04); D:0D9A = marker/shoulder
   bump flag (0x1E6A6); D:0DBE = radar zone counter (high word 1..7), D:0DC4 = constant 0x32 (lamp on time);
   D:26FC = shift in progress, D:1600/D:1602 = previous gear / previous shift state; D:1922 = +1 gas, −1 brake,
   0 none, written after the physics and read by the next frame's engine update; D:28A6 = speed, signed 16.16,
   clamped ≥ 0.
4. **Drive frame length.** The audio update rate follows the drive loop (≥ 5 VBLs); if frames take longer on a
   stock A500, the chirp envelope and pitch steps slow down with them. The port should reproduce the 5-tick frame.
5. **sfx_free_drive** frees the engine samples while the loops may still be fading (the next song_play stops
   them). The port must stop or detach the channels before freeing; behaviour on real hardware was reading
   freed chip RAM for a short time.
6. **Tie flag carry-over** (README bug 12, *resolved*): track +16 is not reset by the SMUS parse. A song that
   ends with a tied note on a waveform track could leave the next song's first note on that track untriggered
   (no retrigger, only the tie update) or leave a one-shot track without its early cut. Not observed with the
   shipped songs' order; the port clears the flags at the parse by default and keeps them with
   `--original-bugs` (§4.11).
7. **Filter**: whether to enable the A500 low-pass/LED filter by default in the port is a presentation choice;
   the game itself never changes it.
