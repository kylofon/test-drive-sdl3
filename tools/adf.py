"""Amiga disk images (.adf, 880 KB DD): list and extract the files of an OFS/FFS volume.

    python tools/adf.py DISK.adf list
    python tools/adf.py DISK.adf extract OUTDIR
    python tools/adf.py DISK.adf boot OUT.bin      (the 1 KB boot block)

Layout (AmigaDOS): 1760 blocks of 512 bytes, big-endian longs. Root block 880. Header blocks
(root, directories, files) keep a 72-entry hash table / data-block table at longs 6..77 and
their name as a BCPL string at byte 432. OFS data blocks have a 24-byte header; FFS ones are
raw 512 bytes. Files longer than 72 blocks continue in extension blocks (long 126 = next).
"""
import struct
import sys
from pathlib import Path

BSIZE = 512
T_HEADER, T_DATA, T_LIST = 2, 8, 16
ST_ROOT, ST_DIR, ST_FILE = 1, 2, -3


class Adf:
    def __init__(self, data: bytes):
        if data[:3] != b"DOS":
            raise ValueError("not an AmigaDOS disk")
        self.data = data
        self.ffs = bool(data[3] & 1)
        self.nblocks = len(data) // BSIZE

    def block(self, n):
        return self.data[n * BSIZE:(n + 1) * BSIZE]

    def longs(self, n):
        return struct.unpack(">128l", self.block(n))

    def name(self, n):
        b = self.block(n)
        return b[433:433 + b[432]].decode("latin-1")

    def entries(self, n):
        """(name, block, secondary type) for every entry of the directory at block n."""
        L = self.longs(n)
        for h in L[6:78]:
            while h:
                e = self.longs(h)
                yield self.name(h), h, e[127]
                h = e[124]  # hash chain

    def file_bytes(self, n):
        L = self.longs(n)
        size = L[81] & 0xFFFFFFFF
        blocks = []
        hdr = n
        while hdr:
            H = self.longs(hdr)
            count = H[2]
            # data blocks are stored from long 77 downwards
            blocks += [H[77 - i] for i in range(count)]
            hdr = H[126]
        out = bytearray()
        for b in blocks:
            if self.ffs:
                out += self.block(b)
            else:
                D = self.block(b)
                dsize = struct.unpack(">l", D[12:16])[0]
                out += D[24:24 + dsize]
        return bytes(out[:size])

    def walk(self, n=880, path=""):
        for name, blk, st in sorted(self.entries(n), key=lambda e: e[0].lower()):
            p = f"{path}/{name}" if path else name
            if st == ST_DIR:
                yield p, blk, None
                yield from self.walk(blk, p)
            else:
                yield p, blk, self.longs(blk)[81] & 0xFFFFFFFF


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    adf = Adf(Path(sys.argv[1]).read_bytes())
    cmd = sys.argv[2]
    if cmd == "list":
        print(f"volume {adf.name(880)!r}, {'FFS' if adf.ffs else 'OFS'}")
        for p, blk, size in adf.walk():
            print(f"{'<dir>' if size is None else size:>8}  {p}")
    elif cmd == "extract":
        out = Path(sys.argv[3])
        for p, blk, size in adf.walk():
            target = out / p
            if size is None:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(adf.file_bytes(blk))
    elif cmd == "boot":
        Path(sys.argv[3]).write_bytes(adf.data[:1024])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
