"""Amiga Test Drive resources: `Pckd` files, shape archives, IFF ILBM pictures, samples, SMUS songs, text files.

    python tools/amigares.py info FILE...          what each file is (container, method, CRC, archive entries)
    python tools/amigares.py unpack FILE OUT       write the unpacked contents of a Pckd file
    python tools/amigares.py export FILE OUTDIR [PALETTE_ILBM]
                                                   PNGs of an ILBM picture or of every shape in an archive
                                                   (shapes use the CMAP of PALETTE_ILBM, default grey ramp)
    python tools/amigares.py wav FILE OUT.wav [NOTE SECONDS]
                                                   a Sfx/instrument sample as WAV at its header rate; with NOTE
                                                   (SMUS note number, 60 = middle C) the sample is looped the way
                                                   the song player plays a waveform instrument (Songs/BuzzSynth)
    python tools/amigares.py smus FILE             dump an IFF SMUS score (chunks, events, td's timing)
    python tools/amigares.py song NAME OUT.wav [SECONDS] [SONGDIR]
                                                   render one of td's five songs (TestDrive, Test2, TestGas,
                                                   EndSuccess, Loser) with td's player rules, stereo 22050 Hz
    python tools/amigares.py pal FILE              a <car>Logo.Pal colour list (32 x 12-bit RGB)
    python tools/amigares.py scores FILE           HighScores entries and checksum check
    python tools/amigares.py ss FILE               a <car>.SS showroom animation script
    python tools/amigares.py car FILE.B            the Amiga car record, fields as td reads them (0x20D68)

`Pckd` is the DOS .PES container (FORMATS.md) with its fields big-endian:
    char[4] "Pckd", u32 packed_len, u32 unpacked_len, u16 method, u16 CRC-16/ARC, payload
Methods (the decoder at 0x14C9C switches on method - 2): 2 stored, 3 packed (RLE90), 4 squeezed (Huffman +
RLE90), 8 crunched (LZW 9-12 bits + RLE90). The loader (0x149FE) keeps a file without the magic as it is.
Unpacked archives (`.Shp`) have the DOS archive layout, big-endian:
    u32 total_size, u16 count, count x char[4] names, count x u32 offsets (from the end of the table), data
Shapes: the DOS sprite header, big-endian, with the plane map replaced by a plane count and size:
    u16 width_bytes, u16 height, s16 hot_x, s16 hot_y, s16 x, s16 y, u16 planes (5), u16 plane_bytes
    then `planes` bitplanes of `plane_bytes` = width_bytes * height bytes, MSB = leftmost pixel.
Samples (Sfx/*, Songs/Drum, Drum2, BuzzSynth), read by 0x1246A: u32 length (bytes), u16 rate (Hz; < 100 means
kHz), then signed 8-bit PCM. Paula period = 0x369E99 / rate. No loop fields: the caller picks the repeat count.
The rest of the formats, and the td code they come from, are in the Amiga section of FORMATS.md.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tdres import crc16_arc, unlzw, unrle90, unsqueeze  # noqa: E402


def unpack(data):
    """(contents, description) for a Pckd file; other files come back unchanged."""
    if data[:4] != b"Pckd":
        return data, "raw"
    packed, unpacked, method, crc = struct.unpack_from(">IIHH", data, 4)
    payload = data[16:]
    if method == 2:
        out = payload
    elif method == 3:
        out = unrle90(payload)
    elif method == 4:
        out = unrle90(unsqueeze(payload))
    elif method == 8:
        out = unrle90(unlzw(payload))
    else:
        raise ValueError(f"unknown Pckd method {method}")
    out = out[:unpacked]
    ok = len(out) == unpacked and crc16_arc(out) == crc
    return out, f"Pckd method {method}, {packed} -> {unpacked} bytes, {'crc ok' if ok else 'CRC/SIZE MISMATCH'}"


def archive(raw):
    """[(name, blob)] if raw is a shape archive, else None."""
    if len(raw) < 6:
        return None
    total, count = struct.unpack_from(">IH", raw, 0)
    base = 6 + 8 * count
    if count == 0 or base > len(raw) or total > len(raw) + 16:
        return None
    names = [raw[6 + 4 * k:10 + 4 * k] for k in range(count)]
    if not all(all(c == 0 or 0x20 <= c < 0x7F for c in n) for n in names):
        return None
    offs = struct.unpack_from(f">{count}I", raw, 6 + 4 * count)
    if any(o > len(raw) - base for o in offs):
        return None
    order = sorted(range(count), key=lambda k: offs[k])
    ends = {}
    for n, k in enumerate(order):
        ends[k] = offs[order[n + 1]] if n + 1 < len(order) else len(raw) - base
    return [(names[k].rstrip(b"\0").decode("latin-1"), raw[base + offs[k]:base + ends[k]]) for k in range(count)]


def ilbm(data):
    """(width, height, pixels as bytes of colour indices, [(r, g, b)] palette) of an IFF ILBM."""
    assert data[:4] == b"FORM" and data[8:12] == b"ILBM"
    pos, bmhd, cmap, body = 12, None, [], None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack_from(">I", data, pos + 4)[0]
        chunk = data[pos + 8:pos + 8 + size]
        if cid == b"BMHD":
            bmhd = struct.unpack_from(">HHhhBBBBHBBhh", chunk)
        elif cid == b"CMAP":
            cmap = [tuple(chunk[i:i + 3]) for i in range(0, len(chunk) - 2, 3)]
        elif cid == b"BODY":
            body = chunk
        pos += 8 + size + (size & 1)
    w, h, _x, _y, nplanes, masking, compression = bmhd[:7]
    row = (w + 15) // 16 * 2
    planes_in_body = nplanes + (1 if masking == 1 else 0)
    if compression == 1:  # ByteRun1
        out, i = bytearray(), 0
        need = row * planes_in_body * h
        while len(out) < need and i < len(body):
            n = body[i] if body[i] < 128 else body[i] - 256
            i += 1
            if n >= 0:
                out += body[i:i + n + 1]
                i += n + 1
            elif n != -128:
                out += bytes([body[i]]) * (1 - n)
                i += 1
        body = bytes(out)
    pix = bytearray(w * h)
    for y in range(h):
        for p in range(nplanes):
            line = body[(y * planes_in_body + p) * row:(y * planes_in_body + p + 1) * row]
            for x in range(w):
                if line[x >> 3] >> (7 - (x & 7)) & 1:
                    pix[y * w + x] |= 1 << p
    return w, h, bytes(pix), cmap


def shape(blob):
    """(width, height, header fields, pixels) of a shape."""
    wb, h, hx, hy, x, y, planes, psize = struct.unpack_from(">2H4h2H", blob, 0)
    w = wb * 8
    pix = bytearray(w * h)
    for p in range(planes):
        base = 16 + p * psize
        for yy in range(h):
            for xx in range(w):
                b = blob[base + yy * wb + (xx >> 3)] if base + yy * wb + (xx >> 3) < len(blob) else 0
                if b >> (7 - (xx & 7)) & 1:
                    pix[yy * w + xx] |= 1 << p
    return w, h, (hx, hy, x, y, planes), bytes(pix)


CLOCK = 0x369E99  # 3579545, the NTSC Paula clock td divides by (0x1246A)
VBL_HZ = 50        # PAL vertical blank: every player runs from a VBL server


def sample(data):
    """(rate_hz, signed PCM bytes, length field) of a Sfx/instrument file (0x1246A)."""
    length, rate = struct.unpack_from(">IH", data, 0)
    if rate < 100:  # 0x12480: cmp.w #$64 / mulu #$3e8
        rate *= 1000
    return rate, data[6:6 + length], length


def write_wav(path, rate, frames, channels=1):
    """frames: list of ints -32768..32767 (interleaved when stereo)."""
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(frames)}h", *[max(-32768, min(32767, int(v))) for v in frames]))


# Song player note table (D:0500-D:070F, 132 longs): CLOCK / frequency, indexed by SMUS note number (0x12BDA
# indexes D:05F0 with note - 0x3C). Notes 0-23 repeat the octave 24-35 (lowest C = 32.7 Hz).
_OCT = [109456, 103312, 97514, 92041, 86875, 81999, 77397, 73053, 68953, 65083, 61430, 57982]
NOTE_TABLE = _OCT * 2 + _OCT + [
    54728, 51656, 48757, 46020, 43437, 40999, 38698, 36526, 34476, 32541, 30715, 28991, 27364, 25828, 24378,
    23010, 21719, 20500, 19349, 18263, 17238, 16271, 15357, 14496, 13682, 12914, 12189, 11505, 10859, 10250,
    9675, 9132, 8619, 8135, 7679, 7248, 6841, 6457, 6095, 5753, 5430, 5125, 4837, 4566, 4310, 4068, 3839, 3624,
    3420, 3229, 3047, 2876, 2715, 2562, 2419, 2283, 2155, 2034, 1920, 1812, 1710, 1614, 1524, 1438, 1357, 1281,
    1209, 1141, 1077, 1017, 960, 906, 855, 807, 762, 719, 679, 641, 605, 571, 539, 508, 480, 453, 428, 404, 381,
    360, 339, 320, 302, 285, 269, 254, 240, 226]


def waveform_period(inst, note):
    """Paula period for a looped waveform instrument (0x12BD6): table / low word of the length field, >= 0x7C."""
    return max(NOTE_TABLE[note] // (struct.unpack_from(">H", inst, 2)[0] or 1), 0x7C)


# The five songs: 0x12E12 TestDrive, 0x12E58 Test2, 0x12E8A TestGas, 0x12EBE EndSuccess, 0x12EF6 Loser (no caller).
# (instrument names per track, one-shot flags per track, song volume, "waveform channel" mask for 0x12432).
# A name slot of 0 means "same sample as slot 0" (0x12840: a value <= 10 is an index into the slots).
SONGS = {
    "TestDrive": (["BuzzSynth", "Drum2", "Drum", 0], [0, 1, 1, 0], 0x20, 1),   # D:08C6 / D:08D6
    "Test2": (["BuzzSynth", 0, "Drum", 0], [0, 0, 1, 0], 0x16, 3),              # D:08DE / D:08EE
    "TestGas": (["BuzzSynth", 0, "Drum", 0], [0, 0, 1, 0], 0x16, 3),
    "EndSuccess": (["BuzzSynth", 0, "Drum", 0], [0, 0, 1, 0], 0x16, 3),
    "Loser": (["BuzzSynth", 0, "Drum", 0], [0, 0, 1, 0], 0x16, 3),
}
SMUS_EVENTS = {0x80: "rest", 0x81: "instrument", 0x82: "time sig", 0x83: "key sig", 0x84: "dynamic",
               0x85: "MIDI chan", 0x86: "MIDI preset", 0x87: "clef", 0x88: "tempo", 0xFF: "mark"}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def iff_chunks(data, form):
    assert data[:4] == b"FORM" and data[8:12] == form, "not an IFF " + form.decode()
    pos, out = 12, []
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack_from(">I", data, pos + 4)[0]
        out.append((cid.decode("latin-1"), data[pos + 8:pos + 8 + size]))
        pos += 8 + size + (size & 1)
    return out


def duration_table(t=6):
    """Ticks per SMUS duration code (data & 0x0F), as 0x129BA fills D:0710 for tempo t (td always passes 6).
    Codes 5-7 and 13-15 keep their initial data (0, 0, 0 and 12, 0, 0); 0 means 65535 ticks in the player."""
    d = [16 * t, 8 * t, 4 * t, 2 * t, t, 0, 0, 0]
    t15 = t + (t >> 1)
    return d + [16 * t15, 8 * t15, 4 * t15, 2 * t15, t15, 12, 0, 0]


def smus_dump(data):
    durs = duration_table()
    for cid, body in iff_chunks(data, b"SMUS"):
        if cid == "SHDR":
            tempo, vol, ntr = struct.unpack_from(">HBB", body)
            print(f"SHDR tempo {tempo:#06x} = {tempo / 128:g} quarter notes/min, volume {vol}, {ntr} tracks"
                  " (td stores tempo and volume in D:08BE/D:08C0 and never reads them)")
        elif cid == "INS1":
            reg, typ, d1, d2 = body[:4]
            print(f"INS1 register {reg} type {typ} data {d1},{d2} name {body[4:].rstrip(bytes(1)).decode('latin-1')!r}"
                  " (ignored by td)")
        elif cid == "TRAK":
            print(f"TRAK {len(body)} bytes, {len(body) // 2} events")
            tick = 0
            for i in range(0, len(body) - 1, 2):
                sid, v = body[i], body[i + 1]
                if sid > 0x80:
                    print(f"  {tick:6d}        {SMUS_EVENTS.get(sid, 'event %02X' % sid)} {v}   (skipped by td)")
                    continue
                n = durs[v & 15]
                what = "rest" if sid == 0x80 else f"{NOTE_NAMES[sid % 12]}{sid // 12 - 1} ({sid})"
                flags = []
                if v & 0x80:
                    flags.append("chord (ignored: played in sequence)")
                if v & 0x40:
                    flags.append("tie")
                if v & 0x30:
                    flags.append(f"tuplet {v >> 4 & 3} (ignored)")
                if v & 8:
                    flags.append("dotted")
                print(f"  {tick:6d} +{n:4d}  {what:12s} div {v & 7}{' ' + ', '.join(flags) if flags else ''}")
                tick += n
            print(f"  {tick:6d}  end ({tick / VBL_HZ:.2f} s at {VBL_HZ} Hz)")
        else:
            print(f"{cid} {len(body)} bytes: {body[:40]!r}")


class Paula:
    """Minimal Paula channel: a DMA pointer looping over a block, like the hardware (period, volume 0-64)."""

    def __init__(self):
        self.block, self.period, self.vol, self.pos, self.on, self.loops = b"", 0x96, 0, 0.0, False, -1

    def render(self, n, out_rate):
        out = [0.0] * n
        if not self.on or not self.block or not self.period:
            return out
        step = CLOCK / self.period / out_rate
        blk, L = self.block, len(self.block)
        for i in range(n):
            p = int(self.pos)
            if p >= L:
                if self.loops == 0:
                    self.on = False
                    break
                if self.loops > 0:
                    self.loops -= 1
                    if self.loops == 0:
                        self.on = False
                        break
                self.pos -= L
                p = int(self.pos)
            s = blk[p]
            out[i] = (s - 256 if s > 127 else s) * self.vol
            self.pos += step
        return out


def song_render(name, songdir, seconds, out_rate=22050):
    """Render with the rules of the Song VBLInt player (0x12A54) and the Sfx engine for one-shot instruments."""
    names, oneshot, vol, _mask = SONGS[name]
    score = (Path(songdir) / f"{name}.Iff.Sng").read_bytes()
    insts = []
    for k in range(4):
        nm = names[k]
        insts.append(insts[nm] if isinstance(nm, int) else (Path(songdir) / nm).read_bytes())
    traks = [body for cid, body in iff_chunks(score, b"SMUS") if cid == "TRAK"][:4]
    durs = duration_table()
    chans = [Paula() for _ in range(4)]
    trk = [dict(active=False) for _ in range(4)]
    state, frames, per_tick = 1, [], out_rate // VBL_HZ
    pending = [None] * 4  # one-shot starts the Sfx VBLInt makes (it runs after the song server)
    for _tick in range(int(seconds * VBL_HZ)):
        for c in range(4):  # Sfx VBLInt: start a pending one-shot once 2 ticks have passed since the stop
            if pending[c] is not None:
                pending[c][1] -= 1
                if pending[c][1] <= 0:
                    inst = pending[c][0]
                    rate, pcm, _ = sample(inst)
                    ch = chans[c]
                    ch.block, ch.period, ch.vol, ch.pos, ch.on, ch.loops = pcm[:len(pcm) & ~1], CLOCK // rate, vol, 0.0, True, 1
                    pending[c] = None
        if state == 1:  # (re)start: SHDR/TRAK scan, every track from the top
            for k in range(4):
                trk[k] = dict(active=k < len(traks), pos=0, left=0, tie=False)
            state = 2
        else:
            any_active = False
            for k in range(4):
                t, ch = trk[k], chans[k]
                if not t["active"]:
                    continue
                any_active = True
                if t["left"]:
                    t["left"] -= 1
                    if t["left"] == 1 and not t["tie"]:
                        ch.vol = 0  # articulation: the note is cut one tick before its end
                    continue
                ev = traks[k]
                while True:
                    if t["pos"] >= len(ev):  # end of track: volume 0, DMA off
                        ch.vol, ch.on, t["active"] = 0, False, False
                        break
                    sid, v = ev[t["pos"]], ev[t["pos"] + 1]
                    t["pos"] += 2
                    if sid > 0x80:
                        continue
                    t["left"] = (durs[v & 15] - 1) & 0xFFFF
                    if sid == 0x80:
                        ch.vol, t["tie"] = 0, False
                    elif oneshot[k]:
                        # 0x1246A: stop the channel (if busy) and queue the sample; retrigger waits a tick
                        busy = ch.on
                        ch.on, ch.vol = False, 0
                        pending[k] = [insts[k], 1 if busy else 0]
                        if not busy:
                            rate, pcm, _ = sample(insts[k])
                            ch.block, ch.period, ch.vol, ch.pos, ch.on, ch.loops = pcm[:len(pcm) & ~1], CLOCK // rate, vol, 0.0, True, 1
                            pending[k] = None
                    else:
                        if not t["tie"]:
                            inst = insts[k]
                            ch.period = waveform_period(inst, sid)
                            n = struct.unpack_from(">H", inst, 2)[0] >> 1
                            ch.block, ch.vol, ch.loops = inst[6:6 + 2 * n], vol, -1
                            if not ch.on:
                                ch.pos, ch.on = 0.0, True
                        t["tie"] = bool(v & 0x40)
                    break
            state = 2 if any_active else 1
        mixes = [ch.render(per_tick, out_rate) for ch in chans]
        for i in range(per_tick):  # Amiga stereo: channels 0 and 3 left, 1 and 2 right
            frames += [(mixes[0][i] + mixes[3][i]) * 2, (mixes[1][i] + mixes[2][i]) * 2]
    return out_rate, frames


def logo_pal(data):
    """32 colours from a <car>Logo.Pal: one line per colour, sscanf "%x" (0x13F32), 12-bit 0RGB."""
    cols = []
    for line in data.split(b"\n")[:32]:
        v = int(line.strip() or b"0", 16)
        cols.append(v)
    return cols


def hs_checksum(buf, crc=0x6D62, poly=0x2058):
    """0x14088: CRC over 16-bit big-endian words (len/2 of them, an odd last byte is ignored), MSB first."""
    for i in range(0, len(buf) // 2 * 2, 2):
        w = buf[i] << 8 | buf[i + 1]
        for k in range(16):
            crc ^= (w >> (15 - k) & 1) << 15
            top = crc >> 15
            crc = crc << 1 & 0xFFFF
            if top:
                crc ^= poly
    return crc


def highscores(data):
    """[(name, score, car)], checksum stored, checksum computed (0x13028)."""
    lines, pos, entries = data.split(b"\n"), 0, []
    body_len = 0
    for k in range(8):
        name, score, car = lines[3 * k:3 * k + 3]
        entries.append((name.decode("latin-1"), int(score or b"0"), car.decode("latin-1")))
        body_len += len(name) + len(score) + len(car) + 3
    stored = int(lines[24].strip() or b"0", 16) if len(lines) > 24 else None
    return entries, stored, hs_checksum(data[:body_len])


def ss_script(data):
    """(count, start, names) of a <car>.SS (0x1C244): sscanf "%d %d", skip two lines, then `count` 4-char names
    each followed by one separator byte."""
    text = data.decode("latin-1")
    first = text.split()
    count, start = int(first[0]), int(first[1])
    p = text.index("\n") + 1
    p = text.index("\n", p) + 1
    names = []
    for _ in range(count):
        names.append(text[p:p + 4])
        p += 5
    return count, start, names


def car_record(b):
    """Fields of Cars/<car>.B as 0x20D68 copies them into D:1924..D:1982 (big-endian)."""
    w = lambda o: struct.unpack_from(">H", b, o)[0]
    f = {
        "+000 gears (D:1924)": w(0), "+002 tach clamp rpm (D:1926)": w(2), "+004 rev limit (D:1928)": w(4),
        "+006 turbo flag, engine sound only (D:192A)": w(6), "+008 max steer before skid (D:192C)": w(8),
        "+00A skid drift, word (D:192E)": w(0xA), "+00C steering wheel centre x (D:1930)": w(0xC),
        "+00E steering wheel centre y (D:1932)": w(0xE), "+010 steering wheel marker radius (D:1934)": w(0x10),
        "+012 gear ratios": [w(0x12 + 2 * i) for i in range(7)],
        "+020 knob x,y per gear": [(w(0x20 + 4 * i), w(0x22 + 4 * i)) for i in range(7)],
        "+10C node -> gear": list(b[0x10C:0x11C]), "+11C torque curve (80)": list(b[0x11C:0x16C]),
        "+16C analog gauges": w(0x16C),
    }
    if w(0x16C):
        f["+16E speedo pivot x,y (bytes)"] = (b[0x16E], b[0x16F])
        f["+170 tach pivot x,y (bytes)"] = (b[0x170], b[0x171])
        f["+172 speedo needle box x,y"] = (w(0x172), w(0x174))
        f["+176 tach needle box x,y"] = (w(0x176), w(0x178))
        f["+17A speedo tips (215 x,y bytes)"] = f"{len(b[0x17A:0x328]) // 2} pairs"
        f["+328 tach tips (215 x,y bytes)"] = f"{len(b[0x328:0x4D6]) // 2} pairs"
    else:
        f["+16E speed digit x,y (hundreds, tens, units)"] = [(w(0x16E + 4 * i), w(0x170 + 4 * i)) for i in range(3)]
        f["+17A speed bar: dir (0 = grows left), x0, unused, scale"] = (w(0x17A), w(0x17C), w(0x17E), w(0x180))
        f["+182 speed digit shape prefix"] = bytes(c & 0x7F for c in b[0x182:0x185]).decode("latin-1")
        f["+318 tach digit x,y (hundreds, tens, units)"] = [(w(0x318 + 4 * i), w(0x31A + 4 * i)) for i in range(3)]
        f["+324 tach bar: dir (0 = grows left), x0, unused, scale"] = (w(0x324), w(0x326), w(0x328), w(0x32A))
        f["+32C tach digit shape prefix"] = bytes(c & 0x7F for c in b[0x32C:0x32F]).decode("latin-1")
    return f


def png(path, w, h, pix, palette):
    from PIL import Image
    img = Image.frombytes("P", (w, h), pix)
    flat = [c for rgb in palette for c in rgb]
    img.putpalette(flat + [0] * (768 - len(flat)))
    img.save(path)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "info":
        for path in sys.argv[2:]:
            data = Path(path).read_bytes()
            raw, desc = unpack(data)
            kind = ""
            if raw[:4] == b"FORM":
                kind = f"IFF {raw[8:12].decode('latin-1')}"
            else:
                arc = archive(raw)
                if arc:
                    kind = f"archive of {len(arc)}: " + " ".join(f"{n}({len(b)})" for n, b in arc[:12])
                    kind += " ..." if len(arc) > 12 else ""
                else:
                    kind = f"data {raw[:16].hex(' ')}"
            print(f"{path}: {desc}; {kind}")
    elif cmd == "unpack":
        raw, desc = unpack(Path(sys.argv[2]).read_bytes())
        Path(sys.argv[3]).write_bytes(raw)
        print(desc)
    elif cmd == "export":
        raw, _ = unpack(Path(sys.argv[2]).read_bytes())
        out = Path(sys.argv[3])
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(sys.argv[2]).name.replace(".", "_")
        if raw[:4] == b"FORM":
            w, h, pix, cmap = ilbm(raw)
            png(out / f"{stem}.png", w, h, pix, cmap)
            print(f"{stem}.png {w}x{h}")
            return
        palette = [(i * 8, i * 8, i * 8) for i in range(32)]
        if len(sys.argv) > 4:
            palette = ilbm(unpack(Path(sys.argv[4]).read_bytes())[0])[3]
        for name, blob in archive(raw) or []:
            if len(blob) < 16:
                continue
            w, h, fields, pix = shape(blob)
            if w and h:
                png(out / f"{stem}_{name.replace('/', '_')}.png", w, h, pix, palette)
        print(f"{len(archive(raw) or [])} shapes")
    elif cmd == "wav":
        data = Path(sys.argv[2]).read_bytes()
        rate, pcm, length = sample(data)
        if len(sys.argv) > 5:  # looped waveform at a note, as the song player does it
            note, secs = int(sys.argv[4]), float(sys.argv[5])
            ch = Paula()
            n = struct.unpack_from(">H", data, 2)[0] >> 1
            ch.block, ch.period, ch.vol, ch.on = data[6:6 + 2 * n], waveform_period(data, note), 64, True
            out_rate = 22050
            frames = [v * 4 for v in ch.render(int(secs * out_rate), out_rate)]
            write_wav(sys.argv[3], out_rate, frames)
            print(f"{length} bytes, loop of {2 * n}, note {note}: period {ch.period}, "
                  f"{CLOCK / ch.period / (2 * n):.2f} Hz")
        else:
            write_wav(sys.argv[3], rate, [(c - 256 if c > 127 else c) * 256 for c in pcm])
            print(f"{length} bytes at {rate} Hz (period {CLOCK // rate}), {length / rate:.3f} s")
    elif cmd == "smus":
        smus_dump(Path(sys.argv[2]).read_bytes())
    elif cmd == "song":
        name = sys.argv[2]
        secs = float(sys.argv[4]) if len(sys.argv) > 4 else 30
        songdir = sys.argv[5] if len(sys.argv) > 5 else "work/amiga/disk/Songs"
        rate, frames = song_render(name, songdir, secs)
        write_wav(sys.argv[3], rate, frames, 2)
        print(f"{name}: {secs:g} s")
    elif cmd == "pal":
        for i, v in enumerate(logo_pal(Path(sys.argv[2]).read_bytes())):
            print(f"{i:2d} {v:03X}  rgb({(v >> 8 & 15) * 17}, {(v >> 4 & 15) * 17}, {(v & 15) * 17})")
    elif cmd == "scores":
        entries, stored, calc = highscores(Path(sys.argv[2]).read_bytes())
        for name, score, car in entries:
            print(f"{score:7d}  {name:20s} {car}")
        print(f"checksum stored {stored:04x}, computed {calc:04x}: {'ok' if stored == calc else 'BAD (td clears the table)'}")
    elif cmd == "ss":
        count, start, names = ss_script(Path(sys.argv[2]).read_bytes())
        print(f"{count} entries, car starts moving at entry {start}")
        print("  front wheel:", " ".join(names[0:3]), "  rear wheel:", " ".join(names[3:6]))
        print(f"  standing (9 ticks each), entries 6..{start - 1}:", " ".join(names[6:start]))
        print(f"  while driving away (2 ticks each), entries {start}..{count - 1}:", " ".join(names[start:]))
    elif cmd == "car":
        for k, v in car_record(Path(sys.argv[2]).read_bytes()).items():
            print(f"{k:48s} {v}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
