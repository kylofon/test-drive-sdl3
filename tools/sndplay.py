"""Test Drive (1987) TDSND.SND -> WAV (PC-speaker square wave).

Container: u32 total, u16 count, count*4-char names, count*u32 offsets
(relative to the end of the offset table).  Songs are a byte-code stream
interpreted by the 100 Hz timer IRQ in TDEGA.EXE (image 0x6A1F):

  n (0x00..0x7F) dur:u16   note n (0 = rest) for dur ticks; PIT divisor =
                           table DS:6452[n]; speaker is cut when the
                           remaining count equals dur >> shift (shift 0 = legato).
                           Each event lasts dur+1 ticks.
  FE s                     set articulation shift
  FD/FC/FB n:u16           loop 1/2/3 start, body plays n+1 times
  FA/F9/F8                 loop 1/2/3 end
  F7/F6/F5                 if loop 1/2/3 counter == 0 jump to its end marker
                           (skip the rest of the body on the last pass)
  FF                       end of song (or start queued song)

Usage: python tools/sndplay.py [--loops N] [--rate 44100]
"""
import argparse
import os
import struct
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIT = 1193182
TICK_HZ = PIT / 0x2E97          # 100.04 Hz timer set by 699E


def load_divisors(exe):
    d = open(exe, 'rb').read()
    img = d[struct.unpack_from('<H', d, 8)[0] * 16:]
    return struct.unpack_from('<128H', img, 0xC9A0 + 0x6452)


def parse_archive(b):
    total, count = struct.unpack_from('<IH', b, 0)
    names = [b[6 + 4 * i:10 + 4 * i].decode() for i in range(count)]
    base = 6 + 8 * count
    offs = struct.unpack_from('<%dI' % count, b, 6 + 4 * count)
    return {n: base + o for n, o in zip(names, offs)}


def run(b, pos, max_loops, max_ticks=100 * 600):
    """Returns list of (divisor or 0, ticks)."""
    shift = 0
    cnt = [0, 0, 0]
    start = [0, 0, 0]
    endpos = [0, 0, 0]
    out = []
    ticks = 0
    while ticks < max_ticks:
        op = b[pos]
        if op < 0x80:
            dur = struct.unpack_from('<H', b, pos + 1)[0]
            pos += 3
            cut = (dur >> shift) if (op and shift) else 0
            if op == 0:
                out.append((0, dur + 1))
            else:
                out.append((op, dur + 1 - cut))
                if cut:
                    out.append((0, cut))
            ticks += dur + 1
        elif op == 0xFF:
            break
        elif op == 0xFE:
            shift = b[pos + 1]
            pos += 2
        elif 0xFB <= op <= 0xFD:
            k = 0xFD - op
            cnt[k] = min(struct.unpack_from('<H', b, pos + 1)[0], max_loops)
            pos += 3
            start[k] = pos
        elif 0xF8 <= op <= 0xFA:
            k = 0xFA - op
            cnt[k] -= 1
            if cnt[k] >= 0:
                endpos[k] = pos
                pos = start[k]
            else:
                pos += 1
        elif 0xF5 <= op <= 0xF7:
            k = 0xF7 - op
            pos = endpos[k] if cnt[k] == 0 else pos + 1
        else:
            raise ValueError('bad opcode %02x at %x' % (op, pos))
    return out


def render(events, div, rate):
    chunks = []
    phase = 0.0
    for note, t in events:
        n = int(round(t * rate / TICK_HZ))
        if note == 0 or div[note] == 0:
            chunks.append(np.zeros(n))
            continue
        f = PIT / div[note]
        ph = phase + np.arange(n) * f / rate
        chunks.append(np.where((ph % 1.0) < 0.5, 1.0, -1.0))
        phase = (phase + n * f / rate) % 1.0
    s = np.concatenate(chunks) if chunks else np.zeros(1)
    return (s * 9000).astype('<i2')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--snd', default=os.path.join(ROOT, 'Game', 'TDSND.SND'))
    ap.add_argument('--exe', default=os.path.join(ROOT, 'work', 'TDEGA_unp.exe'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'sound'))
    ap.add_argument('--loops', type=int, default=1, help='cap for loop repeat counts (FD 400 = "forever")')
    ap.add_argument('--rate', type=int, default=44100)
    a = ap.parse_args()
    b = open(a.snd, 'rb').read()
    div = load_divisors(a.exe)
    os.makedirs(a.out, exist_ok=True)
    for name, pos in parse_archive(b).items():
        ev = run(b, pos, a.loops)
        pcm = render(ev, div, a.rate)
        path = os.path.join(a.out, name + '.wav')
        with wave.open(path, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(a.rate)
            w.writeframes(pcm.tobytes())
        notes = [n for n, _ in ev if n]
        print('%s: %d events, %.1f s, note range %d..%d -> %s' % (
            name, len(ev), len(pcm) / a.rate, min(notes), max(notes), path))


if __name__ == '__main__':
    main()
