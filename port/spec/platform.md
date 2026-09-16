# Platform layer (TDEGA.EXE image 0x4941–0xC99F)

Conventions: port/RE_GUIDE.md. `DS:xxxx` = image 0xC9A0+xxxx. `CS:xxxx` = a variable stored in the code
segment at image offset xxxx (the hand-written assembly keeps its graphics state there). "far ptr" =
16:16 off,seg pair. Formats already decoded in FORMATS.md are cited, not repeated. Tables dumped to
`port/spec/tables/`: `blit_tables.json`, `font8x8.json`, `ega_palettes.json`, `note_divisors.json`,
`engine_divisors.json`, `sound_effects.json`, `input_tables.json`, `crt_functions.json`.

**Corrections to FORMATS.md / RE_GUIDE.md found here**

* Sprite planemap high nibbles are **not** "bits set on every pixel": `pm[0] >> 4` = colour planes
  **cleared** over the sprite rectangle (REPLACE/AND blits), `pm[1] >> 4` = planes **set** (REPLACE/OR) or
  inverted (XOR), `pm[3] >> 4` = per-plane padding bytes. `f0 00 00 00` (`blnk`) is a black box, not
  colour 15; `87 00 00 00` gives colours 0/7; `07 80 00 00` gives 8/15.
* 0x8A3E is `snd_play_oneshot`, not the sound tick; the song interpreter runs inside the timer ISR 0x6A1F.
  The "int 8 hook ~0x4910/0x1F3E" is the *driving-mode* hook (0x4908 installs, 0x1F29 removes); the base
  100 Hz hook is 0x69CF.
* Note slots 0x55–0x57 of the divisor table DS:6452 are patched at run time (engine, skid/grind, radar beep).
* Copy protection result is only a return value (0 pass / 0xFEF6 fail), consumed in 3 places.
* Mode 0Dh palette actually used in game is DS:00CC (set by main right after 0x4D96 loads DS:637C).
* TDEGA has no page flipping and no retrace waits.

## 1. Overview

The range holds five independent layers, mostly hand-written assembly plus the Microsoft C 4.x runtime.

1. **Planar graphics.** A tiny "target" abstraction (current target copied into CS:5A64) that is either
   the EGA screen (A000h, driven through the sequencer map mask / GC function / write mode / bit mask /
   read map registers) or an off-screen RAM buffer with up to 4 bit planes, allocated by 0x5150 and laid
   out exactly like a sprite resource. On top of it: 24 sprite blitter entry points (REPLACE/OR/AND/XOR ×
   clipped/unclipped × hotspot/raw/own position), rectangle fill, clear, line, 8×8 text, dissolve fade,
   window scroll, screen grab. All game screens are composed in RAM buffers and copied to A000h with a
   blit or the dissolve; nothing waits for vertical retrace.
2. **Input.** BIOS keyboard polling through INT 16h (no INT 9 hook) — the last buffered keystroke wins —
   and a port-201h joystick reader with self-adjusting calibration. Two front ends: `input_poll_drive`
   (direction 0–8 + fire, used in driving and "press fire" waits) and `getkey` (menu codes).
3. **Timer and sound.** PIT channel 0 reprogrammed to divisor 0x2E97 (100.04 Hz) for the whole run. The
   ISR counts ticks, chains the BIOS every 5 ticks in menus, and steps a bytecode song player that drives
   PIT channel 2 + port 61h. During driving a second ISR (0x3B1F, simulation range) is chained in front:
   engine pitch follows rpm and the physics runs every 8th tick. INT 0 is hooked in driving so divide
   overflows yield 0xFFFF.
4. **Resources and memory.** One large DOS block: archive cache growing up (30 slots), buffers growing
   down (8 slots). `.PES` archives are decompressed (FORMATS.md) and their offset tables relocated into
   far pointers; `res_find` looks resources up by 4-char name. Fatal errors restore text mode, unhook the
   timer, print and abort.
5. **Copy protection** (0x8DC7, drop it) and the **C runtime** (0xA4E3–0xC99F).

```
main 0x0010 (game_flow)
 ├─ mem_init 0x8CC0
 ├─ gfx_init_ega 0x4D96 ─ gfx_clear_screen 0x4B98 ; INT10 0Dh ; gfx_set_palette 0x4D84(DS:00CC)
 ├─ input_set_mode 0x8AFD(4) ; timer_install_menu 0x699E ─ timer_install_common 0x69CF
 ├─ load_raw_archive 0x78A5("tdsnd.snd") ; res_find 0x6762(sng1..4)
 ├─ gfx_create_buffer 0x5150(40,200,0xF) → DS:7F1A
 ├─ copy_protection_check 0x8DC7          (port: return 0)
 └─ exit: gfx_shutdown 0x50FE | herc_shutdown 0x8D3C ; timer_restore 0x694A

screens (game_flow):  gfx_select_target(buffer) → gfx_clear_clip 0x74F4 → blit_copy_own 0x6D1C …
                      → gfx_select_target(screen 0x5A7C) → gfx_dissolve 0x768B ×8 (set_deadline 0x7894)
driving (scene_render/simulation):
  select buffer DS:0890 → blits (0x5DE2/0x4DF1/0x8308/0x8058/0x7C63/0x7A5F…) → select screen
  → blit_copy_clip_own 0x5DE2(buffer) ; gauges gfx_draw_line 0x85D5 ; grab_into_sprite 0x8C00

INT 8  → [drive_isr 0x3B1F →] timer_isr 0x6A1F ─ snd_fetch 0x6AA8 ─ PIT ch2 / port 61h
         drive_isr every 8th tick → input_poll_drive 0x5C24 ─ joy_read 0xA12F ; physics 0x3FE8…
menus  → getkey 0x67E8 ─ getkey_kbd_joy_edge 0x68F4 ─ getkey_kbd_ctrl 0x6846 / joy_read 0xA12F
load   → load_archive 0x8A5B ─ cache_find 0xA280 ─ load_packed_archive 0x9A86
         ─ cache_alloc 0xA2BE ─ lzw 0x9E1D / huff 0x9C90 ─ rle90_out 0x9CF9 ─ pack_putc 0x9DD3
fatal 0x94AB ─ gfx_shutdown 0x50FE ─ timer_restore 0x694A ─ printf ─ abort
```

## 2. Function table

### 2.1 Graphics

| image addr | proposed name | signature | one-line purpose | confidence |
|---|---|---|---|---|
| 0x4941 | gfx_fill_rect | `void (s16 x, s16 y, s16 w, s16 h, u8 colour)` | Pixel rectangle fill, no clipping; RAM per-plane set/clear or EGA write mode 2 | verified |
| 0x4B98 | gfx_clear_screen | `void (u8 colour)` | Fills A000h (8000 bytes, all planes) regardless of target | verified |
| 0x4BD0 | gfx_draw_text | `void (char *s, s16 x, s16 y)` | Sets text cursor DS:6914/6916, falls into 0x4BE7 | verified |
| 0x4BE7 | gfx_draw_text_at_cursor | `void (char *s)` | Opaque 8×8 font text, fg DS:690E / bg DS:6910 | verified |
| 0x4D78 | gfx_set_border | `void (u8 colour)` | INT 10h AH=0Bh; unreferenced | verified |
| 0x4D84 | gfx_set_palette | `void (u16 ds_table)` | INT 10h AX=1002h, ES:DX = DS:table (17 bytes) | verified |
| 0x4D96 | gfx_init_ega | `void (void)` | Reset GC, clear, equipment = colour, mode 0Dh, palette DS:637C | verified |
| 0x4DF1 | blit_or_clip_hot | `void (u16 off, u16 seg, s16 x, s16 y)` | Clipped OR blit at x−hot_x, y−hot_y | verified |
| 0x4E05 | blit_or_clip_raw | `void (u16 off, u16 seg, s16 x, s16 y)` | Clipped OR blit at x, y | verified |
| 0x4E19 | blit_or_clip_own | `void (u16 off, u16 seg)` | Clipped OR blit at header x&~3, y | verified |
| 0x4E2D | (data) | `u16[8]` + code to 0x50A0 | OR/clipped RAM shift routines | verified |
| 0x50A1 | gfx_set_clip | `void (u16 doff, u16 dseg, s16 x0, s16 x1, s16 y0, s16 y1)` | Clip in byte columns / rows (x1, y1 exclusive); also updates the live copy | verified |
| 0x50FE | gfx_shutdown | `void (void)` | Clear screen, equipment = colour, INT 10h mode 3, AH=0Bh BX=20h | verified |
| 0x5128 | gfx_select_target | `void (u16 doff, u16 dseg)` | Copies 12-word descriptor to CS:5A64, pointer to CS:5A60 | verified |
| 0x5150 | gfx_create_buffer | `far desc (u16 w_bytes, u16 h, u16 plane_mask)` | Off-screen planar buffer (= sprite); descriptor in CS:5290..5A5F | verified |
| 0x5290 | (data) | 2000 bytes | Descriptor/row-table pool, bump pointer CS:528E | verified |
| 0x5A60 | (data) | 0x1C4 bytes | Current-target pointer + copy, screen descriptor CS:5A7C, screen row table CS:5A94 | verified |
| 0x5D84 | blit_copy_clip_hot | `void (u16 off, u16 seg, s16 x, s16 y)` | Clipped REPLACE blit at hotspot | verified |
| 0x5DB6 | blit_copy_clip_raw | `void (u16 off, u16 seg, s16 x, s16 y)` | Clipped REPLACE blit at x, y | verified |
| 0x5DE2 | blit_copy_clip_own | `void (u16 off, u16 seg)` | Clipped REPLACE at own x&~3, y; body of all clipped blits (0x5E0E) | verified |
| 0x6124 | (data+code) | tables CS:6124 (RAM REPLACE), CS:6134 (EGA all ops) | Clipped shift routines 0x6144–0x6762 | verified |
| 0x6CBE | blit_copy_hot | `void (u16 off, u16 seg, s16 x, s16 y)` | Unclipped REPLACE at hotspot | verified |
| 0x6CF0 | blit_copy_raw | `void (u16 off, u16 seg, s16 x, s16 y)` | Unclipped REPLACE at x, y | verified |
| 0x6D1C | blit_copy_own | `void (u16 off, u16 seg)` | Unclipped REPLACE at own x&~3, y; body of all unclipped blits (0x6D48) | verified |
| 0x6FD8 | (data+code) | tables CS:6FD8 (RAM REPLACE), CS:6FE8 (EGA all ops) | Unclipped shift routines 0x6FF8–0x74E2 | verified |
| 0x74E3 | gfx_set_text_cursor | `void (s16 x, s16 y)` | DS:6914/6916 | verified |
| 0x74F4 | gfx_clear_clip | `void (u8 colour)` | Fills the current clip rectangle (EGA path quirks) | verified |
| 0x768B | gfx_dissolve | `void (u16 off, u16 seg, u8 phase)` | Screen-only dissolve: 12 interlaced row passes, one pixel per byte | verified |
| 0x79FF | gfx_free_buffer | `void (u16 doff, u16 dseg)` | Pops descriptor pool (LIFO) and frees buffer memory (0xA37E) | verified |
| 0x7A37 | blit_or_hot | `void (u16 off, u16 seg, s16 x, s16 y)` | Unclipped OR at hotspot (table CS:7A73) | verified |
| 0x7A4B | blit_or_raw | `void (u16 off, u16 seg, s16 x, s16 y)` | Unclipped OR at x, y | verified |
| 0x7A5F | blit_or_own | `void (u16 off, u16 seg)` | Unclipped OR at own x, y | verified |
| 0x7C3B | blit_and_hot | `void (u16 off, u16 seg, s16 x, s16 y)` | Unclipped AND at hotspot (table CS:7C77) | verified |
| 0x7C4F | blit_and_raw | `void (u16 off, u16 seg, s16 x, s16 y)` | Unclipped AND at x, y | verified |
| 0x7C63 | blit_and_own | `void (u16 off, u16 seg)` | Unclipped AND at own x, y | verified |
| 0x7E54 | blit_xor_hot | `void (u16 off, u16 seg, s16 x, s16 y)` | Unclipped XOR at hotspot (table CS:7E90) | verified |
| 0x7E68 | blit_xor_raw | `void (u16 off, u16 seg, s16 x, s16 y)` | Unclipped XOR at x, y | verified |
| 0x7E7C | blit_xor_own | `void (u16 off, u16 seg)` | Unclipped XOR at own x, y | verified |
| 0x8058 | blit_xor_clip_hot | `void (u16 off, u16 seg, s16 x, s16 y)` | Clipped XOR at hotspot (table CS:8094) | verified |
| 0x806C | blit_xor_clip_raw | `void (u16 off, u16 seg, s16 x, s16 y)` | Clipped XOR at x, y | verified |
| 0x8080 | blit_xor_clip_own | `void (u16 off, u16 seg)` | Clipped XOR at own x, y | verified |
| 0x8308 | blit_and_clip_hot | `void (u16 off, u16 seg, s16 x, s16 y)` | Clipped AND at hotspot (table CS:8344) | verified |
| 0x831C | blit_and_clip_raw | `void (u16 off, u16 seg, s16 x, s16 y)` | Clipped AND at x, y | verified |
| 0x8330 | blit_and_clip_own | `void (u16 off, u16 seg)` | Clipped AND at own x, y | verified |
| 0x85D5 | gfx_draw_line | `void (s16 x0, s16 y0, s16 x1, s16 y1, u8 colour)` | Clipped line: H/V via fill_rect, else 16.16 DDA | verified |
| 0x8B08 | gfx_grab_screen | `void (s16 sx, s16 sy, s16 dx, s16 dy, s16 w_bytes, s16 h)` | Copies a screen rectangle into the current RAM target | verified |
| 0x8BDC | grab_into_sprite_hot | `void (u16 off, u16 seg, s16 x, s16 y)` | Screen → sprite planes at x−hot_x, y−hot_y; unreferenced | verified |
| 0x8C00 | grab_into_sprite_raw | `void (u16 off, u16 seg, s16 x, s16 y)` | Screen → sprite planes at x, y (background save, caller 0x35C6) | verified |
| 0x8C1E | grab_into_sprite_own | `void (u16 off, u16 seg)` | Screen → sprite planes at own x&~7, y; body 0x8C3C; unreferenced | verified |
| 0x8CEC | herc_init | `void (void)` | Hercules graphics mode (argv[1] == "herc") | verified |
| 0x8D3C | herc_shutdown | `void (void)` | Hercules back to text mode 7 | verified |
| 0x91CF | gfx_scroll_window | `void (s16 x, s16 y, s16 w, s16 h, s16 row_step, u16 soff, u16 sseg, s16 srow)` | EGA write-mode-1 one-row scroll + one sprite row (credits) | verified |
| 0x97D4 | rect_clear_plane | asm: ES:DI dst, DX width, SI rows, CX skip, BX shift | RAM: clear sprite-rectangle pixels of one plane | verified |
| 0x981E | rect_set_plane | same | RAM: set sprite-rectangle pixels | verified |
| 0x9868 | rect_xor_plane | same | RAM: invert sprite-rectangle pixels | verified |
| 0x98C2 | rect_clear_plane_ega | same | EGA read-modify-write variant | verified |
| 0x992B | rect_set_plane_ega | same | EGA variant | verified |
| 0x9994 | rect_xor_plane_ega | same | EGA variant (wrong at partial bytes with GC function XOR) | verified |
| 0x9A69 | draw_glyph | `void (int x, int y, int idx)` | Blits built-in glyph sprite CS:[0x9A19+idx*2] (text cursor) | verified |
| 0xA3B7 | gfx_target_save | `void (void)` | Copies 24 words CS:5A64..5A93 (current + screen descriptor) to DS:6AC4 | verified |
| 0xA3CB | gfx_target_restore | `void (void)` | Copies them back | verified |
| 0xA4D9 | gfx_get_target_ptr | `u32 (void)` | Returns CS:5A60/5A62 (debug dump only) | verified |

### 2.2 Input, timer, sound

| image addr | proposed name | signature | one-line purpose | confidence |
|---|---|---|---|---|
| 0x5C24 | input_poll_drive | `u16 (void)` | Last buffered key → direction/fire/hotkey, else joystick; ESC = 0xFFFF | verified |
| 0x67DD | getkey_wait | `u16 (void)` | Loops `getkey` until nonzero | verified |
| 0x67E8 | getkey | `u16 (void)` | Dispatch through CS:67F2[DS:6422] (modes 0/2/4) | verified |
| 0x67F8 | getkey_kbd | mode 0 | Non-blocking INT 16h: ASCII or scan<<8 | verified |
| 0x680E | getkey_kbd_joy_level | mode 2 | Keyboard or level-triggered joystick menu codes; unused | verified |
| 0x6846 | getkey_kbd_ctrl | internal | Drains INT 16h buffer, keeps last key, handles Ctrl hotkeys | verified |
| 0x68F4 | getkey_kbd_joy_edge | mode 4 (used) | Keyboard or edge-triggered joystick menu codes | verified |
| 0x6939 | kbd_flush | `u16 (void)` | Empties the BIOS keyboard buffer | verified |
| 0x694A | timer_restore | `void (void)` | Restores INT 8, PIT ch0 divisor 0, speaker off | verified |
| 0x698C | timer_install_drive | `void (void)` | 100.04 Hz, no BIOS chaining | verified |
| 0x699E | timer_install_menu | `void (void)` | 100.04 Hz, BIOS INT 8 every 5 ticks | verified |
| 0x69B6 | timer_install_div | `void (int unused, u16 divisor)` | Generic install; dead | verified |
| 0x69CF | timer_install_common | DX = divisor | Speaker off, 43h=B6h, hook INT 8 → 0x6A1F, load ch0 divisor | verified |
| 0x6A1F | timer_isr | INT 8 handler | Tick count, BIOS chain, song step, EOI | verified |
| 0x6AA8 | snd_fetch | internal | Song bytecode interpreter (handlers 0x6B5A–0x6C38, table CS:6B42) | verified |
| 0x6C3B | delay_ticks | `void (u16 n)` | Busy wait n ticks | verified |
| 0x6C5B | getkey_timeout | `u16 (u16 n)` | getkey with n-tick timeout; no callers | verified |
| 0x6C85 | gfx_set_text_colours | `void (u16 fg, u16 bg)` | DS:690E / DS:6910 | verified |
| 0x7864 | getkey_until_deadline | `u16 (void)` | getkey until deadline, else 0 | verified |
| 0x7881 | wait_deadline | `void (void)` | Busy wait until deadline | verified |
| 0x7894 | set_deadline | `void (u16 ticks)` | DS:650C = now, DS:650E = ticks | verified |
| 0x89F0 | snd_stop_oneshot | `void (void)` | DS:643E &= 6 | verified |
| 0x89F6 | snd_off | `void (void)` | DS:643E &= 3; no callers | verified |
| 0x89FC | snd_on | `void (void)` | DS:643E \|= 4; no callers | verified |
| 0x8A02 | snd_oneshot_active | `u8 (void)` | DS:643E & 1; no callers | verified |
| 0x8A08 | snd_stop_all | `void (void)` | DS:643E &= 4 | verified |
| 0x8A0E | snd_set_loop | `void (u16 off, u16 seg)` | Sets background loop stream; starts it if idle | verified |
| 0x8A3E | snd_play_oneshot | `void (u16 off, u16 seg)` | Starts a stream now (current note count still finishes) | verified |
| 0x8AFD | input_set_mode | `void (u16 mode)` | DS:6422 = mode (main: 4) | verified |
| 0x8BAF | rand8 | `u8 (void)` | Table PRNG DS:6520/6522 (not the CRT rand) | verified |
| 0x95B0 | menu_key | `int (void)` | getkey_until_deadline: 0→−1, ESC→1, else code | verified |
| 0x95D9 | toupper_c | `int (char c)` | a–z → A–Z | verified |
| 0x95F4 | joy_calibrate_screen | `void (void)` | 3×3 grid calibration screen | verified |
| 0x9A01 | ticks_now | `u16 (void)` | Returns DS:642A | verified |
| 0x9A05 | ticks_elapsed | `u16 (u16 start)` | \|now − start\| (absolute difference) | verified |
| 0xA12F | joy_read | `u8 (void)` | Port 201h timing, adaptive calibration, direction + button bits | verified |
| 0xDDC3 (DGROUP:1423) | div0_isr | INT 0 handler (data segment) | AX=0xFFFF, skip 2-byte div, iret (installed in driving by 0x4908) | verified |

### 2.3 Resources, memory, misc

| image addr | proposed name | signature | one-line purpose | confidence |
|---|---|---|---|---|
| 0x6762 | res_find | `far ptr (u16 aoff, u16 aseg, char *name4)` | Linear case-sensitive 4-char lookup; fatal if missing | verified |
| 0x78A5 | load_raw_archive | `far ptr (char *fname, u16 reserve)` | Uncompressed archive (tdsnd.snd) via raw INT 21h; "%s FILE ERROR" | verified |
| 0x8A5B | load_archive | `far ptr (char *fname, u16 reserve)` | Cache check, load_packed_archive, relocate offset table | verified |
| 0x8CC0 | mem_init | `void (void)` | Grabs the largest DOS memory block | verified |
| 0x8D8C | crc8_b8 | `u8 (u8 *buf, int len, u8 seed)` | SCORES checksum (FORMATS.md) | verified |
| 0x8DB0 | (data) cp_signature | 8 words | Protection sector signature | verified |
| 0x8DC7 | copy_protection_check | `int (void)` | 0 = pass, 0xFEF6 = fail | verified |
| 0x92A8 | text_input_line | `int (char *buf, int maxlen, int x, int y, u16 timeout)` | High-score name editor (see game_flow) | likely |
| 0x94AB | fatal | `void (char *fmt, ...)` | Text mode, timer_restore, printf, abort | verified |
| 0x94C7 | res_find_list | `void (far arc, char *names, far ptr *out)` | res_find for a packed 4-char name list | verified |
| 0x9507 | draw_text_centered | `void (char *s, int y)` | x = 0xA0 − strlen*4 | verified |
| 0x9530 | draw_rect_outline | `void (x0, y0, x1, y1, colour)` | Four fill_rect calls | verified |
| 0x9A86 | load_packed_archive | `far ptr (char *fname, u16 reserve)` | `Pckd` header, cache slot, methods 2/3/4/8 | verified |
| 0x9C1E | huff_read_tree | `void (void)` | Method 4 tree (FORMATS.md) | verified |
| 0x9C76 | huff_read_word | `int (void)` | Two input bytes | likely |
| 0x9C90 | huff_decode | `int (void)` | Next Huffman symbol, −1 at EOF | verified |
| 0x9CF9 | rle90_out | `void (u8 c)` | RLE90 output state machine | verified |
| 0x9D64 | pack_getc | `int (void)` | Buffered 1 KB input, −1 when packed length exhausted | verified |
| 0x9DD3 | pack_putc | `void (u8 c)` | Huge-pointer output, drops bytes past unpacked length | verified |
| 0x9E1D | lzw_decompress | `void (void)` | Method 8 | verified |
| 0x9FA2 | lzw_getcode | `int (void)` | LZW code reader | verified |
| 0xA0CF | lzw_alloc_tables | `void (void)` | malloc(0x438B); "DECOMP BUFFER ALLOCATE ERROR" | verified |
| 0xA111 | lzw_free_tables | `void (void)` | free tables | verified |
| 0xA280 | cache_find | `u16 seg (char *fname)` | 30-slot archive cache lookup (12 chars, exact case) | verified |
| 0xA2BE | cache_alloc | `u16 seg (char *fname, u16 paras, u16 reserve)` | Low-end allocation with LIFO eviction; "OUT OF MEMORY LOADING %s" | verified |
| 0xA340 | buf_alloc | `u16 seg (u16 paras)` | High-end buffer allocation, 8 slots | verified |
| 0xA37E | buf_free | `void (u16 seg)` | "BUFFER NOT FOUND RELEASE ERROR" | verified |
| 0xA3DF | mem_debug_dump | `void (void)` | MBOT/LOW/HIGH/MTOP dump; unreferenced | verified |

### 2.4 Microsoft C 4.x runtime (identification only)

Details and callers: `tables/crt_functions.json`. The game itself calls `strcmp strlen strncpy strcat
strcpy sprintf printf abort fopen fclose fgets fscanf fprintf sscanf open read close malloc free rand
srand itoa` and the long helpers; replace all with host libc except **`rand`/`srand`, which must be
bit-exact**: `seed = seed*0x343FD + 0x269EC3; return (seed >> 16) & 0x7FFF` (u32 seed, initial 1).

| image addr | name | confidence |
|---|---|---|
| 0xA4E3 | abort | likely |
| 0xA4F8 | close | verified |
| 0xA50C | _astart (entry) | verified |
| 0xA5B6 | fclose | verified |
| 0xA659 | fgets | verified |
| 0xA6B1 | fopen | verified |
| 0xA6D7 | fprintf | verified |
| 0xA70E | fscanf | likely |
| 0xA722 | free | verified |
| 0xA730 | malloc | verified |
| 0xA776 | open | verified |
| 0xA8C7 | printf | verified |
| 0xA8FD | srand | verified |
| 0xA90E | rand | verified |
| 0xA93A | read | verified |
| 0xAA00 | sprintf | verified |
| 0xAA51 | sscanf | verified |
| 0xAA88 | strcmp | verified |
| 0xAABD | strlen | verified |
| 0xAAD8 | strncpy | verified |
| 0xAB00 | _filbuf | likely |
| 0xABE2 | _flsbuf | likely |
| 0xAD0D | _freebuf | likely |
| 0xAD3C | _openfile | likely |
| 0xAE3F | _stbuf | likely |
| 0xAEDE | _ftbuf | likely |
| 0xAF67 | _nmalloc search | likely |
| 0xB048 | _amlink | guess |
| 0xB082 | _amexpand | guess |
| 0xB0A4 | _amallocbrk | likely |
| 0xB0C3 | _nullcheck | likely |
| 0xB0DF | creat | verified |
| 0xB152 | umask helper | likely |
| 0xB165 | _cinit | verified |
| 0xB214 | exit | likely |
| 0xB22B | _exit | verified |
| 0xB257 | _ctermsub | likely |
| 0xB270 | _initterm | likely |
| 0xB27F | _dosret0 | likely |
| 0xB287 | _dosretax | likely |
| 0xB2C7 | fflush | likely |
| 0xB32F | _input (scanf engine) | likely |
| 0xB698 | _input helpers (0xB698–0xBAD8) | guess |
| 0xBAFF | itoa | likely |
| 0xBB1A | _NMSG_TEXT | likely |
| 0xBB4A | _NMSG_WRITE | verified |
| 0xBB73 | _output (printf engine) | verified |
| 0xBE03 | _output helpers (0xBE03–0xC35A) | likely |
| 0xC382 | _setargv | likely |
| 0xC467 | _setenvp | likely |
| 0xC4CD | strcat | verified |
| 0xC4FE | strcpy | verified |
| 0xC523 | _getstream | likely |
| 0xC55A | unlink | verified |
| 0xC567 | sbrk | likely |
| 0xC5D5 | _growseg | likely |
| 0xC62B | _chkstk | verified |
| 0xC644 | isatty | likely |
| 0xC6B2 | ungetc | likely |
| 0xC70C | write | verified |
| 0xC849 | flushall | likely |
| 0xC87A | _aNldiv | verified |
| 0xC91D | _aNlmul | verified |
| 0xC949 | _aNlshl | verified |
| 0xC954 | _aNlshr | verified |
| 0xC95F | _aNaldiv | likely |
| 0xC981 | _aNalshl | likely |

No `getch/kbhit/int86` in the binary. The CRT installs its own INT 0 handler (CS:A5A8, saved DS:71B0)
in `_cinit` and restores it in `_exit`.

## 3. Globals table

Code-segment variables are listed as `CS:xxxx`.

| DS offset | proposed name | type/size | meaning | written by | read by |
|---|---|---|---|---|---|
| CS:528E | gfx_desc_pool_top | u16 | Next free byte of descriptor pool (init 0x5290, limit 0x5A60) | 0x5150, 0x79FF | 0x5150, 0x79FF |
| CS:5A60 | gfx_cur_desc | far ptr | Selected target descriptor (init CS:5A7C) | 0x5128 | 0xA4D9 |
| CS:5A64 | gfx_cur | 12 words | Live copy of selected descriptor: +2 planes CS:5A66..6C, rowtab CS:5A6E, clip x0/x1/y0/y1 CS:5A70..76, stride CS:5A78 | 0x5128, 0x50A1, 0xA3CB, game (0x3ACE, 0x3AF7) | all primitives |
| CS:5A7C | gfx_screen_desc | 12 words | Screen: planes A000h, rowtab CS:5A94, clip 0,40,0,200, stride 40 | 0x50A1, game | 0x8B08, 0x8C1E |
| CS:5A94 | gfx_screen_rows | u16[200] | y*40 | const | all |
| DS:00CC | pal_game | u8[17] | Game palette (see ega_palettes.json) | const | 0x4D84 via main |
| DS:0040 | str_herc | char[] | "herc" command-line switch | const | main |
| DS:008A | herc_mode | u16 | 1 when Hercules selected | main | main, 0x098C |
| DS:0890 | road_buf_desc | far ptr | 40×112×3-plane road view buffer (+0894 header ptr, +0898 rowtab) | 0x4792 | scene_render |
| DS:089A | buf_desc_b | far ptr | Buffer sized from sprite DS:13B7 (see scene_render) | 0x4792 | scene_render |
| DS:08B2 | buf_desc_c | far ptr | Buffer sized from sprite DS:1393 (see scene_render) | 0x4792 | scene_render |
| DS:636C | fill_left_mask | u8[8] | FF 7F 3F 1F 0F 07 03 01 | const | 0x4941 |
| DS:6374 | fill_right_mask | u8[8] | 80 C0 E0 F0 F8 FC FE FF | const | 0x4941 |
| DS:637C | pal_default | u8[17] | Identity 200-line palette | const | 0x4D96 |
| DS:63A8 | joy_dir_map | u8[16] | Joystick bits → direction | const | 0x5C24 |
| DS:63B8 | ext_scan_dir_map | u8[12] | [scan−0x46] → direction | const | 0x5C24 |
| DS:63C4 | digit_dir_map | u8[10] | '0'..'9' → direction \| fire | const | 0x5C24 |
| DS:63F0 | kbd_shift_btn | u8 | Shift flags \| buttons; write-only | 0x680E, 0x68F4 | – |
| DS:63F2 | joy_menu_scan | u16[16] | Joystick bits → menu scan codes | const | 0x680E, 0x68F4 |
| DS:6420 | joy_menu_last | u16 | Edge detector for joystick menu codes | 0x68F4 | 0x68F4 |
| DS:6422 | input_mode | u16 | getkey dispatch index (0/2/4) | 0x8AFD | 0x67E8 |
| DS:6424 | modal_pause | u8 | 1 in pause/calibration: song frozen, speaker off, sim skipped | 0x5C24, 0x6846 | 0x6A1F, 0x3B1F |
| DS:6426 | old_int8 | far ptr | Saved BIOS INT 8 | 0x69CF | 0x694A, 0x6A1F |
| DS:642A | tick_count | u16 | ++ per 100.04 Hz tick | 0x6A1F | 0x9A01, 0x9A05 |
| DS:642C | snd_ptr | seg (642C) : off (642E) | Current bytecode position | 0x8A0E, 0x8A3E, ISR | ISR |
| DS:6430 | snd_loop_ptr | seg (6430) : off (6432) | Background loop stream | 0x8A0E | ISR |
| DS:6434 | chain_reload | u16 | BIOS chain period (5 menu, 0x7D00 drive) | 0x698C, 0x699E, 0x69B6 | ISR |
| DS:6436 | chain_count | s16 | Countdown to BIOS INT 8 call | 0x699E, 0x69B6, ISR | ISR |
| DS:6438 | note_left | u16 | Remaining ticks of current event | ISR | ISR |
| DS:643A | note_cut | u16 | Speaker off when note_left equals it | ISR | ISR |
| DS:643C | snd_shift | u8 | Articulation shift (cut = dur >> shift), init 3 | ISR (FE) | ISR |
| DS:643D | snd_playing | u8 | 0 idle, 1 one-shot, 2 loop | 0x69CF, 0x8A0E, 0x8A3E, 0x5C24, 0x6846, ISR | ISR, 0x8A0E |
| DS:643E | snd_flags | u8 | bit0 one-shot, bit1 loop set, bit2 sound enabled (init 4) | 0x89F0–0x8A3E, 0x5C24, 0x6846, ISR | ISR, 0x5C24 |
| DS:643F | chain_enable | u8 | 1 = chain BIOS INT 8 | 0x698C, 0x699E, 0x69B6 | ISR |
| DS:6440 | loop_cnt | s16[3] | Loop counters FD/FC/FB | ISR | ISR |
| DS:6446 | loop_start | u16[3] | Loop body offsets | ISR | ISR |
| DS:644C | loop_end | u16[3] | Loop end-opcode offsets | ISR | ISR |
| DS:6452 | note_div | u16[0x5E] | PIT divisor per note (note_divisors.json) | const, patched 64FC/64FE/6500 | ISR |
| DS:64FC | note_div_engine | u16 | Slot 0x55: engine divisor DS:2077[rpm_disp>>6] | 0x1FE4, 0x3B1F | ISR |
| DS:64FE | note_div_skid | u16 | Slot 0x56: 0xFFFF / 0x08E8 skid / 0x0474 grind | sim | ISR |
| DS:6500 | note_div_beep | u16 | Slot 0x57: 0x0384 radar beep | 0x1FEA | ISR |
| DS:650C | deadline_start | u16 | set_deadline start tick | 0x7894 | 0x7864, 0x7881 |
| DS:650E | deadline_len | u16 | set_deadline length | 0x7894 | 0x7864, 0x7881 |
| DS:6520 | rand8_idx | u16 | rand8 index | 0x8BAF | 0x8BAF |
| DS:6522 | rand8_tab | u8[256] | rand8 table | 0x8BAF | 0x8BAF |
| DS:6642 | herc_crtc_gfx | u8[12] | 6845 values, graphics | const | 0x8CEC |
| DS:664E | herc_crtc_text | u8[12] | 6845 values, text | const | 0x8D3C |
| DS:66E8 | joy_enabled | u8 | 0 keyboard only, 1 joystick | 0x5C24, 0x6846, 0x95F4 | 0xA12F |
| DS:66E9 | joy_calibrated | u8 | Calibration screen shown | 0x95F4 | 0x5C24, 0x6846 |
| DS:66EA | calib_sq_x | u16[9] | Grid square x per direction | const | 0x95F4 |
| DS:66FC | calib_sq_y | u16[9] | Grid square y per direction | const | 0x95F4 |
| DS:690E | text_fg | u16 | Text foreground (init 3) | 0x6C85 | 0x4BE7 |
| DS:6910 | text_bg | u16 | Text background (init 0) | 0x6C85 | 0x4BE7 |
| DS:6912 | text_margin_x | u16 | x after CR/LF (0) | const | 0x4BE7 |
| DS:6914 | text_x | u16 | Cursor x, pixels (drawn at x>>3 bytes) | 0x4BD0, 0x74E3, 0x4BE7 | 0x4BE7 |
| DS:6916 | text_y | u16 | Cursor y | 0x4BD0, 0x74E3, 0x4BE7 | 0x4BE7 |
| DS:691A | text_glyph_h | u16 | 8 | const | 0x4BE7 |
| DS:691C | text_font | far ptr | Font pointer table DS:6E2C | const | 0x4BE7 |
| DS:6920 | text_adv_x | u16 | 8 | const | 0x4BE7 |
| DS:6922 | text_adv_y | u16 | 8 | const | 0x4BE7 |
| DS:6924 | text_enabled | u16 | 1 (text drawn only when 1) | const | 0x4BE7 |
| DS:6A3C | lzw_tables | u16 | malloc'd LZW tables | 0xA0CF, 0xA111 | 0xA0CF, 0xA111 |
| DS:6A3E | joy_x | u16 | X loop count (0x50 on timeout); DS:6A40 = joy_y | 0xA12F | 0xA12F |
| DS:6A42 | joy_port_pre | u8 | 201h sample before trigger | 0xA12F | 0xA12F |
| DS:6A43 | joy_result | u8 | Bits being built | 0xA12F | 0xA12F |
| DS:6A44 | joy_xmin | u16 | Learned min (init 0x50); DS:6A46 xmax (init 0) | 0xA12F | 0xA12F |
| DS:6A48 | joy_xover_min | u16 | Smallest above-max sample; DS:6A4A countdown (8) | 0xA12F | 0xA12F |
| DS:6A4C | joy_xlo | u16 | 25% threshold; DS:6A4E 75% threshold | 0xA12F | 0xA12F |
| DS:6A50 | joy_ymin | u16 | Y equivalents of 6A44–6A4E at 6A50–6A5A | 0xA12F | 0xA12F |
| DS:6AC4 | gfx_target_save_area | u16[24] | Saved CS:5A64..5A93 | 0xA3B7 | 0xA3CB |
| DS:6E2C | font_ptrs | u16[256] | Near ptr per character, 0 = none (font8x8.json) | const | 0x4BE7 |
| DS:746C | lzw_tab_ptrs | u16 ×3 (746C/7470/748C) | Offsets into lzw_tables | 0xA0CF | 0x9E1D, 0x9FA2 |
| DS:7478 | rle_state | u16 | RLE90 state | 0x9A86, 0x9CF9 | 0x9CF9 |
| DS:78E0 | pack_inptr | u16 | Input buffer cursor | 0x9A86, 0x9D64 | 0x9D64 |
| DS:790E | unpacked_len | u32 | Expected output size | 0x9A86 | 0x9DD3, 0x9A86 |
| DS:7B14 | mem_bot | u16 seg | Base of DOS block | 0x8CC0 | 0xA3DF |
| DS:7B18 | out_count | u32 | Bytes emitted | 0x9A86, 0x9DD3 | 0x9DD3, 0x9A86 |
| DS:7B24 | mem_low | u16 seg | Next free segment above archive cache | 0x8CC0, 0xA2BE | 0xA2BE, 0xA340 |
| DS:7B2E | packed_left | u32 | Remaining packed bytes | 0x9A86, 0x9D64 | 0x9D64 |
| DS:7D36 | mem_top | u16 seg | End of DOS block | 0x8CC0 | 0xA3DF |
| DS:7D38 | cache_slots | 16 B × 30 | `{char name[12]; u16 paras; u16 seg}` | 0xA2BE | 0xA280, 0xA2BE |
| DS:7F18 | mem_high | u16 seg | Lowest buffer segment | 0x8CC0, 0xA340, 0xA37E | 0xA2BE, 0xA340, 0xA37E |
| DS:7F1A | page_buf_desc | far ptr | 40×200×4-plane page buffer descriptor | main, 0x1030 | game_flow |
| DS:7F1E | buf_slots | 4 B × 8 | `{u16 seg; u16 paras}` | 0xA340, 0xA37E | 0xA340, 0xA37E |
| DS:7F3E | pack_inbuf | u16 | malloc(0x400) | 0x9A86 | 0x9D64 |
| DS:7F42 | pack_fd | u16 | File handle | 0x9A86 | 0x9D64 |
| DS:8096 | pack_inpos | u16 | Bytes consumed in input buffer | 0x9A86, 0x9D64 | 0x9D64 |
| DS:809C | pack_outptr | huge ptr | Output cursor | 0x9A86, 0x9DD3 | 0x9DD3 |
| DS:80A0 | in_count | u32 | Bytes read (unused) | 0x9A86, 0x9D64 | – |

Driving-ISR globals in the simulation range used here: DS:091B rpm, DS:091D rpm_disp, DS:093A
drive_tick, DS:0934 old_int0, CS:3B18 drive_old_int8, DS:0929 crash state, DS:80A4 stage clock
(see simulation spec).

## 4. Pseudocode

### 4.1 Planar model used by every primitive

The software framebuffer must be **planar**, not a plain indexed image, because the game draws into
targets that lack planes (3-plane buffers) and uses per-plane AND/OR/XOR:

```c
typedef struct {            /* "descriptor", 0x18 bytes + row table, lives in CS:5290..5A5F   */
    u16 hdr_off;            /* +00 always 0 -> (hdr_off, plane_seg[0]) = far ptr to 16-byte header */
    u16 plane_seg[4];       /* +02..+08 plane k storage, 0 = plane absent (writes skipped)   */
    u16 rowtab;             /* +0A near ptr (CS) to row table: row y -> byte offset in plane  */
    s16 clip_x0, clip_x1;   /* +0C,+0E clip columns in BYTES (8-pixel cells), x1 exclusive    */
    s16 clip_y0, clip_y1;   /* +10,+12 clip rows, y1 exclusive                                 */
    u16 stride;             /* +14 bytes per row (40 for 320 px)                               */
    u16 pad;                /* +16 padding added to each plane block (0..15)                  */
    u16 row[h];             /* +18 row table                                                   */
} Target;
```

* Screen descriptor (static) at CS:5A7C: planes = A000h ×4, rowtab CS:5A94 (`row[y] = y*40`, 200 rows),
  clip 0,40,0,200, stride 40.
* Current target = 12-word copy at CS:5A64..5A7B (plane segs CS:5A66.., rowtab CS:5A6E, clip CS:5A70..76,
  stride CS:5A78), far pointer to the selected descriptor at CS:5A60. All primitives read only the copy;
  **game code pokes the copy directly** (e.g. 0x3ACE sets clip y 0x13..0x6F after selecting a buffer).
* Every primitive tests `cur.plane_seg[0] == 0xA000`: if so it uses the EGA register path, otherwise the
  RAM path. Results are identical except for the quirks flagged below.
* An off-screen buffer made by 0x5150 **is a sprite**: one DOS block = 16-byte sprite header followed by
  one `w*h+pad` block per present plane, `row[y] = 0x10 + y*w`. It can be passed to the sprite blitters
  (via `desc->hdr_off:plane_seg[0]`), and to the dissolve 0x768B.

Port: keep `Target { u8 *plane[4] (NULL if absent); int stride,h; clip; }` with each plane a linear byte
array of `stride*h` bytes plus slack (unclipped blits write one byte past the row end and may start
before it; wrap into the next/previous row exactly as the linear offset does). The physical screen is a
Target with 4 planes of 40×200. Present it by combining the 4 planes to a 4-bit index per pixel
(bit k from plane k, MSB of each byte = leftmost pixel), mapping through the current 16-entry palette
(tables/ega_palettes.json) into an SDL_Texture (SDL_PIXELFORMAT_XRGB8888 streaming, 320×200, scaled ×2 or
with 4:3 aspect correction via SDL_SetRenderLogicalPresentation). There is no page flipping, no CRTC start
address and no 3DAh retrace wait anywhere in TDEGA: frames are composed in RAM buffers and copied to
A000h with a blit; the port should present the texture after each such copy (or once per game loop).

### 4.2 Sprite blitter family (the core)

Sprite header (FORMATS.md): `+0 w (bytes) +2 h +4 hot_x +6 hot_y +8 x +A y +C planemap[4]`, data at +0x10.
`blocksize = (h & 0xFF) * (w & 0xFF) + (planemap[3] >> 4)` — the high nibble of planemap[3] is the
per-plane padding (0x5150 writes it; shipped sprites have 0). 8-bit multiply: `mul byte ptr [si]`.

24 entry points = 8 operation tables × 3 position modes:

| entry (hotspot / raw / own) | clip | op | GC func (3CFh idx 3) | flags | RAM table |
|---|---|---|---|---|---|
| 0x5D84 / 0x5DB6 / 0x5DE2 | yes | REPLACE | 00 | 3 | CS:6124 |
| 0x4DF1 / 0x4E05 / 0x4E19 | yes | OR | 10 | 2 | CS:4E2D |
| 0x8308 / 0x831C / 0x8330 | yes | AND | 08 | 1 | CS:8344 |
| 0x8058 / 0x806C / 0x8080 | yes | XOR | 18 | 4 | CS:8094 |
| 0x6CBE / 0x6CF0 / 0x6D1C | no  | REPLACE | 00 | 3 | CS:6FD8 |
| 0x7A37 / 0x7A4B / 0x7A5F | no  | OR | 10 | 2 | CS:7A73 |
| 0x7C3B / 0x7C4F / 0x7C63 | no  | AND | 08 | 1 | CS:7C77 |
| 0x7E54 / 0x7E68 / 0x7E7C | no  | XOR | 18 | 4 | CS:7E90 |

Position modes (args are `(u16 spr_off, u16 spr_seg [, s16 x, s16 y])`):
* **hotspot**: `px = x - hdr.hot_x; py = y - hdr.hot_y`
* **raw**: `px = x; py = y`
* **own**: `px = hdr.x & 0xFFFC; py = hdr.y` (note: low 2 bits dropped, not 3)

Each table has 8 routines indexed by `shift = px & 7`; the EGA path uses one shared table per clip class
(CS:6134 clipped, CS:6FE8 unclipped) with the GC function register doing the op.

```c
void blit(Target *t, Sprite *s, int px, int py, int op, int flags, bool clip)
{
    int shift = px & 7;
    int col   = px >> 3;               /* arithmetic shift (sar) */
    int rows  = s->h, w = s->w, vis_w = w;
    int src_skip_top = 0, left_skip = 0;
    u8  edge = 1;                      /* bit0: right edge NOT clipped -> write carry byte
                                          bit1: left edge clipped -> seed carry from column-1 */
    if (clip) {
        /* vertical */
        if (py >= t->clip_y0) {
            int over = py + rows - t->clip_y1;
            if (over > 0) { rows -= over; if (rows <= 0) return; }
        } else {
            int nr = py + rows - t->clip_y0;
            if (nr <= 0) return;
            src_skip_top = (u8)(rows - nr) * (u8)w;   /* mul byte */
            rows = nr; py = t->clip_y0;
            int over = py + rows - t->clip_y1;
            if (over > 0) { rows -= over; if (rows <= 0) return; }
        }
        /* horizontal, in byte columns */
        if (col >= t->clip_x0) {
            int over = col + w - t->clip_x1;
            if (over >= 0) {           /* NB: >= : touching the right clip counts as clipped */
                edge = 0; vis_w = w - over; if (vis_w <= 0) return;
                right_skip = over;     /* row_src_skip = over */
            }
        } else {
            int nv = col + w - t->clip_x0;
            if (nv <= 0) return;
            left_skip = w - nv; vis_w = nv; col = t->clip_x0; edge |= 2;
            /* row_src_skip = left_skip, source starts at +left_skip */
        }
    }
    /* per-row source skip after vis_w bytes = w - vis_w (both clip cases). */
    int dst0 = t->row[py] + col;                   /* linear offset in each plane */

    /* 1. constant planes (done first, whole visible rectangle, pixel exact at the shifted edges) */
    if (flags & 1)                                  /* REPLACE and AND only */
        for (b = 0; b < 4; b++) if ((s->pm[0] >> 4) & (1 << b) && t->plane[b])
            rect_op(t->plane[b], dst0, vis_w, rows, shift, CLEAR);     /* 0x97D4 / EGA 0x98C2 */
    if (flags & 6)                                  /* REPLACE, OR -> set ; XOR -> xor */
        for (b = 0; b < 4; b++) if ((s->pm[1] >> 4) & (1 << b) && t->plane[b])
            rect_op(t->plane[b], dst0, vis_w, rows, shift, (flags & 4) ? XOR : SET); /* 0x981E/0x9868 */

    /* 2. stored planes: stored plane k (k=0,1,..) feeds every colour bit in pm[k] & 0x0F.
          The list stops at the first pm[k] with low nibble 0; RAM path also stops after the byte
          that brings the number of (non-absent) destinations to >= 4. */
    for (k = 0; k < 4 && (s->pm[k] & 0x0F); k++)
        for (b = 0; b < 4; b++) if ((s->pm[k] & (1 << b)) && t->plane[b])
            copy_plane(t->plane[b], dst0,
                       s->data + k*blocksize + src_skip_top + left_skip,
                       vis_w, rows, w - vis_w, shift, edge, op);
    /* RAM path processes the destination list last-to-first, EGA path first-to-last; only
       matters if one colour bit is listed twice (never in shipped data). */
}
```

`rect_op(plane, dst, n, rows, shift, OP)` (0x97D4 clear / 0x981E set / 0x9868 xor; EGA 0x98C2/0x992B/0x9994):
for `shift == 0` apply OP to `n` whole bytes per row. Otherwise `m = CS:97CC[shift]`
(`00 80 C0 E0 F0 F8 FC FE`): first byte OP on bits `~m`, `n-1` middle bytes whole, byte `n` OP on bits `m`
— i.e. exactly pixels `[8*col+shift, 8*(col+n)+shift)`. Row advance `stride - n`. (For `n == 1` it does the
two partial bytes only.)

**EGA write-function caveat.** On the screen the GC function register (3CEh index 3) stays set to the
op while the EGA helpers and copy routines run, and they write *pre-combined* bytes
(`v = (d & keep) | new`, or `0x00/0xFF` for whole bytes). The hardware then applies the op again:
REPLACE, OR and AND give the same result as the RAM path, but **XOR does not**: every partial edge byte
becomes `v ^ d`, i.e. the destination pixels *outside* the sprite in the first and last byte of each row
are cleared, and the in-sprite pixels of partial bytes in `rect_op(XOR)` become 1 instead of inverted
(whole middle bytes are correct: 0xFF ^ d). Only matters for XOR blits (0x8058 family, 0x7E54 family)
drawn directly on the screen with `shift != 0`; XOR callers in scene_render appear to draw into RAM
buffers — confirm there.

`copy_plane` byte semantics, per row, `s` = source bytes, `d` = destination:
* `shift == 0`: `d[i] = OP(d[i], s[i])` for `i < vis_w`.
* `shift = n > 0`: output byte i = `(s[i] >> n) | carry`, then `carry = (s[i] << (8-n)) & 0xFF`.
  - initial carry:
    * not left-clipped, REPLACE/AND: carry = `d[0] & ~(0xFF >> n)` for REPLACE (preserve the n leftmost
      destination pixels) and `0xFF & ~(0xFF>>n)` for AND (so AND keeps them); OR/XOR: 0.
    * left-clipped: `s[-1] << (8-n)` (the pixels of the clipped column that spill in) — correct in every
      EGA routine and in the RAM REPLACE routines. **RAM OR/AND/XOR clipped tables (4E2D, 8344, 8094) use
      `s[-1] >> n` for n = 1..3** (and for AND without the keep bits), so the first byte receives
      `(s[0] | s[-1]) >> n` ORed/ANDed/XORed. n = 4..7 are correct.
  - output i written with OP (REPLACE writes it, others combine with d[i]).
  - after the row, if `edge & 1` (unclipped families: always): byte `vis_w` gets the final carry:
    REPLACE: `d = (d & (0xFF >> n)) | carry`; OR: `d |= carry`; AND: `d &= carry | (0xFF >> n)`;
    XOR: `d ^= carry`. If the right edge is clipped the spill-over pixels are dropped.
* Row advance: dest `+= stride - vis_w` (EGA path hard-codes 40), source `+= w - vis_w`.

Net pixel semantics (ignoring the two quirks): for every pixel P of the sprite rectangle
`[8*col+shift, 8*(col+w)+shift) × [py, py+h)` that survives clipping, and every colour bit b:
`bit_b = OP(const_b(bit_b), srcbit_k)` for each stored plane k mapping to b, where const_b clears
(pm[0] high, REPLACE/AND), sets (pm[1] high, REPLACE/OR) or inverts (pm[1] high, XOR). Colour bits not
mentioned anywhere are left untouched even in REPLACE mode. **There is no transparent colour**: masking
is done by drawing a mask sprite with AND (e.g. `rg0m`), then the image with OR — the scene code does
exactly this pairing (0x8308 then 0x4DF1; 0x7C63 then 0x7A5F).

Examples (FORMATS.md's reading of the high nibbles was wrong; verified by these and by the dissolve
routine's 0x781D "clear" / 0x7832 "set" entries):
* `01 02 04 08` plain 4-plane image.
* `07 80 00 00` one stored plane → bits 0,1,2; plane 3 set: pixels are 8 or 15.
* `87 00 00 00` one stored plane → bits 0,1,2; plane 3 **cleared** (REPLACE/AND): 0 or 7.
* `52 80 00 00` stored plane → bit 1; planes 0,2 cleared; plane 3 set: 8 or 10.
* `f0 00 00 00` (`blnk`) no stored plane; all planes cleared: a black rectangle.

### 4.3 Other primitives

**0x4941 fill_rect(x, y, w, h, colour)** — pixels `[x, x+w) × [y, y+h)`, **no clipping**, uses
DS:636C left masks `FF 7F 3F 1F 0F 07 03 01` and DS:6374 right masks `80 C0 E0 F0 F8 FC FE FF`.
RAM: per present plane k, OR the masks/0xFF if `colour>>k & 1` else AND with the inverted masks.
EGA: write mode 2, map mask 0Fh, bit mask per partial byte, replace. Result: pixel = colour (absent
planes untouched).

**0x4B98 clear_screen(colour)** — always A000h, all 4 planes, 8000 bytes = colour (write mode 2). Ignores
the selected target.

**0x74F4 clear_target(colour)** — fills the current clip rectangle (byte columns × rows) with colour.
RAM: per present plane 0x00/0xFF; when `clip width == stride` it uses `rep stosw` with
`count = (stride>>1) * rows` (16-bit signed imul). EGA path quirks: full width uses `imul dl`
(8-bit: `count = 40 * (s8)rows`, wrong for rows ≥ 128 → writes up to 0xF740 bytes); partial width
has `dec dx; jle` instead of `jg`, so it fills only the **first row** when rows > 1 (and leaves write
mode 2 set). The EGA full-width path also never writes the sequencer map mask, so only the planes left
enabled by the previous primitive are filled. Known screen use: 0x1DFA `gfx_clear_clip(8)` with clip rows
0x13..200 (full width, 181 rows → overshoot into invisible VRAM, visually rows 19–199; see 4.4a). All other
callers clear RAM buffers. Implement the RAM behaviour plus "full width, rows ≥ 128 → fill to the bottom".

**0x85D5 draw_line(x0, y0, x1, y1, colour)** — pixel coordinates, clip = current clip ×8 in x.
* `y0 == y1`: clip horizontally, then `fill_rect(xmin, y, len, 1, colour)` (skipped if y outside).
* `x0 == x1`: clip vertically, then `fill_rect(x, ymin, 1, len, colour)`.
* else DDA, 16.16 fixed point; `dx = |x1-x0|+1`, `dy = |y1-y0|+1`; the walk always goes in +major
  direction (endpoints swapped when needed):
  * x-major (`dx >= dy`): `step = (dx==dy) ? ±0x10000 : ±((dy<<16)/dx)`; phase 1 skips points while
    outside the clip (x++, y += step); phase 2 plots while `y0c <= y < y1c && x < x1c`, stops at the
    first failing point.
  * y-major: `step = ±((dx<<16)/dy)`; phase 1 skips while outside, **but advances x by the constant
    0xFFF0FFEE (−15.00027) per skipped row instead of `step`** (assembler typo `mov ax,0FFEEh` for
    `mov ax,[bp-12h]`); phase 2 plots while `y < y1c && x0c <= x < x1c`.
  * plot: RAM target → OR the pixel bit into **every present plane (colour ignored → 15)**; screen →
    write mode 2, GC function OR: pixel |= colour. Callers: gauge needles (0x35C6, 0x392C) and the
    joystick calibration screen (0x95F4).

**0x4BD0 draw_text(str, x, y)** / **0x4BE7 draw_text_at_cursor(str)** / **0x74E3 set_cursor(x, y)** /
**0x6C85 set_text_colours(fg, bg)** — 8×8 font (tables/font8x8.json, pointer table DS:6E2C). For each
char: 0 ends; CR or LF: `x = DS:6912 (0), y += DS:6922 (8)`; char with null glyph pointer: skipped, no
advance; otherwise the glyph is drawn **opaque** at byte column `x>>3`, rows `y..y+DS:691A(8)-1`:
pixel = bit ? fg : bg for every plane (planes where fg==bg get the constant bit), then
`x += DS:6920 (8)`. No clipping. Does nothing unless DS:6924 == 1 (always 1). Defaults fg=3, bg=0.

**0x768B dissolve(spr_off, spr_seg, phase)** — screen only (EGA path, map mask + read map). Draws a
sprite (normally the 320×200 page buffer DS:7F1A) at byte column `hdr.x` (not >>3) and row `hdr.y`,
updating one pixel per byte:
```c
for (pass = 11; pass >= 0; pass--) {
    int r0 = CS_7627[pass];         /* 0B 05 08 02 0A 04 07 01 09 03 06 00 */
    for (r = r0; r < h; r += 12) {
        u8 m = CS_7633[phase & 7];  /* 01 08 40 02 10 80 04 20 */
        for each destination entry e (stored-plane bits, then pm[0]-high "clear", pm[1]-high "set"):
            for (i = 0; i < w; i++) { d[i] = (src[i] & m) | (d[i] & ~m); m = ror8(m, 1); }
            /* m is NOT reset between entries */
        phase = (phase + 1) & 0xFF;   /* the stack argument is incremented per row */
    }
}
```
Plane size here is `h*w` (padding ignored). The "clear"/"set" entries (0x781D/0x7832) are buggy: they
clear/set only the first byte's masked pixel and then fall into the copy loop with the mask inverted
(`d = (src & ~m) | (d & m)`), leaving the source pointer one byte short. Unreachable for 4-plane buffers
(no high nibbles); implement the copy path only. Callers (game_flow) loop the phase to complete a fade.

**0x91CF scroll_window(x, y, w, h, row_step, spr_off, spr_seg, spr_row)** — screen only. Write mode 1
copy of `h` rows of `w` bytes: `row(y + i*row_step/40) = row(y + (i+1)*row_step/40)` for i = 0..h-1
(`row_step = ±40`: +40 scrolls up with y the top row, −40 scrolls down with y the bottom row). Then if
`spr_seg != 0` the sprite row `(u8)spr_row` of each stored plane is written (replace, map mask =
`pm[k] & 0x0F`) at the final row position. Used by the credits scroller (0x0AB2).

**0x8B08 grab_screen(sx, sy, dx, dy, w, h)** — copies `w` bytes × `h` rows from the physical screen
(read map = plane, source row table = screen descriptor CS:5A86, source stride 40) into the current
target (all present planes). **0x8C1E grab_into_sprite(spr)** — unreferenced inverse (screen →
sprite's own planes at its stored x&~7, y).

**0x5150 create_buffer(w_bytes, h, plane_mask) → far ptr descriptor** — `size = w*h` (16-bit imul),
`pad = (-size) & 0xF`, allocates `(nplanes*(size+pad) + 0x10 >> 4) + 1` paragraphs through 0xA340;
header `w, h, 0,0,0,0, pm = present plane bits packed (1,2,4,8 order), pm[3] |= pad<<4`; plane k segment
= base + i*((size+pad)>>4) for the i-th present plane; descriptor appended at CS:[528E]
(`+(h+0x0C)*2` bytes, must stay below 0x5A60 else fatal "OUT OF ROW TABLE SPACE"); clip = whole buffer.
**0x79FF free_buffer(desc)** — pops the descriptor area by `(h+0x0C)*2` (must be the most recent) and
releases the memory via 0xA37E. **0x5128 select_target(desc)** — copies 12 words to CS:5A64, stores the
far pointer at CS:5A60. **0x50A1 set_clip(desc, x0, x1, y0, y1)** — writes the descriptor and, if it is
the current target (same plane-0 segment), the live copy.

Game buffers: DS:7F1A = 40×200×4 planes (page buffer for title/showroom screens, faded in with 0x768B);
DS:0890 = 40×112 (0x70) × 3 planes (road view, clip rows 0x13..0x6F, copied to the screen with 0x5DE2 so
screen plane 3 is untouched there); DS:089A and DS:08B2 sized from sprites DS:13B7 / DS:1393 (mirror and
steering wheel areas) — details in scene_render.

### 4.4 Mode set, palette, other adapters

* **0x4D96 video_init_ega**: GC mode reg (5) = 0, enable set/reset (1) = 0, bit mask (8) = FFh, function
  (3) = 0; `clear_screen(0)`; BIOS 0040:0010 equipment video bits = 10b (80×25 colour); INT 10h AX=000Dh;
  INT 10h AX=1002h ES:DX = DS:637C (identity 200-line palette). main (0x0010) then calls
  **0x4D84 set_palette(DS:00CC)** — the game palette: `00 01 02 03 04 05 07 16 00 10 06 12 13 14 11 17`
  overscan 00 → black, blue, green, cyan, red, magenta, light grey, yellow, black, dark grey, brown,
  light green, light cyan, light red, light blue, white. Nothing changes the palette afterwards.
* **0x50FE video_shutdown**: `clear_screen(0)`, equipment = colour, INT 10h AX=0003h, INT 10h AH=0Bh
  BX=0020h.
* **0x4D78** set border/background (INT 10h AH=0Bh BH=0 BL=arg) — unreferenced.
* **Hercules** (`TDEGA herc`): main compares argv[1] with "herc" (DS:0040); **0x8CEC herc_init**
  (equipment=mono, INT 10h mode 4, 6845 at 3B4h from DS:6642 `38 28 2D 0A 7F 06 64 70 02 02 06 07`,
  3BFh=3, 3B8h=0x8A, clears B800h) and **0x8D3C herc_shutdown** (table DS:664E, mode 7). The drawing
  code has no Hercules path in this range; not needed for the port. No CGA code in TDEGA (TDCGA.EXE is a
  separate build).

### 4.4a Road window copy: EGA register state and plane 3 (answer to scene_render Q1)

**Setup at stage start (0x1DC0)**
* 0x1DD8 `gfx_select_target(screen)`.
* 0x1DF0 `gfx_set_clip(screen, 0, 0x28, 0x13, 200)`.
* 0x1DFA `gfx_clear_clip(8)` on the screen, EGA full-width path:
  * GC idx 5 = 02h (write mode 2) at 0x75CC–0x75D5.
  * `stosb` of 08h at 0x75EF–0x75F3. The count is `imul dl` = 40 × (s8)181 = 0xF448 bytes, starting at row 19. That covers rows 19–199 plus invisible VRAM.
  * GC idx 5 = 00h at 0x75F5–0x75FE.
  * **The sequencer map mask is not written.** In write mode 2 every enabled plane gets bit k of the value 8: plane 3 = 1, planes 0–2 = 0.
  * Every screen routine that runs before a stage leaves the map mask with bit 3 set:
    * 0x4B98 leaves 0Fh (car select 0x098C starts with it).
    * 0x4941 leaves FFh.
    * 4-plane blits and the 7F1A dissolve leave 08h (last entry).
  * So plane 3 = **1** over rows 19–199. Confidence: likely. The mask is inherited, not set.
* 0x1E08 and 0x1E16: `blit_copy_own` of sprites DS:1383 and DS:13DB. They overwrite plane 3 only inside their own rectangles.

**Every frame**
* 0x3ACE selects the 40×112 3-plane buffer and sets its clip to rows 0x13–0x6F.
* `gfx_clear_clip(8)` runs on that RAM buffer. It has no plane 3, so planes 0–2 get 0.
* 0x3AF7 selects the screen, pokes clip y1 = 0x6F, and calls `blit_copy_clip_own` 0x5DE2 on the buffer.
  * The buffer header x,y is 0,0, so it copies source rows 19–110 to screen rows 19–110.
  * planemap = `01 02 04 00` (pad 0, since 40×112 = 0x1180).

**Register values during that copy (EGA path)**
| register | value | where |
|---|---|---|
| GC idx 3 (function) | 00h, replace | 0x5FF7–0x6001; set back to 00h at 0x640C–0x6415 |
| destination list | 3 entries, (read map 0, mask 1), (1, 2), (2, 4) | built at 0x6010–0x6051 from CS:5D5C/5D6C; stops at pm[3] low nibble 0 |
| constant planes | none | pm[0] and pm[1] high nibbles are 0 (tests at 0x6062, 0x60B6) |
| routine | shift-0 routine 0x63D2 | x & 7 = 0 |
| sequencer idx 2 (map mask) | 01h, 02h, 04h per row per entry | 0x63DE–0x63E7 |
| data write | `lodsb` / `stosb` | 0x63EB–0x63F0 |
| GC idx 5 (mode) | not written, 00h (write mode 0) | left by the last primitive; all restore 00h |
| GC idx 1 (enable set/reset) | not written, 00h | text 0x4C0C sets it, 0x4C34 restores 0 |
| GC idx 0 (set/reset) | not written | irrelevant because enable set/reset = 0 |
| GC idx 8 (bit mask) | not written, FFh | see note below |

**Result**
* The copy writes **only planes 0–2**. Plane 3 is never touched or forced, and it keeps the 1 from 0x1DFA.
* A buffer value v (0–7) is displayed as palette index **v | 8**. With the game palette DS:00CC:

| v | index | colour |
|---|---|---|
| 0 | 8 | black (the cleared buffer background) |
| 1 | 9 | dark grey |
| 2 | 10 | brown |
| 3 | 11 | light green |
| 4 | 12 | light cyan |
| 5 | 13 | light red |
| 6 | 14 | light blue |
| 7 | 15 | white |

* Exception: pixels inside the rectangles of DS:1383/DS:13DB, or of any later 4-plane screen blit that overlaps rows 19–110 (mirror buffer, wheel), keep that sprite's bit 3 until redrawn. scene_render should check those rectangles.
* **Port:** at stage start fill screen rows 19–199 with colour 8. Blit the road buffer with REPLACE on planes 0–2 only. Equivalently, show index `v | 8` wherever plane 3 is still 1.

**EGA state leaks to be aware of (screen only)**
* `gfx_draw_line` diagonal EGA path sets GC idx 8 = 00h at 0x88DB–0x88E4 and 0x89E3–0x89EC.
  * After that, every write-mode-0 screen blit is a no-op until `gfx_fill_rect` restores FFh (0x4ACA, 0x4B6F) or `gfx_init_ega` runs.
  * All known screen lines are horizontal or vertical: calibration grid 0x95F4 goes through fill_rect. The needles (0x35C6, 0x392C) are drawn into RAM buffers. So this never happens in practice.
* `gfx_clear_clip` partial-width EGA path returns through 0x757A without restoring GC idx 5 = 0, leaving write mode 2 set. Not reached by known callers: every screen clear is full width.

### 4.5 Input

#### 3.4 Keyboard/joystick poll for driving (0x5C24)

```c
u16 input_poll_drive(void) {
    if (!bios_key_available()) {
        u16 j = joy_read();                                  /* 0 if joystick disabled */
        u16 r = joy_dir_map[j & 0x0F];
        if (j & 0x30) r |= 0x10;
        return r;
    }
    u16 k; do k = bios_getkey(); while (bios_key_available());   /* keep LAST key, discard the rest */
    u8 a = k & 0xFF, sc = k >> 8;
    if (a == 'p' || a == 'P') goto pause;
    if (a == 'a' || a == 'A') return 0x11;                   /* up + fire */
    if (a == 'z' || a == 'Z') return 0x15;                   /* down + fire */
    if ((s8)a >= 0x20) {                                     /* signed: bytes 0x80-0xFF go to the table path (bug) */
        if (a >= '0' && a <= '9') return digit_dir_map[a - '0'];
        return 0xFF00 | a;                                   /* other printable: AH=FF, AL=ASCII */
    }
    if (a == 0) {                                            /* extended */
        int i = sc - 0x46;
        return (i > 0 && i < 12) ? ext_scan_dir_map[i] : 0;
    }
    switch (a) {                                             /* CS:5CC5 table */
    case 0x0A: /* Ctrl-J */ joy_enabled = 1;
               if (!joy_calibrated) { modal_pause = 1; joy_calibrate_screen(); modal_pause = 0; }
               break;
    case 0x0B: /* Ctrl-K */ joy_enabled = 0; break;
    case 0x10: /* Ctrl-P */ pause: modal_pause = 1; getkey_wait(); modal_pause = 0; break;
    case 0x11: /* Ctrl-Q */ snd_flags &= 3; break;
    case 0x13: /* Ctrl-S */ snd_flags |= 4; if (snd_flags & 2) snd_playing |= 2; break;
    case 0x1B: /* ESC    */ return 0xFFFF;
    }
    return 0xFF00 | sc;                                      /* AH=FF, AL=scan code */
}
```
Return encoding: `0x00dd` = direction dd (0 centre, 1 N, 2 NE, 3 E, 4 SE, 5 S, 6 SW, 7 W, 8 NW), `| 0x10` = fire. `0xFFxx` = non-control key (AL = ASCII or scan).
`0xFFFF` = ESC. The sim (0x3BF8) treats AL==0xFF as ESC/quit (DS:0929=1), AH==0xFF as a letter key, and in demo mode (DS:0084) any nonzero value as quit.
**Keyboard gives a direction only on polls where a keystroke is buffered.** Between typematic repeats the poll returns 0 (centre), or the joystick reading if enabled.

#### 3.5 Menu getkey, mode 4 (0x68F4) and 0x6846

```c
u16 getkey_kbd_joy_edge(void) {
    kbd_shift_btn = bios_shift_flags() & 3;
    if (bios_key_available()) return getkey_kbd_ctrl();
    u16 j = joy_read(), r;
    kbd_shift_btn |= j >> 4;
    r = (j >> 4) ? 0x000D : joy_menu_scan[j & 0x0F];
    if (r == joy_menu_last) return 0;
    joy_menu_last = r; return r;
}
u16 getkey_kbd_ctrl(void) {                  /* 0x6846 */
    u16 k; do k = bios_getkey(); while (bios_key_available());
    u8 a = k;
    if ((s8)a >= 0x20) return a;             /* ASCII, AH=0 */
    if (a == 0) return k;                    /* scan<<8 */
    switch (a) {                             /* CS:686B */
    case 0x0A: joy_enabled = 1; if (!joy_calibrated) joy_calibrate_screen(); return 0;  /* no modal_pause here */
    case 0x0B: joy_enabled = 0; return 0;
    case 0x10: modal_pause = 1; getkey_wait(); modal_pause = 0; return 0;
    case 0x11: snd_flags &= 3; return 0;
    case 0x13: snd_flags |= 4; if (snd_flags & 2) snd_playing |= 2; return 0;
    default:   return a;                     /* e.g. 0x0D Enter, 0x08 BS, 0x1B ESC */
    }
}
```
Mode 2 (0x680E) is identical except it is level-triggered (no 0x6420 compare) and returns 0 when `joy_read()==0`.

#### 3.6 Joystick read (0xA12F)

```c
u8 joy_read(void) {
    if (!joy_enabled) return 0;
    u8 res = 0;
    u8 pre = inb(0x201); joy_port_pre = pre;
    u8 wait = 3; joy_x = 0x50; joy_y = 0x50;
    u16 cx = 0;
    cli(); outb(0x201, pre);                      /* any write fires the one-shots */
    for (;;) {
        u8 b = (inb(0x201) & wait) ^ wait;        /* bits that have dropped to 0 */
        if (!b) { if (++cx >= 300) break; continue; }   /* 0x12C timeout; count is CPU-speed dependent */
        if (b & 1) { joy_x = cx; wait &= 2; if (!wait) break; if (!(b & 2)) continue; }
        if (b & 2) { joy_y = cx; wait &= 1; if (!wait) break; }
        /* NB: no ++cx on the iteration that catches an edge */
    }
    sti();
    /* ---- X (signed compares) ---- */
    s16 x = joy_x;
    if (x < (s16)xmin) { xmin = x; recalc_x: { u16 h = (u16)(xmax - xmin) >> 1, q = h >> 1;
                                                xhi = xmin + h + q; xlo = xhi - 2*q; }
                         x = joy_x; xover_cnt = 8; xover_min = 20000; }
    else if (x > (s16)xmax) {
        if (--xover_cnt == 0) { xmax = xover_min; goto recalc_x; }
        if (x < (s16)xover_min) xover_min = x;
    } else { xover_cnt = 8; xover_min = 20000; }
    if (x < (s16)xlo) res |= 8;                    /* left  */
    else if (x >= (s16)xhi) res |= 4;              /* right */
    /* ---- Y: identical, but min and threshold compares are UNSIGNED (jae/jb), max compares signed ---- */
    u16 y = joy_y;
    if (y < ymin) { ymin = y; recalc_y ...; y = joy_y; yover_cnt = 8; yover_min = 20000; }
    else if ((s16)y > (s16)ymax) { if (--yover_cnt == 0) { ymax = yover_min; goto recalc_y; }
                                   if ((s16)y < (s16)yover_min) yover_min = y; }
    else { yover_cnt = 8; yover_min = 20000; }
    if (y < ylo) res |= 1;                         /* up   */
    else if (y >= yhi) res |= 2;                   /* down */
    res |= ((inb(0x201) & joy_port_pre) & 0x30) ^ 0x30;   /* buttons A=0x10, B=0x20, active low; pressed in either sample */
    return res;
}
```
Calibration model: `min` follows the smallest sample immediately. `max` only moves after **8 consecutive** above-max samples, and then takes the smallest of them (spike filter).
Thresholds are the 25%/75% points of [min,max]. The screen at 0x95F4 asks the player to sweep the stick to every square so the extents converge.
Initial state is xmin=ymin=0x50, xmax=ymax=0, counters 0, so directions are garbage until swept.

#### 3.7 Calibration screen (0x95F4)
```c
if (input_poll_drive() & 0x10) { joy_enabled = 0; return; }   /* fire held on entry -> cancel */
save EGA screen (5150/5128/8B08); joy_calibrated = 1; draw text at y=0x23,0x2D,0x37,0xB9 + grid lines (85D5);
int prev = -1, r;
while (!((r = input_poll_drive()) & 0x10)) {
    if (r != prev && r >= 0 && r <= 9) {        /* signed; 0xFFxx ignored */
        for (i = 0; i < 9; i++) fill_rect(calib_sq_x[i], calib_sq_y[i], 0x20, 0x18, 0);   /* 0x4941 */
        fill_rect(calib_sq_x[r], calib_sq_y[r], 0x20, 0x18, 4);
        prev = r;
    }
}
restore screen; free; delay_ticks(100);
```

#### Every key / input code the game checks

| Code (as returned) | Meaning | Where checked |
|---|---|---|
| 'p' 'P' (0x70/0x50), Ctrl-P 0x10 | pause until any key/joystick event (music frozen, sim frozen) | 5C57, 5CC5[0x10]; 686B[0x10] |
| 'a' 'A' | → 0x11 (up+fire) | 5C5F |
| 'z' 'Z' | → 0x15 (down+fire) | 5C6F |
| '0'–'9' | numpad-style direction + fire: 0→10, 1→16, 2→15, 3→14, 4→17, 5→10, 6→13, 7→18, 8→11, 9→12 | 5C80 (DS:63C4) |
| Home/Up/PgUp/Left/Right/End/Down/PgDn (scan 47,48,49,4B,4D,4F,50,51, AL=0) | direction 8,1,2,7,3,6,5,4, no fire | 5CA7 (DS:63B8) |
| ESC 0x1B | 5C24 → 0xFFFF → sim sets DS:0929=1 (abort stage); menu_key → 1 (back) | 5CC5[0x1B]=5D56, 3C07; 95B0 |
| Ctrl-J 0x0A | enable joystick (+ calibration screen the first time) | 5D05, 68AB |
| Ctrl-K 0x0B | keyboard only (joystick off) | 5D26, 68BE |
| Ctrl-Q 0x11 | sound off | 5D40, 68D8 |
| Ctrl-S 0x13 | sound on | 5D2D, 68C5 |
| 'd' 'D' (AH=FF path) | toggle DS:08BE (sim; meaning TBD by simulation spec) | 3BB4 |
| 'o' 'O' (AH=FF path) | toggle DS:0921; when set, DS:0920 = gear node from DS:279B lookup of DS:0A78 (sim) | 3BC3 |
| any key in demo mode | quit demo stage | 3C00 |
| fire (0x10) / any unmapped key / ESC | continue ("press fire") | 1F7B, 38EB (wait release), 95F4 exit |
| Menu `menu_key()` results: 0x0D Enter or joystick fire | select | 02BF (0x193), 098C (0x560), name entry 92A8 |
| 0x4800 Up / 0x5000 Down (also joystick up/down) | menu move (Play again/new car 02BF; car select 098C next/prev) | 02BF, 098C |
| 0x4B00 Left / 0x4D00 Right | cursor in name entry | 92A8 |
| 0x5200 Ins | toggle insert mode | 92A8 |
| 0x5300 Del | delete char | 92A8 |
| 0x08 Backspace | delete left | 92A8 |
| 0x20..0x7A | typed character | 92A8 |
| -1 timeout | attract/demo transitions (DS:0084=1), auto-advance | 02BF, 03F4, 051B, 0792, 098C, 1D20, 92A8 |
| any key (≠ -1) | skip animation | 03F4, 051B, 0792, 1D20 |
| 'Y'/'y' (after 95D9 toupper) to "BACK TO DOS (Y or other key)?" | exit | 0x0218–0x0222 |
| any key (getkey_wait) | continue | 1B07 (gas station), A4C5 (score table), 0x0218 |


### 4.6 Timer and sound

Song data: TDSND.SND (FORMATS.md). Divisor table: tables/note_divisors.json; engine table DS:2077: tables/engine_divisors.json; effect streams: tables/sound_effects.json.

#### 3.1 Timer install / restore

```c
#define PIT_HZ 1193182
#define DIV_100HZ 0x2E97            /* 11927 -> 100.0404 Hz */

void timer_install_menu(void)  { chain_reload = 5;      chain_count = 5; chain_enable = 1; timer_install_common(DIV_100HZ); } /* 0x699E */
void timer_install_drive(void) { chain_reload = 0x7D00;                  chain_enable = 0; timer_install_common(DIV_100HZ); } /* 0x698C: chain_count untouched */
void timer_install_div(int unused, u16 div) {                          /* 0x69B6, dead */
    chain_reload = chain_count = (u16)(0x10000L / (s16)div);            /* idiv DX:AX=0x10000 by word */
    chain_enable = 1; timer_install_common(div);
}
static void timer_install_common(u16 div) {                            /* 0x69CF */
    outb(0x61, inb(0x61) & 0xFC);        /* speaker off */
    outb(0x43, 0xB6);                    /* ch2, lo/hi, mode 3 (speaker) — ch0 mode is NOT reprogrammed */
    outb(0x21, inb(0x21) | 0x03);        /* mask IRQ0+IRQ1 */
    snd_playing = 0;
    cli();
    if (IVT[8].off != 0x6A1F) old_int8.off = IVT[8].off;
    if (IVT[8].seg != CS) {              /* "cmp ax,0000" is a segment relocation (MZ reloc at 0x69FB) */
        old_int8.seg = IVT[8].seg;
        IVT[8] = CS:0x6A1F;
    }
    outb(0x21, inb(0x21) & 0xFC);        /* unmask IRQ0+IRQ1 unconditionally */
    sti();
    outb(0x40, div & 0xFF); outb(0x40, div >> 8);
}
void timer_restore(void) {                                             /* 0x694A */
    if (IVT[8].seg != CS || IVT[8].off != 0x6A1F) return;
    outb(0x21, inb(0x21) | 3); cli(); IVT[8] = old_int8; outb(0x21, inb(0x21) & 0xFC); sti();
    outb(0x40, 0); outb(0x40, 0);         /* 65536 -> 18.2 Hz */
    outb(0x61, inb(0x61) & 0xFC);
}
```

#### 3.2 Base timer ISR + song interpreter (0x6A1F)

```c
void interrupt timer_isr(void) {          /* entered with IF=0 */
    tick_count++;
    if (--chain_count <= 0) {             /* signed */
        chain_count = chain_reload;
        if (chain_enable) { IVT[8] = old_int8; int86(8); IVT[8] = CS:0x6A1F; } /* BIOS does its own EOI */
    }
    if (snd_playing) {
        if (modal_pause)                       { spk_off(); }
        else if (note_left != 0) {
            u16 old = note_left--;
            if (old == note_cut) spk_off();
        } else snd_fetch();
    }
    outb(0x20, 0x20);                     /* non-specific EOI (second one if BIOS was chained) */
}

static void snd_fetch(void) {             /* 0x6AA8 */
  for (;;) {
    u8 f = snd_flags;
    if (!(f & 4))            goto stop;                   /* sound disabled */
    if (!(f & snd_playing)) {                             /* current stream cancelled or ended */
        if (!(snd_flags & 2)) goto stop;
        snd_flags &= 6; snd_playing = 2;                  /* start loop stream from its beginning */
        snd_ptr = snd_loop_ptr; continue;
    }
    u8 op = mem[snd_ptr];
    if ((s8)op >= 0) {                                    /* note/rest event */
        note_left = rd16(snd_ptr + 1); snd_ptr.off += 3;
        if (op == 0) { note_cut = 0; spk_off(); return; }
        note_cut = snd_shift ? (note_left >> snd_shift) : 0;
        u16 d = note_div[op];                             /* DS:6452[op], op 1..0x7F */
        outb(0x42, d & 0xFF); outb(0x42, d >> 8);
        outb(0x61, inb(0x61) | 3);                        /* gate ch2 + speaker data on */
        return;
    }
    switch ((u8)-op) {                                    /* CS:6B42[-op]; no range check */
    case 1: /* FF */ goto end_of_stream;                  /* == the !(f & snd_playing) branch above */
    case 2: /* FE s */ snd_shift = mem[snd_ptr+1]; snd_ptr.off += 2; break;
    case 3: case 4: case 5: { int k = op==0xFD?0:op==0xFC?1:2;          /* FD/FC/FB n16 */
        loop_cnt[k] = rd16(snd_ptr+1); snd_ptr.off += 3; loop_start[k] = snd_ptr.off; break; }
    case 6: case 7: case 8: { int k = 0xFA - op;                        /* FA/F9/F8 */
        if (--loop_cnt[k] < 0) snd_ptr.off += 1;                        /* js */
        else { loop_end[k] = snd_ptr.off; snd_ptr.off = loop_start[k]; }
        break; }
    case 9: case 10: case 11: { int k = 0xF7 - op;                      /* F7/F6/F5 */
        if (loop_cnt[k] == 0) snd_ptr.off = loop_end[k];                /* jump to the FA/F9/F8 byte */
        else snd_ptr.off += 1;
        break; }
    }
    continue;
  end_of_stream:
    if (snd_flags & 2) { snd_flags &= 6; snd_playing = 2; snd_ptr = snd_loop_ptr; continue; }
  stop:
    snd_playing = 0; snd_flags &= 6; note_left = 0; spk_off(); return;
  }
}
```

Exact event semantics:
* Note n with duration d sounds on the fetch tick and stays sounding while `note_left` counts d..1.
  The event lasts **d+1 ticks**. With shift s>0 the speaker turns off on the tick where the pre-decrement value equals `d>>s`, which gives
  `d+1-(d>>s)` ticks on and `d>>s` ticks off. The exception is `d>>s == 0`: that never matches, so the note is legato.
  Shift 0 is legato. The initial shift is **3** (DS:643C = 3 at load). Rest: speaker off for d+1 ticks.
* Loop body with count n plays n+1 times. `F7` on the last pass jumps to the saved end marker, which then decrements to −1 and exits.
  If `F7` runs on the first pass with n=0, it jumps to a stale `loop_end` (original bug).
* Opcodes 0x80–0xF4 index past the jump table (undefined; not present in data).
* Pointers are seg:off with only the offset advancing. Streams must fit within 64 KB of their normalized segment (they do).
* **Priority**: `snd_play_oneshot` (0x8A3E) replaces the pointer immediately but **does not reset note_left**, so the currently sounding note finishes its count first.
  When a one-shot hits FF, the loop stream (if set) restarts **from its start**. A loop stream hitting FF restarts itself (infinite).
  `snd_set_loop` while something is playing only queues. `snd_stop_oneshot` / `snd_stop_all` take effect at the next fetch.
* Sound toggle: Ctrl-Q clears bit2, so at the next fetch the stream stops and the pointer is left at the un-fetched opcode. Ctrl-S sets bit2.
  If a loop is set (bit1) it also sets `snd_playing |= 2`, which resumes at the **stale pointer** (possibly inside the old one-shot stream, now treated as a loop).

Songs (TDSND.SND loaded by main via 0x78A5, names looked up with 0x6762): DS:8090=`sng1`, DS:78E8=`sng2`, DS:7906=`sng4`, DS:7B2A=`sng3`.
* `sng2`: 0x037A intro (ACCOLADE/TESTDRV logos), stopped at 0x03DE
* `sng4`: 0x098C car-select/attract loop, stopped at 0x0A3F
* `sng3`: 0x1482 high-score name entry, stopped 0x1626
* `sng1`: 0x1993 gas-station screen, stopped 0x1B2F

All four use 0x8A3E (one-shot); no loop stream is set in menus. Note range used: 22..70, so the patched slots 0x55–0x57 never collide.

In-game (driving):
* 0x48FD `snd_set_loop(DS:0B05)`: `FE 00 | 55 0003 | 56 0001 | FF`, i.e. 4 ticks of engine tone (slot 0x55) then 2 ticks of slot 0x56, looping (6-tick cycle).
  The divisor is re-read at each note fetch, so pitch updates are quantised to that cycle.
* 0x35E2 (per frame, when `(DS:80A4 & 8) && DS:0A05 != 0 && DS:186F <= DS:0A05-1`, i.e. radar detector alert, see simulation): `snd_play_oneshot(DS:0B0F)`: `FE 00 | 57 0001 | FF`,
  a 2-tick 1325.8 Hz beep, after which the engine loop restarts. It is retriggered every frame while the condition holds.
* 0x1DC0: crash (DS:0929≥3) → `snd_stop_all`, then after the crash sequence `snd_set_loop(DS:0B05)` again (0x1EB1). Stage end → `snd_stop_all` (0x1E80/0x1EFC).

#### 3.3 Driving ISR (0x3B1F), sound/timing part

```c
void interrupt drive_isr(void) {
    push all; pushf(); far_call(drive_old_int8);   /* = timer_isr 0x6A1F: tick, song, EOI */
    DS = ES = DGROUP;
    if (modal_pause || crash_state /*DS:0929*/ == 3) goto iret_;
    s16 r = rpm_disp, t = rpm;                      /* signed compares */
    if (r != t) {
        if (r < t) { r += 0x40; if (r >= t) r = t; }   /* jl keeps r */
        else       { r -= 0x40; if (r <= t) r = t; }
    }
    rpm_disp = r;
    note_div[0x55] = engine_div[((u16)r >> 5) & 0xFFFE];   /* word table DS:2077, index rpm>>6 */
    drive_tick++;
    if ((drive_tick & 7) != 0) goto iret_;
    DS:80A4++; if (DS:093C == 0) DS:80A4--;          /* stage clock advances only when 093C set */
    /* 0x3BEA: input_poll_drive() + keys + physics (0x3FE8...) — see simulation spec */
iret_:
    pop all; iret;                                  /* 0x4673 */
}
```
Engine tone: `engine_div[i]` = round(596591 / i) for i≥10 (**f = 2·i Hz = rpm_disp/32 Hz**, e.g. 800 rpm → 24 Hz, 6400 rpm → 200 Hz). i<10 = 0xFFFF.
151 entries (i ≤ 150, rpm < 9664). Slot 0x56: 0xFFFF (18.2 Hz thump) normally, reset on every road-unit advance (0x4017).
It becomes 0x08E8 = 523.3 Hz tyre squeal while `lateral ≥ car grip DS:2697` (0x40D5/0x40A7). It becomes 0x0474 = 1046.7 Hz on each sim tick while `DS:08F4` counts down (0x4269/0x426D),
set to 3 when a shift raises rpm by more than 2500 (0x3C3E) or to 0x12 at 0x3C88 (gear grind). The simulation agent should confirm the trigger meanings.

#### 3.8 Tick helpers
```c
u16 ticks_elapsed(u16 start) { u16 n = tick_count; return (n < start) ? start - n : n - start; }  /* wrap bug: after 0xFFFF wrap returns large → timeouts end early */
void set_deadline(u16 t) { deadline_start = tick_count; deadline_len = t; }
u16  getkey_until_deadline(void) { u16 k; do { if ((k = getkey())) return k; } while (ticks_elapsed(deadline_start) < deadline_len); return 0; }
int  menu_key(void) { int k = getkey_until_deadline(); return k == 0 ? -1 : k == 0x1B ? 1 : k; }
```


### 4.7 Resources and memory


* **Heap.** One big DOS memory block, obtained at startup by `mem_init` (0x8CC0): AH=48h for 100 paragraphs,
  then AH=4Ah with BX=0xA000 (this fails and returns the maximum size), then AH=4Ah again with that
  maximum. Its segment range is split in two:
  * **Low end, growing up:** the *archive cache*. `DS:7B24` (mem_low) is the next free segment.
    Up to 30 slots, 16 bytes each, at `DS:7D38`: `{char name[12]; u16 paras; u16 seg;}`.
  * **High end, growing down:** *buffers* (row tables / off-screen pages). `DS:7F18` (mem_high) is the
    lowest used segment. 8 slots, 4 bytes each, at `DS:7F1E`: `{u16 seg; u16 paras;}`.
  * Both are raw segments addressed as `seg:0000`. No malloc is involved, except the small 1 KB
    read buffer and the ~17 KB LZW table (these use the CRT near heap, `malloc` at 0xA730).
* **Files.** Two different styles:
  * `load_raw_archive` (0x78A5, used only for `tdsnd.snd`) calls int 21h directly (3Dh/3Fh/3Eh).
  * `load_packed_archive` (0x9A86, used for every `.PES`) goes through MSC `open`/`read`/`close`
    (0xA776/0xA93A/0xA4F8) with O_BINARY 0x8000.
  * SCORES and `.BIN` go through CRT stdio/io (they belong to the game_flow spec).
* **Archive in memory.** This is the decompressed archive from FORMATS.md. After loading, the u32 offset
  table is **relocated in place** into normalized far pointers. So the loader returns a far ptr to the
  archive, and `res_find` (0x6762) returns the far ptr of the resource (sprite header / song bytecode).
* **Lookup.** `res_find(archive, "name")` does a linear search over the 4-char names. It is
  case-sensitive (plain `cmpsb`). A short query name is **space-padded in place**, and a NUL in the archive
  name matches a space in the query. If nothing matches it is fatal: `"%-4.4s SHAPE OR SOUND NOT FOUND"`.
* **Cache semantics.** A loader first calls `cache_find(name)` (0xA280). If the file name (12 chars,
  exact case) is already in a slot, the loader returns that segment and does not reload. Allocation takes
  a `reserve` argument in paragraphs. If `mem_high - seg < paras + reserve`, it **evicts the newest cache
  entries** (LIFO) until the load fits. This is the only "free" for archives.
* **Errors.** Every error path calls `fatal(fmt, arg)` (0x94AB): restore text video mode (0x50FE),
  unhook the timer and silence the speaker (0x694A), `printf`, then `abort()`. That prints R6010
  "abnormal program termination" and exits with code 3. A few raw paths also do `int 20h`.



```c
/* ---------- memory ---------- */
void mem_init(void)                                                  /* 0x8CC0 */
{
    u16 seg = dos_alloc(0x64);            /* AH=48h, BX=100 paras (error not checked) */
    g_mem_low = g_mem_bot = seg;
    u16 max = 0xA000;
    dos_setblock(seg, &max);              /* AH=4Ah: fails, BX = largest possible */
    dos_setblock(seg, &max);              /* AH=4Ah again with that size */
    g_mem_high = g_mem_top = g_mem_bot + max;
}

typedef struct { char name[12]; u16 paras; u16 seg; } CacheSlot;     /* DS:7D38 x 30 */

u16 cache_find(const char *fname)          /* 0xA280; returns seg (DX), AX=0 */
{
    for (int i = 0; i < 30; i++) {
        CacheSlot *s = &g_cache[i];
        if (s->seg == 0) return 0;                 /* first empty slot ends the list */
        int j;
        for (j = 0; j < 12; j++) {
            char c = fname[j];
            if (c == 0) { if (s->name[j] == 0) return s->seg; else break; }
            if (s->name[j] != c) break;            /* case-sensitive */
        }
        if (j == 12) return s->seg;
    }
    return 0;
}

u16 cache_alloc(const char *fname, u16 paras, u16 reserve)   /* 0xA2BE; returns seg:0 */
{
    u16 need = paras + reserve;
    CacheSlot *s = g_cache;
    u16 seg = g_mem_low;
    int i;
    for (i = 0; i < 30; i++, s++) {
        u16 end = s->seg + s->paras;
        if (end == 0) break;                       /* free slot: seg = end of previous one */
        seg = end;
    }
    if (i == 30) { s--; seg = s->seg; g_mem_low = seg; }   /* all full: reuse the last slot */
    while ((u16)(g_mem_high - seg) < need) {       /* unsigned compare */
        s->seg = 0; s->paras = 0;                  /* evict */
        s--;
        if (s < g_cache) fatal("OUT OF MEMORY LOADING %s\n", fname);
        seg = s->seg;                              /* reuse the previous slot's start */
    }
    for (int j = 0; j < 12; j++) { s->name[j] = fname[j]; if (!fname[j]) break; }
    s->paras = paras;
    s->seg   = seg;
    g_mem_low = seg + paras;
    return seg;
}
/* Side effect: evicting slot k also discards every slot above it (they are zeroed, or overwritten later).
   The caller keeps far pointers, so a stale pointer into an evicted archive is possible (see Q2). */

u16 buf_alloc(u16 paras)                                             /* 0xA340 */
{
    int i;
    for (i = 0; i < 8; i++) if (g_bufs[i].seg == 0) break;
    if (i == 8) fatal("OUT OF MEMORY BUFFERS");
    u16 seg = g_mem_high - paras;
    if (seg <= g_mem_low) fatal("OUT OF BUFFER MEMORY");     /* unsigned */
    g_mem_high = seg;
    g_bufs[i].seg = seg; g_bufs[i].paras = paras;
    return seg;
}

void buf_free(u16 seg)                                               /* 0xA37E */
{
    int i;
    for (i = 0; i < 8; i++) if (g_bufs[i].seg == seg) break;
    if (i == 8) fatal("BUFFER NOT FOUND RELEASE ERROR");
    u16 end = g_bufs[i].paras + seg;
    if (end >= g_mem_high) g_mem_high = end;       /* only really reclaims when freed in LIFO order */
    g_bufs[i].seg = 0; g_bufs[i].paras = 0;
}

void gfx_free_buffer(Desc far *rt)                                 /* 0x79FF */
{
    g_rowpool_ptr -= (hdr(rt)->h + 0x0C) * 2;      /* CS:528E; header = (h+12) words */
    buf_free(rt->plane_seg[0]);                    /* word at +2 = first plane segment */
}

/* ---------- archive relocation (shared by 0x78A5 and 0x8A5B) ---------- */
/* archive at seg:0 : u32 total; u16 count; char name[4]*count; u32 off*count; data...  */
static void archive_relocate(u16 seg)
{
    u8 far *a = MK_FP(seg, 0);
    u16 count = rd16(a + 4);
    u16 tab   = 6 + count * 4;                 /* start of the offset table (near) */
    u16 data  = tab + count * 4;               /* end of table = offset base */
    for (u16 k = 0; k < count; k++) {
        u32 lin = rd32(a + tab + k*4) + data + ((u32)seg << 4);
        wr16(a + tab + k*4,     (u16)(lin & 0x0F));   /* offset */
        wr16(a + tab + k*4 + 2, (u16)(lin >> 4));     /* segment (normalized far ptr) */
    }
    /* count==0 still runs the body once (dec/jg loop): unused */
}

far ptr load_archive(const char *fname, u16 reserve)                  /* 0x8A5B */
{
    u16 seg = cache_find(fname);
    if (seg) return MK_FP(seg, 0);             /* already relocated */
    seg = FP_SEG(load_packed_archive(fname, reserve));
    archive_relocate(seg);
    return MK_FP(seg, 0);
}

far ptr load_raw_archive(const char *fname, u16 reserve)              /* 0x78A5 (tdsnd.snd) */
{
    u16 seg = cache_find(fname);
    if (seg) return MK_FP(seg, 0);
    int fd; u32 size;
    if (dos_open(fname, 0, &fd) || dos_read(fd, &size, 4) != 4 /*also: 0 bytes = err*/ || dos_close(fd))
        { fatal("%s FILE ERROR\\n", fname); int20(); }
    u16 paras = (u16)(size >> 4) + 1;
    seg = cache_alloc(fname, paras, reserve);
    if (dos_open(fname, 0, &fd)) goto err;
    u16 chunks = (u16)(size >> 14);          /* (size<<2) high word */
    u16 rest   = (u16)size;
    u16 ds = seg;
    while ((s16)--chunks >= 0) {             /* full 16 KB chunks */
        if (dos_read(fd, MK_FP(ds, 0), 0x4000) err) goto err;
        rest -= 0x4000; ds += 0x400;
    }
    if (dos_read(fd, MK_FP(ds, 0), rest) err || dos_close(fd)) goto err;
    archive_relocate(seg);
    return MK_FP(seg, 0);
}

far ptr load_packed_archive(const char *fname, u16 reserve)           /* 0x9A86 */
{
    u16 seg = cache_find(fname);
    if (seg) return MK_FP(seg, 0);
    g_pack_fd = open(fname, 0x8000 /*O_BINARY|O_RDONLY*/);
    if (g_pack_fd == 0) fatal("%s FILE OPEN ERROR\n", fname);   /* NB: tests ==0, not -1 */
    struct { char magic[4]; u32 packed; u32 unpacked; u16 method; u16 crc; } h;
    if (read(g_pack_fd, &h, 0x10) != 0x10) fatal("%s FILE READ ERROR\n", fname);
    u32 paras = (h.unpacked >> 4) + 1;       /* _aNlshr, cl=4 */
    seg = cache_alloc(fname, (u16)paras, reserve);
    g_pack_inbuf = malloc(0x400);
    if (!g_pack_inbuf) fatal("PACK BUFFER ALLOCATE ERRROR");
    g_in_count = 0; g_out_count = 0;
    g_packed_left   = h.packed;
    g_unpacked_len  = h.unpacked;
    g_pack_outptr   = MK_FP(seg, 0);
    g_pack_inptr    = g_pack_inbuf;
    g_pack_inpos    = 0x400;                 /* force refill */
    g_rle_state     = 0;
    int c;
    switch (h.method) {
    case 2: while ((c = pack_getc()) != -1) pack_putc(c); break;            /* stored */
    case 3: while ((c = pack_getc()) != -1) rle90_out(c); break;            /* RLE90 only */
    case 4: huff_read_tree(); while ((c = huff_decode()) != -1) rle90_out(c); break;
    case 8: lzw_decompress(); break;                                         /* -> rle90_out */
    default: fatal("UNKNOWN PACK MODE %d\n", h.method);
    }
    close(g_pack_fd);
    free(g_pack_inbuf);
    if (g_out_count != g_unpacked_len) fatal("%x UNPACKED SIZE ERROR\n", g_out_count);  /* CRC is NOT checked */
    return MK_FP(seg, 0);
}

int pack_getc(void)                                                  /* 0x9D64 */
{
    g_in_count++;
    if (g_packed_left == 0) return -1;
    g_packed_left--;
    if (g_pack_inpos >= 0x400) { read(g_pack_fd, g_pack_inbuf, 0x400); g_pack_inpos = 0; g_pack_inptr = g_pack_inbuf; }
    g_pack_inpos++;
    return *g_pack_inptr++;
}

void pack_putc(u8 c)                                                 /* 0x9DD3 */
{
    g_out_count++;
    if (g_out_count <= g_unpacked_len) { *g_pack_outptr = c; huge_inc(&g_pack_outptr); /* off wrap: seg += 0x1000 */ }
}

/* ---------- lookup ---------- */
far ptr res_find(far ptr arc, char *name)                             /* 0x6762 */
{
    for (int i = 0; i < 4; i++) if (name[i] == 0) { for (; i < 4; i++) name[i] = ' '; break; }  /* modifies caller's string */
    u16 n = rd16(arc + 4);                       /* dec/jge: n+1 iterations; reads one past the table */
    u8 far *e = arc + 6;
    for (s16 k = n; k >= 0; k--, e += 4) {
        int j;
        for (j = 0; j < 4; j++) {
            if (e[j] == name[j]) continue;
            if (e[j] == 0 && name[j] == ' ') { j = 4; break; }   /* NUL in archive name matches remaining space */
            break;
        }
        if (j == 4) return rd_farptr(e + rd16(arc + 4) * 4);   /* entry + count*4 = relocated pointer */
    }
    fatal("%-4.4s SHAPE OR SOUND NOT FOUND\\n", name); int20();
}
```
Lookup note: the compare loop is `cmpsb` over 4 bytes. A mismatch is accepted only when the archive byte
just compared is 0 and the query byte is 0x20. Once a NUL/space pair matches, the rest is accepted without
comparing. The loop runs `count+1` times, one extra entry past the table; that entry never matches in
practice. **Port:** `strncmp` on space/NUL-normalised 4-char names, case-sensitive, returning the
resource index/pointer.

```c
void res_find_list(far ptr arc, const char *names, far ptr *out)    /* 0x94C7 */
{ for (int i = 0; *names; names += 4) out[i++] = res_find(arc, (char*)names); }

void fatal(const char *fmt, void *arg)                                 /* 0x94AB */
{ gfx_shutdown(); /*0x50FE: BIOS equip=80x25 colour, int10 mode*/  timer_restore(); /*0x694A*/
  printf(fmt, arg); abort(); }

void draw_text_centered(char *s, int y) { gfx_draw_text(s, 0xA0 - strlen(s) * 4, y); }   /* 0x9507 */
```


### 4.8 Copy protection (brief)


* Entry: saves SP at 0000:0010, writes 0x0201 at 0000:0012, sets DS=ES=CS (so `DS:8DC0` etc. are code-segment
  bytes). Checks DOS version (AH=30h). Tries the **hard-disk install** path first: int 13h reads the MBR
  from DL=80h, requires 0xAA55, scans the partition table for type 1/4 and reads sector(s) on that
  partition, comparing 4 words with the signature at 0x8DB8/0x8DB0.
* **Floppy** path: int 11h gives the drive count (DS:8DC0). For each drive, int 13h AH=04 (verify) and
  AH=02/09 reads of sector IDs 0xF1/0xDE on track 39 (CX=0x2707/0x2708). It expects status bit 0x10
  (CRC error), then compares 16 words of the read sector with each other, and the first 4 words with
  0x8DB0.
* Exit: SP restored from 0000:0010. Returns **AX = 0 when the check passes** (0x8F51) and
  **AX = 0xFEF6 when it fails** (0x8F61). No DGROUP global holds the result: it is only a return value.
* Consumers:
  1. `main` 0x0010, first statement: `if (cp_check() != 0) return 0;` The game **exits to DOS silently**.
  2. `main` back-to-DOS loop: after each game cycle, `if (cp_check() != 0) break;` quits.
  3. 0x037A (title/intro): `if (cp_check() != 0) local_4 = 1;` behaves as "quit".
* **Port:** replace `cp_check()` with `return 0`. Also drop the 0000:0010 IVT write.
* **Launcher gate (not protection, but required):** `main` only runs the game when
  `strcmp(argv[1], "94857102387604294775") == 0` (DS:00DE). TD.EXE passes this string. `strcmp(argv[1],"herc")==0`
  selects Hercules (0x8CEC, DS:008A=1). The port should skip both.
* 0x91CF–0x92A8 is **not** protection. It is `vram_scroll_and_blit`: GC mode register (0x3CE idx 5) = write
  mode 1, sequencer map mask (0x3C4 idx 2) = 0xF. Then `rep movsb` inside A000h copies `h` rows of
  `w` bytes from `dst+src_delta` (for example 0x28 = one row down at 40 bytes/row), which scrolls up.
  It restores write mode 0. If `draw != 0`, it copies row `row` of each stored sprite plane
  (plane mask = planemap low nibble) into the bottom line. It is used by 0x0AB2 (credits/logo scroll,
  `91CF(0,0,0x28,0x57,0x28,0,0,0)` in a loop). Row start offsets come from CS:5A6E. See 4.3.
* 0x92A8 is the high-score name input line editor (caller 0x1482).


### 4.9 C runtime

Identification only, see 2.4. Nothing in the runtime needs a pseudocode port except `rand` (formula in 2.4).

## 5. Hardware / DOS dependencies and SDL3 replacements

| Original | Where | SDL3 / portable replacement |
|---|---|---|
| EGA planar video memory A000h, 4 planes × 8000 bytes | all gfx | 4 `u8` plane arrays of 40×200 (+slack); compose to a 320×200 index image each present, map through the 16-entry palette into an `SDL_Texture` (streaming XRGB8888), `SDL_RenderTexture` with `SDL_SetRenderLogicalPresentation(320,200, LETTERBOX)` (optionally 4:3 by drawing to 320×240) |
| Sequencer 3C4h idx 2 map mask; GC 3CEh idx 0/1 set-reset, 3 function (00/08/10/18h), 4 read map, 5 mode (write mode 0/1/2), 8 bit mask | blitters, fill, text, line, dissolve, scroll | Implement the op in software on the plane arrays (REPLACE/AND/OR/XOR per plane). Emulate the EGA path literally only where results differ (XOR edge bytes, 0x74F4 quirks) |
| Off-screen RAM planes (segments from 0x5150) | buffers | Same plane model with absent planes = NULL (writes skipped) |
| INT 10h AX=000Dh / 0003h / AH=0Bh | 0x4D96, 0x50FE, 0x4D78 | Create window/renderer at start, destroy at exit |
| INT 10h AX=1002h palette | 0x4D84 | Keep a 16-entry RGB table (ega_palettes.json, DS:00CC decoded) |
| BIOS 0040:0010 equipment word | 0x4D96, 0x50FE, 0x8CEC | Drop |
| Hercules 3B4h/3B8h/3BFh, B800h | 0x8CEC, 0x8D3C | Drop (no Hercules in the port) |
| No 3DAh retrace wait / no CRTC start address | – | Present after each copy to the screen or once per main-loop iteration; use VSync or the 100 Hz tick for pacing (see Timing) |
| PIT ch0 divisor 0x2E97 (ports 40h/43h) | 0x69CF, 0x694A | Fixed-step 100.0404 Hz tick (9.996 ms) from an accumulator on `SDL_GetTicksNS()` in the main loop |
| INT 8 hook + BIOS chaining every 5 ticks | 0x69CF, 0x6A1F | Drop chaining. Run `timer_isr` body (tick_count++, song step) per tick |
| INT 8 = 0x3B1F during driving | 0x4908, 0x1F29 | Call `drive_tick()` right after each base tick in the driving state: sound step, rpm slew + engine divisor, then every 8th tick input + physics |
| INT 0 → DGROUP:1423 (AX=0xFFFF, skip `div reg`) | 0x4908 | Helper for every 16-bit div/idiv in sim/renderer: divisor 0 or quotient overflow → AX = 0xFFFF |
| PIT ch2 (42h, 43h=B6h) + port 61h bits 0–1 | ISR | `SDL_AudioStream` (e.g. 44100 Hz mono S16) fed from a generator holding `div` and `on`; square wave f = 1193182/div, phase-continuous across divisor changes; div 0xFFFF ≈ 18.2 Hz. Optional one-pole low-pass for speaker colour |
| INT 16h AH=00h/01h (drain, keep last key), AH=02h shift flags | 0x5C24, 0x6846, 0x67F8, 0x6939 | Queue of BIOS-style keycodes (AH=XT scan, AL=ASCII incl. Ctrl codes) filled from `SDL_EVENT_KEY_DOWN` **including repeat events**; `SDL_GetModState()` for shifts. Optional "held key" mode via `SDL_GetKeyboardState` (not faithful) |
| Port 201h joystick one-shots + buttons | 0xA12F | `SDL_Gamepad` left stick/D-pad + A/B: left `x < −16384`, right `x ≥ 16384`, up `y < −16384`, down `y ≥ 16384`, A=0x10, B=0x20. Faithful option: synthesize counts and keep the adaptive logic |
| PIC 20h EOI, 21h masks | ISR, 0x69CF | Drop |
| INT 21h 48h/4Ah memory, segment arithmetic, huge pointers | 0x8CC0, 0xA2BE, 0xA340, 0x9DD3 | `malloc` per archive/buffer; keep a name-keyed cache so repeated loads return the same object; no eviction needed |
| INT 21h 3Dh/3Fh/3Eh; MSC open/read/close | 0x78A5, 0x9A86 | `SDL_LoadFile` / `SDL_IOFromFile`; case-insensitive file-name match on case-sensitive filesystems |
| Archive offset table relocated into far pointers | 0x8A5B | Array of `u8*` = base + data_start + off[k] |
| `fatal` (text mode, printf, abort) | 0x94AB | `SDL_ShowSimpleMessageBox` + `SDL_Quit` + `exit(3)` |
| INT 13h / INT 11h / IVT writes (protection) | 0x8DC7 | Remove; `copy_protection_check()` returns 0 |
| argv[1] launcher key "94857102387604294775" (DS:00DE), "herc" | main | Skip |
| MSC runtime | 0xA4E3–0xC99F | Host libc; `rand/srand` bit-exact; long helpers → native `int32_t` (`_aNldiv` truncates toward zero, `_aNlshr` arithmetic) |

## 6. Timing

* **Base tick** 1193182 / 11927 = **100.0404 Hz**, installed at start (`timer_install_menu`), re-installed
  after each stage, restored to 18.2 Hz only on exit/fatal.
* **Per tick (ISR)**: `tick_count++`; at most one song event fetch (any number of control opcodes) and the
  note cut check; menus additionally call the BIOS INT 8 every 5 ticks (so the DOS clock runs ~10% fast in
  menus and stops while driving — irrelevant for the port).
* **Driving**: per tick the drive ISR slews `rpm_disp` by ±0x40 toward rpm and writes the engine divisor;
  **every 8th tick (12.505 Hz)** it polls input (INT 16h/joystick) and runs the whole physics/AI step inside
  the interrupt. Rendering (0x1DC0 loop) runs free in the foreground as fast as the CPU allows and simply
  reads the simulation state — there is no frame limiter or retrace sync, so the render rate is
  CPU-dependent but game speed is not. Port: drive the 100 Hz accumulator for sound + sim; render once
  per host frame (VSync) from the latest state.
* Sound pitch in driving is quantised to the 6-tick engine loop (4 ticks slot 0x55 + 2 ticks slot 0x56).
  `snd_play_oneshot` lets the current note count finish first.
* **Menus/screens**: all waits are tick-based busy loops (`set_deadline` + `menu_key`, `delay_ticks`):
  values 1, 10, 100, 400, 1000, 2000, 12000 ticks. Dissolve fades: 8 calls of `gfx_dissolve` with phase 0..7. 0x03F4/0x051B do
  `set_deadline(1); gfx_dissolve(); menu_key()` (≥ 1 tick per phase, a key aborts the screen); 0x1993 does
  `set_deadline(10); gfx_dissolve()` with **no wait**, so that fade runs at drawing speed (reproduce with a
  per-phase present, optionally capped).
* Keyboard directions exist only on polls where a keystroke is buffered (typematic rate), so keyboard
  steering is rate-limited by the BIOS repeat (≈10.9 cps default, 500 ms delay) sampled at 12.5 Hz.
* `tick_count` wraps every 655.36 s; `ticks_elapsed` uses an absolute difference, so a timeout spanning the
  wrap ends early (keep or fix).
* Joystick reads are CPU-speed dependent (300-iteration timeout) — irrelevant with SDL_Gamepad.

## 7. Open questions

1. **Planemap list with a repeated colour bit** — RAM path processes destinations last-to-first, EGA path
   first-to-last. No shipped sprite repeats a bit, but runtime buffers are never passed with such maps
   either; low risk.
2. **EGA-only quirks reachability**: XOR blits on the screen with `x & 7 != 0` (0x7E7C is called right
   after selecting the screen at 0x2715 in scene_render; its sprite x is `&~3`, so shift 4 is possible).
   The stage-start screen clear is answered in 4.4a. It relies on an **inherited** map mask containing bit 3,
   traced as far as the screens preceding 0x1030 (confidence likely). The mirror/wheel rectangles that
   may overwrite plane 3 inside the road window are for scene_render to confirm.
3. **Left-clip carry bug** in RAM OR/AND/XOR clipped tables (shift 1–3) — cosmetic single-column
   artefact at the clip edge; decide whether to reproduce.
4. `gfx_draw_line` y-major skip bug (x −= 15.0003 per skipped row) and RAM-target plots ignoring the colour
   (always 15): confirm the gauge needle targets (0x35C6/0x392C) and whether lines ever start outside
   the clip (needles probably never do).
5. Keyboard steering only on typematic repeats: decide faithful vs "held key" mode (simulation spec to
   confirm how a direction present on one 12.5 Hz tick and absent on the next is used).
6. Divide-error hook assumes 2-byte `div reg` instructions; which divides can overflow must be enumerated
   in simulation/scene_render.
7. `snd_on`/`snd_off`/`snd_oneshot_active`, `getkey_timeout`, `timer_install_div`, getkey mode 2,
   `grab_into_sprite_hot/own`, `gfx_set_border`, `mem_debug_dump` have no callers found (dead code or
   called through pointers not traced).
8. Ctrl-S after Ctrl-Q resumes the loop stream at a stale pointer (possibly inside a finished one-shot
   stream); faithful port reproduces a short glitch.
9. Cache eviction can invalidate far pointers still held by the game (archives reloaded per stage);
   irrelevant if the port keeps all archives loaded.
10. Extended ASCII keystrokes (AL ≥ 0x80) index past the control jump table in 0x5C24/0x6846 (crash in the
    original); the port should ignore them.
11. Hercules path in TDEGA: only mode set/restore were found in this range; how (or whether) the planar
    renderer outputs to a Hercules card was not traced (not needed for the port).
