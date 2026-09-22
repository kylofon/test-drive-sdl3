# Test Drive (1987, DSI/Accolade) — file formats & internals

Everything under "Verified" was confirmed against the disassembly and/or by exact size + CRC
round-trips on every shipped file. Unverified items are marked as such.

## Tools (run from this folder, Python 3.12 + Pillow + numpy + capstone)

| Script | Purpose |
|---|---|
| `tools/unexepack.py IN.EXE OUT.EXE` | Unpacks Microsoft EXEPACK (all three EXEs are packed) |
| `tools/x86dis.py EXE find HEX` / `dis OFF LEN` | Byte search / 16-bit disassembly on image offsets |
| `tools/tdres.py info|export FILE [OUTDIR]` | Decodes `.PES`/`.CMP` archives, exports each sprite as `.bin` + `.png` |
| `tools/sheet.py Game work/sheets` | One labelled contact sheet per archive |

Outputs: `work/ega/<ARCHIVE>/*.png` (541 sprites), `work/cga/<ARCHIVE>/*.png` (552 sprites),
`work/sheets/*.png`.

## Executables (Verified)

* `TD.EXE` – launcher: menu "1 CGA/EGA 4 colours, 2 EGA 16 colours, 3 Hercules", joystick calibration,
  then execs `tdcga.exe` or `tdega.exe`.
* `TDEGA.EXE` / `TDCGA.EXE` – the game. Microsoft C (1986 runtime) + hand-written assembly.
  EXEPACK-packed. TDEGA: 65 584 → 81 424 bytes unpacked, entry 0000:A50C, DGROUP segment 0x0C9A
  (DS:x = image offset 0xC9A0 + x), ~52 KB code, ~170 C function prologues.
* Hardware touched by TDEGA: `int 10h` (mode 0Dh 320×200/16 col; mode 4 CGA and mode 7 Hercules code
  also present). Palette: the mode-set routine 0x4D96 loads the stock table DS:637C, then `main`
  (0x5D) loads the game palette DS:00CC via `int 10h AX=1002h` and keeps it for the whole game:
  register values `00 01 02 03 04 05 07 16 00 10 06 12 13 14 11 17`, i.e. index 6 = light grey,
  7 = yellow, 8 = black, 9 = dark grey, 10 = brown, 11 = light green, 12 = light cyan,
  13 = light red, 14 = light blue, 15 = white, `int 16h` keyboard,
  `int 21h` files, timer `int 8` and `int 0` vectors hooked, PIT/speaker ports 40h–43h/61h,
  PIC 20h/21h, ~190 `out dx,al` (EGA sequencer/graphics-controller plane writes in blitters).
* Copy protection (image 0x8E80–0x91CF): `int 11h` floppy count, then `int 13h` reads of sectors with
  impossible IDs (0xF1/0xDE on track 39) expecting a CRC-error status and a 4-word signature
  (table at 0x8DB0); variant for hard-disk installs (`dl=80h`).
* `ROADDATA.SHP` string exists in the data segment but has no code references (leftover).

## Resource archive (Verified)

Both `.PES` (EGA) and `.CMP` (CGA) decompress to the same layout:

```
u32  total_size
u16  count
count × char[4]  names (zero padded; a few CGA names start with 0x00)
count × u32      offsets, relative to end of this table
...  resource data
```

### `.CMP` container (CGA)
`u32 unpacked_size` stored raw (it is also the archive's first field), followed by an RLE stream:
`83 vv nn` = byte `vv` repeated `nn` times, any other byte is literal.

### `.PES` container (EGA) — it is ARC's compression methods verbatim
```
char[4] "Pckd"
u32     packed_len (file size − 16)
u32     unpacked_len
u16     method      8 = "crunched" (LZW), 4 = "squeezed" (Huffman)   (only TESTDRV.PES uses 4)
u16     CRC-16/ARC  (poly 0xA001, init 0) of the final unpacked data
...     payload
```
* Method 8: `u8 maxbits (=12)` + Unix `compress` 4.0 LZW (9→12 bit codes, CLEAR=256, first free 257,
  codes read `n_bits` bytes at a time so leftover bits are discarded on width change/clear).
  Decoder at TDEGA image 0x9E40, getcode 0x9FA2.
* Method 4: `u16 node_count`, nodes of two `s16` children (negative = leaf `-(byte+1)`, leaf 256 = EOF),
  bitstream LSB-first.
* Both then pass through RLE90 (routine at 0x9CF9): `90 nn` repeats the previous byte `nn−1` more times,
  `90 00` is a literal 0x90.
* All 18 `.PES` files decode to exactly `unpacked_len` with matching CRC.

### Sprite resource
```
u16 width_in_bytes, u16 height, u16 hot_x, u16 hot_y, s16 x, s16 y, u8 planemap[4]
pixel data
```
* CGA: `height` rows of `width` bytes, 2 bits/pixel MSB first (320 px = 80 bytes). planemap unused.
* EGA: one block of `height × width` bytes per stored bit plane (1 bit/pixel, 320 px = 40 bytes).
  For planemap byte k, the low nibble lists the colour planes the k-th stored plane is written to.
  The high nibble of byte 0 lists planes **cleared** over the sprite rectangle, the high nibble of
  byte 1 lists planes **set** (or XORed, depending on the blit operation); byte 3 is padding
  (verified in the blitters, see `port/spec/platform.md`).
  Examples: `01 02 04 08` = normal 4 planes; `09 06 00 00` = 2 planes (planes 0+3, planes 1+2);
  `87 00 00 00` = 1 plane into planes 0–2 with plane 3 cleared (colour 0 or 7);
  `07 80 00 00` = 1 plane into planes 0–2 with plane 3 set (colour 8 or 15).
* There is no transparent colour: masked drawing is an AND blit of a mask sprite (`rg0m`) followed
  by an OR blit of the image (`rig0`).

### Archive contents
| Archive | Contents |
|---|---|
| `TESTDRV` | title logo, key fob, side view car + wheel frames, passenger window animation (`wnd0…R`) |
| `ACCOLADE`, `SLOGO`, `LLOGO` | publisher logo; car-select / high-score logos |
| `<CAR>` | cockpit: `dash`, `inst`, `roof`, steering wheel `whl1/3`, gear box `gbox`/knob, mirror, radar detector lights `rad0-5` |
| `<CAR>SB` | showroom: spec sheet `stat` (with acceleration graph), car, window animation, name plate |
| `GAS` | gas station screen + four station signs (`don`, `john`, `kevn`, `tony`) |
| `XROADA` | road-side objects: cliffs, poles, rocks, lane lines, speed/turn/two-way/gas signs at 5 scales, oil, potholes, gravel, `deal` (THE END MOTORS), `note` ("Nice job. Keep the car. Go home."), `tick` (speeding ticket), `govr` (GAME OVER) |
| `XROADB` / `XROADC` | traffic at 5 scales: truck, rig, RX-7, van front/rear, sedan, cop car front/rear with light frames |

## Road data (embedded in TDEGA.EXE; decoded by `tools/roadmap.py`)

Verified from the disassembly unless noted. DS = image 0xC9A0.

| What | DS | Image |
|---|---|---|
| Record table, 0x6E × `[flag, curve, pitch, object]` | 0x2B70 | 0xF510 |
| Road byte stream, 5 stages, each ends with `0xFF` | 0x2D28–0x6360 | 0xF6C8–0x12D00 |
| Stage start pointers, 5 × u16 | 0x6361 | 0x12D01 |

(TDCGA: same stream at image 0xD598; its pointers are offset by −0x30.)

* One stream byte = one road unit = an index into the record table.
  * Codes 01–08: right curves (+1 +2 +4 +6 +9 +12 +16 +20). Codes 09–10: the matching left curves.
  * Codes 11–18: hills (pitch ±8 … ±64).
  * Object codes, low 6 bits: 2–8 signs (right turn, left turn, two-way, three speed limits, gas station; bit 0x80 = other side of the road), 1 police, 0x10–0x14 / 0x18–0x1C traffic (top 2 bits = spawn-chance threshold), 0x20–0x23 hazards (top 2 bits = lane).
* Stage lengths: 2097, 2913, 2845, 2674 and 3347 units.
* Moving forward (0x3FE8): a sub-unit counter drops by speed/128 each tick and gets +90 on each unit advance. The curve value ×64 pushes the car sideways; the road edge is at ±0x264.
* Look-ahead (0x4241) reads 40 units ahead: `0xFF` there triggers the gas-station sequence, and object codes spawn traffic, police or hazards (0x467D).
* Road drawing (0x2054): 40 rows. heading += curve×64 (clamped to ±75°), x += sin(heading); slope += pitch×4, y += sin(slope).
* **Schematic only:** the game only uses heading within the 40-row window, so integrating it over a whole stage gives loops (stage 3 nets +1022°). The pitch values don't add up to a consistent altitude either.

## Car files (`tools/cardata.py` → `work/cars/NAME.json`)

`NAME.BIN` is read raw, 0x4D6 bytes, into DS:268F (code at image 0x10E2). Fields below are verified in TDEGA unless marked.

| Offset | Field |
|---|---|
| +000 | number of gears |
| +004 | rev limit; going over it damages the engine |
| +008 | grip limit, above which the car skids; +00A is the skid drift |
| +00C/+00E | steering-wheel sprite x,y (inferred) |
| +012 | 7 gear ratios (gear 0 = neutral); rpm = ratio × speed ÷ 65536 |
| +020 | gear-knob x,y for each gear |
| +03C | 16 shift-gate nodes; +07C is a 9×16 table of joystick direction × node → next node; +10C maps node → gear |
| +11C | 80-byte torque curve, one entry per 128 rpm |
| +16C | 1 = needle gauges, otherwise digital (Corvette); +16E is the needle pivots; +17A speedo tips by speed; +328 tach tips by rpm ÷ 64 |

* Acceleration = (torque × ratio, ×1.5 in 1st, − drag) ÷ 64. The drag table, braking and idle rpm (800) are in the EXE.
* Unused by TDEGA: +002, +006, +010 and +172..+179.
* `NAME.SS` is text: two numbers, then the lists of wheel and window animation frame names.

## TDSND.SND (`tools/sndplay.py` → `work/sound/*.wav`)

* A standard resource archive holding 4 songs (`sng1`–`sng4`) of bytecode.
* The player runs on a 100 Hz timer and drives the PC speaker. Play function at image 0x8A3E, queue function at 0x8A0E.
* Events: a note number (note 55 ≈ A440, 0 = rest; divisor table at DS:6452) followed by a u16 duration in ticks.
* Control codes:
  * `FE` sets the note cut-off.
  * `FD/FC/FB n` start loops 1–3; `FA/F9/F8` end them.
  * `F7/F6/F5` skip the rest of a loop on its last pass.
  * `FF` ends the song or chains to the next.

## SCORES

* 8 entries, each written with `%-20.20s%-20.20s%ld` plus a CRLF.
* The line after each entry is a `%x` CRC-8 checksum: reflected polynomial 0xB8, seeded with the row number 0–7, computed over the formatted line plus `\n`.
* Entries with a bad checksum are skipped when the file is loaded.

## Amiga release

The Amiga disk and executable are described in `port/amiga/README.md`. Extract the disk with
`tools/adf.py`; `tools/amigares.py` decodes everything below (`info`, `unpack`, `export`, `wav`, `smus`, `song`,
`pal`, `scores`, `ss`, `car`). Addresses are td image addresses (base 0x10000); globals `D:xxxx` are offsets
into the data hunk. All binary numbers are big-endian. Confidence as in `port/RE_GUIDE.md`: everything here is
**verified** against the disassembly unless marked *likely* or *guess*.

### File loading

* `0x149D2 load_file(name)` and `0x149E8 load_file_chip(name)` both call `0x149FE(name, memflags)` (0x10001 =
  PUBLIC|CLEAR, 0x10003 = PUBLIC|CHIP|CLEAR). It Locks and Examines the file for its size and reads the first 16
  bytes. Then it either unpacks a `Pckd` file or loads the file as it is. It returns the buffer (also left in
  D:24BC) and puts the size in D:2810.
* Buffers come from `0x15930 alloc(size, flags)`: `(size + 0x17) & ~3` bytes, with a 16-byte header in front of the
  returned pointer (`+0` allocation size, `+4/+8` list links, `+0C` "MemB") and "MemE" in the last long. The SMUS
  player uses the size at `ptr − 0x10` as its chunk-search limit. MEMF_CLEAR means text files end in zeros.
* Samples, instruments and shapes are loaded into chip memory (`0x149E8`). Text files, the SMUS score, car records
  and ILBMs go into any memory (`0x149D2`).

### Containers, shapes, pictures

* **`Pckd`** is the `.PES` container above with every field big-endian (`"Pckd"`, `u32 packed_len`,
  `u32 unpacked_len`, `u16 method`, `u16 CRC-16/ARC`). The decoder (0x14C9C) handles ARC methods 2 (stored),
  3 (RLE90), 4 (squeezed) and 8 (crunched). The files use 4 and 8, and all of them decode with matching CRCs. A file
  without the magic is loaded as it is (`Pics/Road.Shp`, the ILBM screens).
* **Shape archives** (`*.Shp`, unpacked) have the resource-archive layout, big-endian. Many entry names match
  the DOS ones (108 of the 167 in `Road.Shp` are also in `XROAD?.PES`), but the art was redrawn, so sizes and hot spots differ.
  `0x15472 find_shape(archive, name)` looks an entry up by its 4-character name, compared as a long. It returns 0
  when the name is missing, and the blitter entry (0x10FDA) ignores any shape pointer ≤ 0x32.
* **Shape**: `u16 width_bytes, u16 height, s16 hot_x, s16 hot_y, s16 x, s16 y, u16 planes (5), u16 plane_bytes`,
  then `planes` bitplanes of `plane_bytes` (= width_bytes × height) bytes, MSB = leftmost pixel. `x, y` is where
  the showroom and dashboard code draws the shape (`+8/+0A`, `0x10E12`).
* **Pictures** are standard IFF ILBM, 320×200, 5 planes, ByteRun1: title screens, dashboards, spec sheets,
  gas station, logos and the ending. On the cracked disk, `Pics/title2` was repainted by the crackers ("Cracked by the
  Rogues"). The original "Accolade presents" picture is lost.
* **`Pics/Endgame.Shp`** holds one shape, `note`. It is 160×79, 5 planes, drawn at 64,21 over `Pics/EndGame`: the
  handwritten "Nice job. Keep the car. Go home." note. It is the Amiga counterpart of the DOS `XROADA` `note`.
* **`Pics/Gas.Shp`** holds the four gas-station signs `don `, `john`, `kevn` and `tony` (144×28–30, drawn at
  112,5–6 over the "Joe's GAS n' FOOD" sign of `<car>Gas`), as in DOS `GAS.PES`. The gas station (0x147E4)
  picks one by stage: `find_shape(gas, D:0A66[D:24CC])`, where D:0A66 = `"don johnkevntony"` as four longs.
  These shapes are signs, not attendants.
* **`Cars/<car>Logo.Pal`**: 32 text lines, each one colour as `%x` (12-bit `0RGB`, e.g. `A75`). The high-score
  table reads it with `0x13F32(row, carpath, ucoplist)`. This function builds a user copper list: `CWait(row × 0x23 + 1, 0)`, then
  `CMove(0xDFF180 + 2i, colour)` and `CBump` for the 32 colour registers. Each table row (35 lines tall) therefore gets
  its car's logo palette. When the file is missing, the 32 colours of D:098E are used instead. `row == −1` loads
  D:098E with `LoadRGB4`. The file is the CMAP of `<car>Logo` (4 bits per gun) with 1–4 entries changed. The
  line reader (0x12FF0) copies characters ≥ 0x20 and then skips one terminator.

### Samples (`Sfx/*`, `Songs/Drum`, `Drum2`, `BuzzSynth`)

```
u32  length   bytes of sample data
u16  rate     Hz; a value < 100 is taken as kHz (×1000)
...  signed 8-bit PCM (length bytes; a file may carry one pad byte)
```
There are **no loop fields**. `0x1246A play_sample(sample, channel, volume)` computes the Paula period as
`0x369E99 / rate`. 3 579 545 is the NTSC clock, and td uses it on PAL machines too. The function then calls
`0x124C4 start_channel(data = sample + 6, length, channel, period, volume, repeats = 1)`. The caller chooses the
repeat count: 1 plays once, −1 loops forever.

| File | Length | Rate | Period | Used by |
|---|---|---|---|---|
| `Sfx/Accolade` | 13122 | 10000 | 357 | title (0x1AED0), channel 3, volume 0x40 |
| `Sfx/Starter` | 50000 | 5000 | 715 | title and showroom drive-away (0x1C244), channel 3, volume 0x40 |
| `Sfx/Radar` | 3354 | 20000 | 178 | radar detector (0x26C50), channel 0, volume 0x40, once |
| `Sfx/Bump` | 340 | 9400 | 380 | bump (0x26EE2), channel 0, volume 0x40, once, only when channel 0 is idle |
| `Sfx/Squeal` | 904 | 10000 | (0x166) | tyre squeal, channel 1, loop; period and volume envelope from the tables at 0x26E7E/0x26EB0 (0x26E26) |
| `Sfx/TheTurbo` | 9261 | 5000 | (0x320) | second engine layer, channel 2, loop; period and volume from rpm and throttle (0x26D4E) |
| `Sfx/TheEngine` | 10825 | 9150 | (0x320) | engine, channel 3, loop; period `0x249988 / max(rpm, 800)` clamped 0x82–0x708 |
| `Songs/Drum` | 1704 | 14300 | 250 | songs, one-shot percussion |
| `Songs/Drum2` | 566 | 10000 | 357 | `TestDrive` song, one-shot percussion |
| `Songs/BuzzSynth` | 17 | (0x0682) | — | songs, looped waveform; the rate field is not used |

Quirk: `0x26C70` starts the three looping engine sounds with `data = sample` instead of `sample + 6`, and with
the length from the header. Their loop therefore includes the 6 header bytes and leaves out the last 6 sample
bytes. The engine code sets their periods; the rate field is not used.

**Sfx engine** (root 0x12304–0x12612). D:0446 holds four channel records of 0x1E bytes, one per Paula channel:
`+00 data ptr (0 = idle)`, `+04 tick of the last stop`, `+08 start pending`, `+0A length in words`,
`+0C period`, `+0E volume (16.16)`, `+12 repeats`, `+14 repeats left`, `+16 target volume (16.16, −1 = none)`,
`+1A volume step`. The helper functions:

* `0x12546` stops a channel: DMA off, AUDxVOL 0, and it records the tick from D:04C2.
* `0x125A6(ch, period, vol)` changes the period and volume (a negative value keeps the current one).
* `0x125F4(ch, target, step)` starts a volume slide.

The engine runs on two interrupts:

* `Sfx VBLInt` (0x126AE, priority 0x1E, installed by 0x12304) counts ticks in D:04C2. It starts a pending channel
  once **2 ticks** have passed since that channel's last stop: it writes AUDxLC/LEN/PER/VOL and enables DMA. It also
  steps the volume slides.
* The level-4 audio interrupt (0x12616, vector 0x70) counts blocks. When `!data || --left < 0`, it stops the
  channel (volume 0, period 0x96, DMA off, stop tick recorded). Paula raises this interrupt as each block starts, so
  `repeats = n` plays the sample n times, and a negative count never stops.

Only the channels in D:1E9E get the audio interrupt. `0x12432(mask)` sets D:1E9E = `(~mask & 0xF) << 7`, so the
channels in `mask` are left to the song player's looped waveforms. D:0344 is the sound-on flag, which a key
toggles in 0x10462. The game calls the sfx functions only when this flag is set.

### Songs (`Songs/*.Iff.Sng`): IFF SMUS

The files are `FORM SMUS` with these chunks:

* `SHDR`.
* `NAME`: the composer's file name (`drivecarfin.iff.sng`, `selectfin.iff.sng`, `testgasfin.iff.sng`,
  `endsuccess.iff.sng`, `gameoverfin.iff.sng`).
* 3–5 `INS1` chunks (register, type 0, name): `Percussion`, `ElecBass`, `BuzzSynth`, `First Voice`, `PipeOrgan`,
  `StratSynth`, `PhaseSynth`.
* Three `TRAK` chunks. Every track starts with the events `clef`, `key sig 0` and `instrument n`.

td plays them from the `Song VBLInt` server at `0x12A54`, installed by 0x1278C. Its priority is 0x20, so it runs
before the sfx server. The player state is in D:0732: 0 idle, 1 start, 2 playing, 3 stop. The rules:

* **Chunk search.** On start the player scans the file in 2-byte steps for the long `SHDR`, up to the allocation
  size at `ptr − 0x10`. It stores the tempo word in D:08BE and the volume byte in D:08C0, then finds up to four
  `TRAK`s the same way. It does not read `NAME`, `INS1` or the SHDR track count. **The SHDR tempo and volume are
  never used.**
* **Timing** is fixed. `0x12972` passes 6 to `0x129BA`, which fills the duration table D:0710 with ticks per
  `data & 0x0F`: whole 96, half 48, quarter 24, eighth 12, sixteenth 6; dotted (bit 3) 144, 72, 36, 18, 9.
  Codes 5–7 (1/32 and shorter) and 13–15 keep their initialised values (0, 0, 0, 12, 0, 0), and a 0 would mean 65535
  ticks. The songs use only codes 0–4 and 9–11. At 50 Hz a quarter note lasts 0.48 s, which is 125 bpm; the files ask for
  130–200 bpm. The tuplet bits (5–4) and the **chord bit (7) are ignored**, so chord notes play one after another.
* **Events** are 2 bytes, `sID, data`. `sID ≤ 0x7F` is a note and `0x80` a rest. `0x81–0xFF` are skipped
  without using any time: instrument, time and key signature, dynamics, MIDI, clef, tempo and mark events are all
  ignored. A note or rest sets the track's countdown to `duration − 1`, and the countdown drops each tick. When it
  reaches 1, the channel volume is set to 0 unless the note is tied, so every note is cut one tick early (a
  quarter note sounds for 22 ticks). When it reaches 0, the next event is read on the following tick.
* **Rest**: AUDxVOL = 0, and the tie flag is cleared.
* **Tie** (data bit 6): the next note does not retrigger, so there is no new period and no restart. The next note
  only updates the tie flag.
* **Instruments** are fixed per track by the caller, not taken from the file (the player skips the
  `instrument` events). Track k plays on Paula channel k. Each track plays one of two kinds of instrument:
  * A **one-shot sample**, played through the sfx engine with `0x1246A(sample, k, song volume)`. It plays at its
    native rate and ignores the note number; a retrigger waits one tick.
  * A **looped waveform**: AUDxLC = `inst + 6`, AUDxLEN = `(length & 0xFFFF) >> 1` words, AUDxPER =
    `note_table[note] / (length & 0xFFFF)` (at least 0x7C), AUDxVOL = song volume, and DMA is left running.

  `note_table` is at D:0500: 132 longs, indexed with `note − 0x3C` from D:05F0. For notes 24–131 it holds
  `0x369E99 / f(note)` (note 69 = A440); notes 0–23 repeat the octave 24–35. BuzzSynth's length is 17, so the
  period is computed for 17 bytes while Paula plays 16. Waveform notes therefore sound 17/16 sharp, about a semitone high.
* **End**: a track past its last event gets volume 0 and DMA off. When no track is active, the state goes back to
  1 and the song **restarts from the top** one tick later. Songs loop until they are stopped.
* **Volume**: `0x12942(volume, step)` puts the target in D:1EF8 (16.16) and the step in D:1EF0. Each tick
  `0x12C98` slides D:1EF4 towards the target (step 0 = jump at once). Notes use the high word of D:1EF4.

The entry point is `0x12CF4 play_song(file, instruments[4], oneshot[4], waveform_mask, volume)`:

1. If a different song is loaded, it is stopped first by `0x12DB0`, which fades to 0 at 0x5400 per tick, waits and frees the song.
2. It loads `songs/<file>`.
3. It loads the instruments with `0x12826`. A name pointer ≤ 10 means "the sample of slot n".
4. It calls `0x12432(waveform_mask)`, sets the volume and starts the player.

If the requested song is already loaded, play_song only fades the volume in (step 0x8000). The five callers:

| Function | File | Tracks 0–3 (one-shot marked *) | Mask | Volume | Called from |
|---|---|---|---|---|---|
| 0x12E12 | `TestDrive.Iff.Sng` | BuzzSynth, Drum2*, Drum*, BuzzSynth | 1 | 0x20 | 0x10018 (main) |
| 0x12E58 | `Test2.Iff.Sng` | BuzzSynth, BuzzSynth, Drum*, BuzzSynth | 3 | 0x16 | 0x10018 (main) |
| 0x12E8A | `TestGas.Iff.Sng` | same | 3 | 0x16 | 0x147E4 (gas station) |
| 0x12EBE | `EndSuccess.Iff.Sng` | same | 3 | 0x16 | 0x1C900 (drive overlay, ending) |
| 0x12EF6 | `Loser.Iff.Sng` | same | 3 | 0x16 | **no caller**: the game-over song is never played |

The files have only three tracks, so track 3 is never used. In `EndSuccess` the third track is a melody
(notes 26–66), but it is given the one-shot `Drum`, so it plays as drum hits. This follows the code and was
probably not what the composer heard. One loop of each song at 50 Hz lasts:

| Song | Ticks | Time |
|---|---|---|
| TestDrive | 14784 | 4:56 |
| Test2 | 2016 | 40.3 s |
| TestGas | 1920 | 38.4 s |
| EndSuccess | 12096 | 4:02 |
| Loser | 1152 | 23.0 s |

`amigares.py song` renders the songs with these rules (Paula mix: channels 0 and 3 left, 1 and 2 right).

### Showroom script (`Cars/<car>.SS`)

`0x1C244` (the showroom drive-away) parses this text file:
```
N\n          number of entries
M\n          entry at which the car starts to drive away
then N entries of 4 characters, each followed by one separator byte (space or newline)
```
`sscanf(buf, "%d %d")` reads both numbers. The parser then skips two lines and takes a name every 5 bytes, so the
line breaks carry no meaning. Each name is looked up in `<car>.ST.Shp`. Entries 0–2 are the front wheel
frames and 3–5 the rear wheel frames. The rest are the body animation, drawn at each shape's own x,y.

| Car | N | M | Body entries from 6 (standing \| driving) |
|---|---|---|---|
| P911T | 36 | 29 | logo×10 shdw wnd1–9 fac1–3 \| fac4 fac5 fac5 fac6×4 |
| Rossa | 32 | 29 | logo×6 shdw wnd1–8 fac1–4 fac5 fac5 fac6 fac6 \| fac7×3 |
| Lotus | 33 | 30 | logo×6 shdw wnd1–9 fac1–4 fac5 fac5 fac6 fac6 \| fac7×3 |
| Countach | 30 | 29 | logo×6 dor0–7 dor7 dor6 dor5 dor5 dor3 dor2 dor1 dor0 dor0 \| dor0 |
| Vette | 33 | 30 | as Lotus |

`fac7` is missing from `Rossa.ST.Shp` and `Lotus.ST.Shp`, so those frames draw nothing (find_shape returns 0).

The animation starts `Sfx/Starter` on channel 3 and then runs in two phases:

1. **Standing**: entry k = 6, 7, ... is drawn every 9 ticks.
2. **Driving away**, once k reaches M. Each frame (2 ticks) draws entries `wheel` and `wheel + 3`, with
   `wheel = ((x + 4) / 5) % 3`, then does `x += vel >> 16` and `vel += 0x2EE0`. The picture is shown shifted by −x,
   and entries M..N−1 keep playing one per frame. The car is gone when x ≥ 0x140.

A key or fire (D:0346) ends the animation early. Afterwards td waits 10 frames and stops channel 3. The tick
counter used is D:03D8.

Differences from DOS (`port/spec/game_flow.md`, `showroom_drive_away`):

* The DOS file is `wndCount startFrame` plus three lines of names: 3 front wheel frames, 3 rear wheel frames and the window frames.
* In DOS the rear wheel uses `dist % 3`, the motion is `vel += 10` with `dist += vel >> 4`, and frames come every 30 or 6 ticks of the 100 Hz timer.
* The Amiga uses one flat list with its own frame names, and M is an absolute entry index.

### Car record (`Cars/<car>.B`) against DOS `.BIN`

`0x24ACA` loads `<carpath>.b` (pointer in D:2548), and `0x20D68` copies it into the globals D:1924–D:1982, so the
Amiga code itself gives the field layout. It is the DOS layout (see "Car files") with every 16-bit field
big-endian. The byte tables are identical byte for byte (`+07C` gate transitions, `+10C`, `+11C` torque, the
needle tips). These fields are read differently on the Amiga, or left unused by DOS:

| Offset | Amiga use | Confidence |
|---|---|---|
| +002 | Tachometer clamp: needle index = `max(min(rpm, +002), 800) / 64` (DOS clamps to +004). 15000; Vette 20000. | verified use |
| +006 | Engine-sound flag (0x26D4E). 0 adds 1500 rpm to the volume curve of the `TheTurbo` layer and doubles its period. It is 1 for P911T and Lotus (the turbo cars) and 0 for the others. | verified use, meaning *likely* (turbo) |
| +008 | Maximum steering/slip value before skidding (0x24A04). The excess, clamped to 0..0x40, is the skid amount and the squeal volume. At or over the limit, steering is clamped and speed drops by 0x4000. This is a different grip model from DOS; the values are the DOS ones ÷ 72.6. | verified use, units *likely* |
| +00A | Read as a word (DOS reads the byte); skid drift `(skid × +00A) >> 8`. | verified |
| +00C, +00E, +010 | Steering-wheel marker: centre x,y and radius (0x247D2: `x = +00C ± sin·r`, `y = +00E − cos·r`). | verified use, meaning *likely* |
| +172..+178 | Four words, the needle boxes: speedometer (+172, +174) and tachometer (+176, +178). 0x1F2EA draws each needle (51 rows) from the pivot bytes +16E/+170 to the tip, both minus the box origin. | verified use, *likely* (hardware sprites) |
| +17A | Speedometer tips, index `max(speed − 10, 0)`. There is no clamp and no per-car case in 0x20B88. | verified |

Digital dashboard (`+16C == 0`, the Corvette), decoded from 0x20D68, 0x2097C and 0x25118. The DOS analysis never
located the code for it.

| Offset | Field | Vette |
|---|---|---|
| +16E | Speed digits x,y: hundreds, tens, units (3 × 2 words). | (76,156) (82,156) (88,156) |
| +17A | Speed bar direction: 0 = its left edge moves left from x0; otherwise its right edge moves right. | 0 |
| +17C, +17E | Bar x0; +17E is unused. | 169, 135 |
| +180 | Bar scale: length = `speed × +180 >> 16` (clip window D:0380/D:0386). | 0x60B6 |
| +182 | Digit shape prefix: 4 chars masked with 0x7F7F7F00, plus `'0' + digit`, give `dgt0`..`dgt9`. | `dgt0` with bit 7 set |
| +318 | Tach digits x,y: hundreds (never drawn, since rpm/100 ≤ 99), tens, units. | (0,0) (185,157) (191,157) |
| +324, +326, +328 | Tach bar direction, x0, unused. | 1, 164, 183 |
| +32A | Tach bar scale: length = `(max(rpm,800) >> 4) × +32A >> 16`. | 5584 |
| +32C | Tach digit prefix. | `dgt0` with bit 7 set |

**`Vette.B` is 816 bytes (0x330)** because the record ends with the last digital field (+32C + 4). The Corvette
does not need the two 215-entry needle tables of the analog cars, which run up to 0x4D6. The DOS release has
the same 816-byte `VETTE.BIN`: DOS asks for 0x4D6 bytes and gets a short read. Apart from endianness, the only
bytes that differ between `Vette.B` and `VETTE.BIN` are the 8 prefix bytes, which have bit 7 set on the Amiga
(td masks it off).

Values that differ between the Amiga and DOS records (everything else is equal after byte-swapping the words):

| Car | +004 rev limit | +008 grip (DOS → Amiga) | +00C, +00E wheel (DOS → Amiga) |
|---|---|---|---|
| P911T | 7900 | 4864 → 67 | 112,210 → 114,217 |
| Rossa | **9200 → 8600** | 5009 → 69 | 120,210 → 119,200 |
| Lotus | 8100 | 4939 → 68 | 129,210 → 124,200 |
| Countach | 9100 | 4792 → 66 | 130,206 → 130,196 |
| Vette | 7100 | 5082 → 70 | 129,205 → 127,192 |

Unchanged in all five cars: gears, +002, +006, +00A, +010, the ratios, the knob and gate positions, the gate
graph, the torque curves, the gauge pivots, +172..+178 and the needle tables.

### `Cars.txt`

`0x10346` reads the file with load_file (`Cars.Txt`):

1. `sscanf("%d")` gives the count. If `0 < count < 30`, the first line is skipped.
2. For each car, the current position (a pointer into the buffer) is stored in D:2E66[i].
3. The line is skipped with `0x10402` (advance to `\n`, then past it), and the byte before the new position
   (the `\n`) is cleared, which makes the line a C string.

The paths are directory-relative stems (`cars/P911t`) that the game extends with `.b`, `.SS`, `.ST`, `.SB`,
`.ST.Shp`, `Dash`, `Dash.Shp`, `Gas`, `Logo`, `logo.Shp` and `Logo.Pal`. The file must use `\n` line ends.
D:0350 holds the number of cars, and D:1E94 is set to 1 when the file is missing.

Quirks:

* A last line without `\n` loses its last character.
* A count outside 1..29 leaves the count line as the first path.

### `HighScores`

Loaded by `0x13028(names[8][40], scores[8], cars[8][40])` and saved by `0x1313E(same)`. It is text with `\n` line ends:
```
8 × { name\n  score (decimal, %ld)\n  car path\n }      (sprintf "%s\n%ld\n%s\n", into a 500-byte buffer)
checksum\n                                             ("%04x\n")
```
* The checksum is `0x14088(buf, len, 0x6D62, 0x2058)`: a CRC over `len / 2` big-endian 16-bit words (an odd last
  byte is not included), MSB first, with initial value 0x6D62 and polynomial 0x2058:
  `for each bit b: crc ^= b << 15; carry = crc >> 15; crc = crc << 1 (16 bits); if carry crc ^= 0x2058`.
  It covers every byte of the 24 entry lines, including their `\n`. The shipped file checks (`9728`).
* On load, the name and car lines are copied up to the first control character, with no length check (the arrays
  are 40 bytes). The score is read with `sscanf("%ld")`, and the checksum line with `sscanf("%x")` into a
  16-bit int. A missing file or a wrong checksum clears all 8 entries (the function returns 1).
* The car path is the `Cars.txt` stem. The table shows the `logo` shape of `<path>logo.Shp` and uses `<path>Logo.Pal`.
* Differences from DOS `SCORES`: three lines per entry instead of one fixed-width line, one 16-bit CRC for the
  whole table instead of a CRC-8 per entry, and `\n` instead of CRLF.
