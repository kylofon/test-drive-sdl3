"""Amiga Test Drive resources: `Pckd` files, shape archives, IFF ILBM pictures, samples.

    python tools/amigares.py info FILE...          what each file is (container, method, CRC, archive entries)
    python tools/amigares.py unpack FILE OUT       write the unpacked contents of a Pckd file
    python tools/amigares.py export FILE OUTDIR [PALETTE_ILBM]
                                                   PNGs of an ILBM picture or of every shape in an archive
                                                   (shapes use the CMAP of PALETTE_ILBM, default grey ramp)

`Pckd` is the DOS .PES container (FORMATS.md) with its fields big-endian:
    char[4] "Pckd", u32 packed_len, u32 unpacked_len, u16 method, u16 CRC-16/ARC, payload
Methods (the decoder at 0x14C9C switches on method - 2): 2 stored, 3 packed (RLE90), 4 squeezed (Huffman +
RLE90), 8 crunched (LZW 9-12 bits + RLE90). The loader (0x149FE) keeps a file without the magic as it is.
Unpacked archives (`.Shp`) have the DOS archive layout, big-endian:
    u32 total_size, u16 count, count x char[4] names, count x u32 offsets (from the end of the table), data
Shapes: the DOS sprite header, big-endian, with the plane map replaced by a plane count and size:
    u16 width_bytes, u16 height, s16 hot_x, s16 hot_y, s16 x, s16 y, u16 planes (5), u16 plane_bytes
    then `planes` bitplanes of `plane_bytes` = width_bytes * height bytes, MSB = leftmost pixel.
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
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
