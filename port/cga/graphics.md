# TDCGA graphics layer (TDCGA.EXE image 0x4857–0x83D6)

Port: `tdport/src/platform/gfx_cga.c`, which implements the `gfx.h` API. Addresses are TDCGA image
offsets (CS offset = image offset). DS = image 0xA8A0. The TDEGA equivalent is `port/spec/platform.md` §4.
Everything below was read from the disassembly. The blitters, fills, clear_clip, grabs, text and lines
were also checked against a pixel-level model and the `tools/tdres.py` sprite PNGs, using a scratch
harness built on the port code.

## 1. Model

TDCGA keeps TDEGA's target model: 12-word descriptors in code-segment memory, a live copy, row tables,
and clip rectangles in byte columns. Every routine uses only `plane_seg[0]`.

* **A target is one 2-bits-per-pixel bitmap.** Each byte holds 4 pixels, MSB first:
  pixel = `(byte >> (6 - 2*i)) & 3`. A 320-pixel row is 80 bytes.
* **The screen has no special code path.** It is simply the target whose segment is B800h. Its row
  table interlaces the two CGA banks:
  * row 2k → B800:0000 + 80k
  * row 2k+1 → B800:2000 + 80k
* **Every primitive locates rows through the current row table**, including the per-row loops. The
  `stride` field is never read.
* **Sprites** use the same 16-byte header as TDEGA: `w_bytes, h, hot_x, hot_y, x, y`, then 4 bytes.
  * TDCGA never reads the last 4 bytes (the "planemap").
  * The header is followed by `h` rows of `w` bytes. There is no per-plane block and no padding.
* **An off-screen buffer is a sprite.** 0x4EA5 allocates a 16-byte header plus `w*h` bytes, and its
  descriptor rows are `0x10 + y*w`.

### Code-segment state

| CS | Contents |
|---|---|
| 4F61 | Pool bump pointer, initially 4F63. The descriptor pool is CS:4F63..5732; create_buffer fails when the new top is ≥ 5733 (DS:634C "OUT OF ROW TABLE SPACE"). |
| 5734 / 5736 | Far pointer to the selected descriptor, stored **segment first** (TDEGA 5A60 is off, 5A62 is seg). 5734 is relocated. |
| 5738..574F | Live copy of the selected descriptor: +00 hdr_off (5738), +02 plane_seg[0] (573A), +04..+08 unused planes, +0A rowtab (5742), +0C clip_x0 (5744), +0E clip_x1 (5746), +10 clip_y0 (5748), +12 clip_y1 (574A), +14 stride (574C), +16 pad. |
| 5750..5767 | Screen descriptor: `0000 B800 0000 0000 0000 5768 0000 0050 0000 00C8 0050 0000`. Clip is 0..80 bytes × 0..200 rows. |
| 5768..58F7 | Screen row table: `0000 2000 0050 2050 00A0 …` |
| 6338 | Dissolve row order `0B 05 08 02 0A 04 07 01 09 03 06 00` |
| 6344 | Dissolve bit masks `01 08 40 02 10 80 04 20` |
| 6D87 / 6D8B / 6D8F / 6D93 | Line tables: first-byte masks `FF 3F 0F 03`, pixels in the first byte `04 03 02 01`, end masks `00 C0 F0 FC`, pixel masks `C0 30 0C 03` |
| 7FA6 | draw_glyph sprite table: idx 0–6 → CS:7FC6 (2×8, underline), idx 7–15 → CS:7FE6 (2×8, block) |

### DGROUP data

| DS | Contents |
|---|---|
| 633C / 6340 | fill_rect masks: left `00 3F 0F 03`, right `00 C0 F0 FC` |
| 6344 | Text colour → pattern word: `0000 5555 AAAA FFFF` |
| 661C / 6628 | Hercules graphics CRTC `38 28 2D 0A 7F 06 64 70 02 02 06 07`; MDA text CRTC `61 50 52 0F 19 06 19 19 02 0D 0B 0C` |
| 66E8 | 256 words: font byte widened to 16 bits, every bit doubled |

Text globals sit at the EGA offsets minus 26h:

| DS | Field | Initial value |
|---|---|---|
| 68E8 | fg | 3 |
| 68EA | bg | 0 |
| 68EC | margin_x | |
| 68EE / 68F0 | x / y | |
| 68F4 | glyph_h | 8 |
| 68F6 | font (near pointer) | 6CEE |
| 68FA | adv_x | 8 |
| 68FC | adv_y | 8 |
| 68FE | enabled | 1 |

Target save area: DS:6986 (24 words).

## 2. Function table

| CGA | Port name | EGA | Notes |
|---|---|---|---|
| 4857 | gfx_fill_rect / gfx_fill_rect_pat | 4941 | Takes a 16-bit **pattern word**. Unclipped. See §3. |
| 4AD8 | gfx_clear_screen / gfx_clear_screen_pat | 4B98 | `rep stosw` FA0h × pattern at B800:0000 and B800:2000. Always the screen. |
| 4AF7 | gfx_draw_text | 4BD0 | Sets x/y, then falls into 4B0E. |
| 4B0E | gfx_draw_text_at_cursor | 4BE7 | Unreferenced |
| 4BC2 | — | 4D78 | INT 10h AH=0Bh BH=0 (background). `push bp` without `mov bp,sp` reads the wrong argument. Unreferenced; not ported. |
| 4BCE | — | (4D84) | INT 10h AH=0Bh BH=1 (CGA palette), same BP bug. Unreferenced; not ported. There is no `gfx_set_palette`. |
| 4BDA | gfx_init_ega | 4D96 | CGA mode 4 init, see §5 |
| 4C0C / 4C30 / 4C4E | blit_or_clip_hot/raw/own | 4DF1.. | 4C30 and 4C4E are unreferenced |
| 4DF6 | gfx_set_clip | 50A1 | Also updates the live copy if `desc+2 == CS:573A` |
| 4E53 | gfx_shutdown | 50FE | Mode 3. Same BP-as-pattern clear bug as 4BDA. |
| 4E7D | gfx_select_target | 5128 | |
| 4EA5 | gfx_create_buffer | 5150 | **Reads only (w, h).** plane_mask is ignored. Header planemap, desc+04..+08 and +16 are not written. |
| 5A30 / 5A54 / 5A72 | blit_copy_clip_hot/raw/own | 5D84.. | 5A54 is also used where TDEGA calls gfx_scroll_window |
| 6178 | gfx_set_text_colours(fg, bg) | 6C85 | Colour indices 0–3 |
| 6189 / 61AD / 61CB | blit_copy_hot/raw/own | 6CBE.. | |
| 62DC | gfx_set_text_cursor | 74E3 | Unreferenced |
| 62ED | gfx_clear_clip / gfx_clear_clip_pat | 74F4 | Takes a pattern word. See §3. |
| 634C | gfx_dissolve | 768B | Works on the current target, see §3 |
| 6599 | gfx_free_buffer | 79FF | Returns with SI and DI swapped (harmless, see the code) |
| 65D1 / 65F5 / 6613 | blit_or_hot/raw/own | 7A37.. | |
| 6717 / 673B / 6759 | blit_and_hot/raw/own | 7C3B.. | |
| 6865 / 6889 / 68A7 | blit_xor_hot/raw/own | 7E54.. | |
| 69AA / 69CE / 69EC | blit_xor_clip_hot/raw/own | 8058.. | Unreferenced |
| 6B94 / 6BB8 / 6BD6 | blit_and_clip_hot/raw/own | 8308.. | |
| 6D97 | gfx_draw_line | 85D5 | |
| 72B0 | gfx_grab_screen | 8B08 | Source is B800h through the screen row table (CS:575A) |
| 733C / 7360 / 737E | grab_into_sprite_hot/raw/own | 8BDC.. | Source is the **current target**. Only raw is referenced and ported. |
| 7587 | gfx_herc_init | 8CEC | |
| 75D7 | gfx_herc_shutdown | 8D3C | |
| 7CC9 | draw_text_centered | 9507 | `x = 0xA0 - strlen*4` |
| 7CF2 | draw_rect_outline | 9530 | |
| 8006 | draw_glyph | 9A69 | |
| 82AB / 82BF | gfx_target_save / restore | A3B7 / A3CB | |
| 83CD | (gfx_get_target_ptr) | A4D9 | Returns DX:AX = CS:5734:CS:5736. Only used by the memory debug dump; not ported. |

Absent from TDCGA:

* `gfx_set_palette` (4BCE is a different, unreferenced routine).
* `gfx_scroll_window`: the credits scroller uses 5A54.
* The EGA rect helpers and the EGA register paths.

## 3. Semantics

### fill_rect (4857)

`(x, y, w, h, u16 pat)` fills pixels `[x, x+w) × [y, y+h)` with no clipping.

* Byte column = `x >> 2`.
* Even rows use the **high** pattern byte, odd rows the **low** byte.
* Partial edge bytes keep the destination pixels outside the rectangle.
* The asm has six loop shapes: one byte, left+mid, left+mid+right, left+right, mid+right, mid. Some
  count rows with `loop` (h = 0 means 65536 rows) and others with `dec; jg`. The port keeps each one.

### clear_clip (62ED)

`(u16 pat)` fills the clip rectangle byte by byte.

* The row parity is **reversed** relative to fill_rect: even rows use the **low** byte.
* It does not special-case the full width and has none of the TDEGA screen-path quirks.

### Text (4B0E)

Nothing happens unless DS:68FE == 1. For each character:

1. Look up `glyph = DS:[font + ch*2]`.
   * If the pointer is 0 and the character is CR or LF: `x = margin`, `y += adv_y`.
   * If the pointer is 0 otherwise: skip the character.
2. For each of `glyph_h` rows, widen the font byte through DS:66E8 into word `e`.
3. Compute `v = (e & pat[fg]) | (~e & pat[bg])`.
4. Store `hi(v)`, then `lo(v)`, at `row(y + i) + (x >> 2)`.
5. After the glyph, `x += adv_x`.

Result: each font bit becomes one CGA pixel of colour fg or bg, and a character is 8 pixels wide.
There is no clipping.

### Blitters

In all four families, `shift = px & 3` pixels, which is `2*shift` bits.

**Clipped families** (4C0C OR, 5A30 COPY, 69AA XOR, 6B94 AND):

* The clip code is the same as TDEGA's, with byte columns of 4 pixels:
  * `col = px sar 2`.
  * Touching the right clip (`col + w == x1`) counts as clipped.
  * The left-clipped path never checks the right edge.
  * A top clip skips `(u8)(rows skipped) * (u8)w` source bytes.
* The `edge` value differs from TDEGA:
  * `edge = 1` when the sprite is not clipped horizontally.
  * `edge = 0` when the right edge is clipped.
  * `edge = 2` when the left edge is clipped. This is a plain `mov`, so bit 0 is cleared (TDEGA sets it to 3).

**Unclipped families** (6189 COPY, 65D1 OR, 6717 AND, 6865 XOR): the aligned case is a plain row copy
(or combine). Shifted rows always write the carry byte.

Each shifted row, per routine:

1. **Initial carry `dh`:**
   * COPY: the destination's left pixels (`d & ~(FF >> 2n)`). When left-clipped, the spill of
     `s[-1] << (8-2n)` instead, which is correct.
   * OR, XOR: 0. When left-clipped, the pixels of the clipped source column that fall into the first
     visible byte are **dropped**; the destination is kept there.
   * AND: the keep mask `~(FF >> 2n)`, even when left-clipped, so those pixels also keep the destination.
2. **Row loop:** `al = s >> 2n | dh; dh = s << (8-2n)`. Then COPY stores `al`; OR/AND/XOR combine it
   into the destination.
3. **Final carry byte:**
   * Unclipped routines: always written.
   * Clipped routines, shift 1–2: written only if `edge & 1`. A left-clipped sprite therefore loses its
     last `n` pixels.
   * Clipped routines, shift 3: the test is `edge != 0`, so a left-clipped sprite does get the byte.
   * Clipped XOR, shift 3 (6B84): the byte is XORed with **AL** (the last written byte) instead of DH.
4. **Carry-byte operation:** COPY `(d & (FF >> 2n)) | dh`; OR `d | dh`; AND `d & (dh | (FF >> 2n))`;
   XOR `d ^ dh`.

**Position modes:**

* hot: `(x - hot_x, y - hot_y)`.
* raw: `(x, y)`.
* own: header `(x, y)`. The unclipped families mask x with `FFFCh`; **the clipped families do not**.

### gfx_dissolve (634C)

* Draws into the **current target**, not only the screen, using the current row table.
* Destination: byte column = header x (not shifted), row = header y.
* Structure:
  * 12 passes, using the row order from CS:6338.
  * Within a pass, every 12th row.
  * Within a row, one **bit** per byte changes (half a CGA pixel). The mask starts at
    `CS:6344[phase & 7]` and rotates right by 1 per byte.
* After each row, `phase` is incremented and the source advances by `(u8)w * 11`.
* Row limit: `rowptr(y) + 2h`.

### gfx_draw_line (6D97)

* Coordinates are pixels. The x clip is `clip_x * 4`.
* **Horizontal lines** clip like TDEGA, then OR `colour` (a byte pattern) into the row. The edge bytes
  are masked through the CS:6D87/6D8B/6D8F tables, which is correct.
* **Vertical lines:**
  * The rejection test is `x <= clip_x0` (`jle`), so a line exactly on the left clip edge is not drawn.
    TDEGA uses `x < clip_x0`.
  * Otherwise OR `pixelmask & colour` into each row.
* **Diagonal lines** use TDEGA's 16.16 DDA and the same `0xFFF0:0xFFEE` constant typo in the y-major
  skip. Plotted pixels OR the full pixel mask, so `colour` is ignored and the result is colour 3.
* **Extra quirk (y-major only):** if the start row is above `clip_y0`, the code jumps into the
  **x-major** skip step (0x6FC5). From there:
  * "x" is register DX, which at that point holds the integer x step (0 or FFFFh).
  * "y" is advanced by the x step.
  * Everything after that runs as the x-major walk.

  The port reproduces this with a `goto`.

### Grabs

* **gfx_grab_screen(sx, sy, dx, dy, w_bytes, h):** copies bytes from B800h (using the screen row
  table) into the current target. `sx` and `dx` are pixels, shifted `>> 2`.
* **grab_into_sprite_raw(spr, x, y):** copies from the current target (using the current row table)
  into the sprite's rows.

## 4. Differences game code must handle (vs TDEGA)

* **Clip and byte columns are 4-pixel bytes.** The full screen is `x1 = 0x50` (EGA uses 0x28).
  Buffers are created with byte widths twice as large, for example 0x50 where EGA passes 0x28.
* **Byte alignment:** TDCGA aligns with `& 0xFFFC` / `>> 2`, where TDEGA uses `& 0xFFF8` / `>> 3`.
  Text advances 8 pixels = 2 bytes.
* **Colour arguments are byte or word patterns, not colour indices:**
  * fill_rect, clear_clip and clear_screen take a word. The shipped callers pass 0000h, AAAAh and FFFFh.
  * draw_rect_outline passes FFFFh through to fill_rect.
  * draw_line takes a byte; the callers pass FFh.
  * Colour c is pattern `c * 5555h`. Values such as 5555h and 8888h appear in the scene code's own
    direct buffer writes (0x2D58, 0x2E5C), where TDEGA uses plane values.
  * The port keeps the `u8 colour` API (`pattern = colour * 0101h`) and adds `*_pat(u16)` variants.
* **Text colours** are still indices 0–3 (fg 3 = white-grey, 1 = cyan, 2 = magenta).
* **gfx_create_buffer** ignores plane_mask.
* **Buffers are single bitmaps.** A buffer "without plane 3" (TDEGA's road buffer) does not exist, so
  the road-window plane-3 trick of platform.md §4.4a has no counterpart.
* **gfx_set_palette** does not exist. main does not load a game palette.
* **gfx_scroll_window** does not exist. TDCGA's credits call blit_copy_clip_raw (5A54).
* **gfx_dissolve and grab_into_sprite_raw** use the current target.
* **Clipped `*_own` blits** do not align x.

## 5. Palette (CGA)

0x4BDA runs these steps in order:

1. `clear_screen(<caller BP>)`
2. Equipment bits = 01b (0x10).
3. `INT 10h AX=0004h`.
4. `AH=0Bh BH=1 BL=1`.
5. `AH=0Bh BH=0 BL=0`.

The IBM BIOS (and DOSBox, which copies it) handles these as follows:

* **Mode set:** writes 30h to the colour select register 3D9h and to 0040:0066. 30h is bit 5
  (palette 1) plus bit 4 (intensified colours 1–3).
* **AH=0Bh BH=1:** replaces bit 5 only, so the register stays 30h.
* **AH=0Bh BH=0:** does `pal = (pal & E0h) | (BL & 1Fh)` and writes the result to 3D9h. With BL = 0
  this clears the background nibble **and bit 4**, leaving 20h.

The EGA/VGA BIOS emulates the same rule: BL bit 4 selects the intensity of palette entries 1–3 in
modes 4/5.

**Conclusion:** a real CGA (and an EGA/VGA running TDCGA) shows **low-intensity palette 1**:

| Colour | RGB |
|---|---|
| 0 | black |
| 1 | cyan #00AAAA |
| 2 | magenta #AA00AA |
| 3 | light grey #AAAAAA |

The high-intensity set (#55FFFF / #FF55FF / #FFFFFF) would require BL bit 4 in the last call.
`tools/tdres.py` renders the sprites with the high-intensity set, which is not what the game shows.

The port models 3D9h and derives colour 0 and colours 1–3 from it. Text modes, after gfx_shutdown or
before gfx_init_ega, display as black.

## 6. Hercules (`tdcga herc`)

main calls herc_init **before** 0x4BDA. herc_init (0x7587) does the following:

1. Equipment bits = 10b.
2. `INT 10h` mode 4. There is no colour adapter, so this only affects BIOS data and memory.
3. `out 3BFh, 3`: allow graphics and map page 1 at B800h.
4. `out 3B8h, 2`: graphics mode, video off.
5. Program the 6845 at 3B4h/3B5h with the 12 bytes from DS:661C.
6. Clear B800:0000–7FFF (4000h words).
7. `out 3B8h, 8Ah`: graphics, video on, display page 1.

The following 0x4BDA only reaches the absent CGA ports, so Hercules graphics mode stays on.

herc_shutdown (0x75D7) does the following:

1. Equipment bits = 10b.
2. `3BFh = 3`.
3. `3B8h = 20h`.
4. Load the MDA text CRTC table.
5. Clear B800:0000–7FFF.
6. `3B8h = 28h`.
7. `INT 10h` mode 7.

**Display geometry.** In graphics mode the card addresses RAM as `(RA << 13) + MA*2 +
half-character`, where RA is the scan-line counter within a character row (RA0/RA1 select one of 4
banks of 8 KB).

| CRTC register | Value | Meaning |
|---|---|---|
| R1 | 28h | 40 characters × 16 pixels = 640 pixels = 80 bytes per row |
| R6 | 64h | 100 rows |
| R9 | 2 | 3 scan lines per row |

So displayed row r shows:

| Scan line | Memory | Content |
|---|---|---|
| 0 | B800:0000 + 80r | CGA line 2r |
| 1 | B800:2000 + 80r | CGA line 2r+1 |
| 2 | B800:4000 + 80r | Bank 2: cleared, and nothing draws there, so black |

**Result:** 640×300 (the host shows it at 4:3). One bit is one pixel, so each 2-bit CGA pixel appears
as its two bits side by side:

| CGA colour | Pixels |
|---|---|
| 0 | off off |
| 1 | off on |
| 2 | on off |
| 3 | on on |

The port draws lit pixels in the chosen phosphor colour: green #33FF33 (default), amber #FFB000 or
white #FFFFFF (`gfx_set_monitor`).

**Memory model in the port:**

* CGA: 16 KB, mirrored at B800:4000.
* Hercules: 32 KB, mapped once 3BFh bit 1 is set.
* B800:8000 and above is not video RAM on either card: writes are dropped and reads return FFh.

The compose function honours the 3B8h/3BFh state and uses the programmed R1/R6/R9 values.
