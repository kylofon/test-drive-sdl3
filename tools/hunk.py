"""AmigaDOS load files (hunk format): list the hunks, their relocations and symbols, and write a
flat, relocated image for disassembly.

    python tools/hunk.py FILE info
    python tools/hunk.py FILE image OUT.bin [BASE]    (hunks laid out from BASE, default 0x10000,
                                                        each aligned to 16 bytes; prints the map)

Overlaid programs (HUNK_OVERLAY) are read too: the image places every overlay hunk at its own
address, as if all were loaded at once. The loader relocates HUNK_RELOC32 entries by adding each target hunk's load address. BSS hunks
occupy zeroed space in the image.
"""
import struct
import sys
from pathlib import Path

NAMES = {
    0x3E7: "UNIT", 0x3E8: "NAME", 0x3E9: "CODE", 0x3EA: "DATA", 0x3EB: "BSS", 0x3EC: "RELOC32",
    0x3ED: "RELOC16", 0x3EE: "RELOC8", 0x3EF: "EXT", 0x3F0: "SYMBOL", 0x3F1: "DEBUG", 0x3F2: "END",
    0x3F3: "HEADER", 0x3F5: "OVERLAY", 0x3F6: "BREAK", 0x3F7: "DREL32", 0x3F8: "DREL16", 0x3F9: "DREL8",
    0x3FC: "RELOC32SHORT",
}


class Hunk:
    def __init__(self, index, kind, size):
        self.index, self.kind, self.size = index, kind, size  # size in bytes (from the header)
        self.data = b""
        self.relocs = {}   # target hunk -> [offsets]
        self.symbols = []  # (name, offset)
        self.memflags = 0
        self.overlay = False


def load(path):
    b = Path(path).read_bytes()
    pos = 0

    def L():
        nonlocal pos
        v = struct.unpack_from(">L", b, pos)[0]
        pos += 4
        return v

    if L() != 0x3F3:
        raise ValueError("not a load file")
    while L():  # resident library names
        pass
    count, first, last = L(), L(), L()
    hunks = []
    for i in range(first, last + 1):
        s = L()
        h = Hunk(i, None, (s & 0x3FFFFFFF) * 4)
        h.memflags = s >> 30
        hunks.append(h)
    cur = 0
    overlay_table = []
    while pos < len(b):
        t = L() & 0x3FFFFFFF
        h = hunks[cur] if cur < len(hunks) else None
        if t in (0x3E9, 0x3EA):
            n = L() * 4
            h.kind = NAMES[t]
            h.data = b[pos:pos + n]
            pos += n
        elif t == 0x3EB:
            L()
            h.kind = "BSS"
        elif t in (0x3EC, 0x3F7):
            while True:
                n = L()
                if not n:
                    break
                target = L()
                h.relocs.setdefault(target, []).extend(L() for _ in range(n))
        elif t == 0x3FC:
            while True:
                n = struct.unpack_from(">H", b, pos)[0]
                pos += 2
                if not n:
                    break
                target = struct.unpack_from(">H", b, pos)[0]
                pos += 2
                offs = struct.unpack_from(f">{n}H", b, pos)
                pos += 2 * n
                h.relocs.setdefault(target, []).extend(offs)
            pos = (pos + 3) & ~3
        elif t == 0x3F0:
            while True:
                n = L()
                if not n:
                    break
                name = b[pos:pos + n * 4].rstrip(b"\0").decode("latin-1")
                pos += n * 4
                h.symbols.append((name, L()))
        elif t == 0x3F1:
            n = L() * 4
            pos += n
        elif t == 0x3E8:
            n = L() * 4
            pos += n
        elif t == 0x3F2:
            cur += 1
        elif t == 0x3F5:
            # Overlay table (size in longs, then size + 1 longs), then the overlay nodes: each is
            # a HUNK_HEADER naming more hunk numbers, those hunks, and HUNK_BREAK.
            n = L()
            overlay_table[:] = struct.unpack_from(f">{n + 1}L", b, pos)
            pos += (n + 1) * 4
        elif t == 0x3F3:
            while L():
                pass
            L()
            first, last = L(), L()
            while len(hunks) <= last:
                hunks.append(Hunk(len(hunks), None, 0))
            for i in range(first, last + 1):
                s = L()
                hunks[i].size = (s & 0x3FFFFFFF) * 4
                hunks[i].memflags = s >> 30
                hunks[i].overlay = True
            cur = first
        elif t == 0x3F6:
            pass
        else:
            raise ValueError(f"unhandled hunk type {t:#x} at {pos - 4:#x}")
    return hunks, overlay_table


def layout(hunks, base):
    addr, bases = base, []
    for h in hunks:
        bases.append(addr)
        addr = (addr + h.size + 15) & ~15
    return bases, addr


def image(hunks, base):
    bases, end = layout(hunks, base)
    img = bytearray(end - base)
    for h, hb in zip(hunks, bases):
        img[hb - base:hb - base + len(h.data)] = h.data
    for h, hb in zip(hunks, bases):
        for target, offs in h.relocs.items():
            for o in offs:
                p = hb - base + o
                v = struct.unpack_from(">L", img, p)[0]
                struct.pack_into(">L", img, p, (v + bases[target]) & 0xFFFFFFFF)
    return bytes(img), bases


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    hunks, overlay_table = load(sys.argv[1])
    if sys.argv[2] == "info":
        for h in hunks:
            nrel = sum(len(v) for v in h.relocs.values())
            mem = ["any", "chip", "fast", "?"][h.memflags]
            print(f"hunk {h.index}: {h.kind:4}{' overlay' if h.overlay else ''} size {h.size:#07x} ({mem}) data {len(h.data):#07x} "
                  f"relocs {nrel} -> hunks {sorted(h.relocs)} symbols {len(h.symbols)}")
            for name, off in h.symbols[:20]:
                print(f"    {off:#07x} {name}")
        if overlay_table:
            print("overlay table:", " ".join(f"{v:08x}" for v in overlay_table))
    elif sys.argv[2] == "image":
        base = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x10000
        img, bases = image(hunks, base)
        Path(sys.argv[3]).write_bytes(img)
        for h, hb in zip(hunks, bases):
            print(f"hunk {h.index} {h.kind:4} {hb:#08x}-{hb + h.size:#08x}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
