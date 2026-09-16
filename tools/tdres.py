"""Test Drive (1987) resource tools.

Container formats
  *.CMP (CGA): u32 size, then RLE stream (0x83 vv nn -> vv repeated nn times)
  *.PES (EGA): "Pckd" u32 packed_len, u32 unpacked_len, u16 ARC method, u16 CRC-16 (ARC, poly 0xA001)
               method 8 "crunched": u8 maxbits(12) + Unix-compress 4.0 LZW, then RLE90
               method 4 "squeezed": Huffman tree + bitstream, then RLE90
Both decode to a resource archive: u32 total, u16 count, count*4 names, count*u32 offsets, data.
Sprites: 16-byte header (u16 width_bytes, height, hx, hy, x, y) + 4 plane-map bytes + pixel rows.
  CGA: rows of 2bpp packed pixels (plane-map bytes unused).
  EGA: one block of rows per stored bit plane; plane-map byte k: low nibble = color bits the
       k-th stored plane sets, high nibbles of all four bytes OR together into constant color bits.

usage: tdres.py info FILE
       tdres.py export FILE OUTDIR
"""
import struct, sys, os
import numpy as np

CGA_PAL = [(0, 0, 0), (85, 255, 255), (255, 85, 255), (255, 255, 255)]
# The game's own palette: main (image 0x5D) loads DS:00CC via int 10h AX=1002h right after setting
# mode 0Dh and never changes it. Register values 00 01 02 03 04 05 07 16 00 10 06 12 13 14 11 17,
# shown as 200-line colours (bit 4 = intensity; 06 is brown).
EGA_PAL = [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170),
           (170, 170, 170), (255, 255, 85), (0, 0, 0), (85, 85, 85), (170, 85, 0),
           (85, 255, 85), (85, 255, 255), (255, 85, 85), (85, 85, 255), (255, 255, 255)]


def unrle_cmp(data):
    size, = struct.unpack_from('<I', data, 0)
    out = bytearray(data[:4])  # the size field is also the archive's own first field
    i = 4
    while i < len(data) and len(out) < size:
        b = data[i]
        if b == 0x83:
            out += bytes([data[i + 1]]) * data[i + 2]
            i += 3
        else:
            out.append(b)
            i += 1
    return bytes(out)


def unrle90(data):
    """ARC-style RLE: 0x90 nn repeats the previous byte nn-1 more times; 0x90 00 is a literal 0x90."""
    out = bytearray()
    last = 0
    i = 0
    while i < len(data):
        b = data[i]
        if b == 0x90 and i + 1 < len(data):
            n = data[i + 1]
            i += 2
            if n == 0:
                out.append(0x90)
            else:
                out += bytes([last]) * (n - 1)
        else:
            out.append(b)
            last = b
            i += 1
    return bytes(out)


def unlzw(src):
    """Unix compress 4.0 decoder as ported in TDEGA.EXE: codes are read n_bits bytes at a time."""
    maxbits = src[0]
    src = src[1:]
    pos = 0
    n_bits, maxcode, clear_flg, offset, size, buf = 9, 511, 0, 0, 0, b''
    free_ent = 257
    maxmaxcode = 1 << maxbits

    def getcode():
        nonlocal pos, n_bits, maxcode, clear_flg, offset, size, buf
        if clear_flg > 0 or offset >= size or free_ent > maxcode:
            if free_ent > maxcode:
                n_bits += 1
                maxcode = maxmaxcode if n_bits == maxbits else (1 << n_bits) - 1
            if clear_flg > 0:
                n_bits, maxcode, clear_flg = 9, 511, 0
            chunk = src[pos:pos + n_bits]
            pos += len(chunk)
            if not chunk:
                return -1
            buf = chunk + b'\0\0'
            offset = 0
            size = (len(chunk) << 3) - (n_bits - 1)
        v = int.from_bytes(buf[offset >> 3:(offset >> 3) + 3], 'little')
        code = (v >> (offset & 7)) & ((1 << n_bits) - 1)
        offset += n_bits
        return code

    prefix = [0] * maxmaxcode
    suffix = list(range(256)) + [0] * (maxmaxcode - 256)
    out = bytearray()
    oldcode = finchar = getcode()
    out.append(finchar)
    while True:
        code = getcode()
        if code < 0:
            break
        if code == 256:
            clear_flg = 1
            free_ent = 256
            code = getcode()
            if code < 0:
                break
        incode = code
        stack = []
        if code >= free_ent:
            stack.append(finchar)
            code = oldcode
        while code >= 256:
            stack.append(suffix[code])
            code = prefix[code]
        finchar = suffix[code]
        stack.append(finchar)
        out += bytes(reversed(stack))
        if free_ent < maxmaxcode:
            prefix[free_ent], suffix[free_ent] = oldcode, finchar
            free_ent += 1
        oldcode = incode
    return bytes(out)


def unsqueeze(src):
    """ARC 'squeezed': u16 node count, nodes of two s16 children (negative = leaf -(byte+1)), LSB-first bits."""
    numnodes, = struct.unpack_from('<H', src, 0)
    nodes = [struct.unpack_from('<hh', src, 2 + 4 * k) for k in range(numnodes)] or [(-257, -257)]
    pos = 2 + 4 * numnodes
    out = bytearray()
    bitpos, cur = 8, 0
    while True:
        i = 0
        while i >= 0:
            if bitpos > 7:
                if pos >= len(src):
                    return bytes(out)
                cur, pos, bitpos = src[pos], pos + 1, 0
            i = nodes[i][cur & 1]
            cur >>= 1
            bitpos += 1
        i = -(i + 1)
        if i == 256:
            return bytes(out)
        out.append(i)


def crc16_arc(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def unpack_pes(data):
    assert data[:4] == b'Pckd'
    _packed, unpacked, method, crc = struct.unpack_from('<IIHH', data, 4)
    if method == 8:
        stage = unlzw(data[16:])
    elif method == 4:
        stage = unsqueeze(data[16:])
    else:
        raise ValueError('unknown ARC method %d' % method)
    out = unrle90(stage)[:unpacked]
    return out, method, crc16_arc(out) == crc


def load_archive(path):
    data = open(path, 'rb').read()
    ega = data[:4] == b'Pckd'
    note = ''
    if ega:
        raw, method, crc_ok = unpack_pes(data)
        note = 'method %d, crc %s' % (method, 'ok' if crc_ok else 'MISMATCH')
    else:
        raw = unrle_cmp(data)
    total, count = struct.unpack_from('<IH', raw, 0)
    names = [raw[6 + 4 * k:10 + 4 * k].rstrip(b'\0').decode('latin-1') for k in range(count)]
    base = 6 + 8 * count
    offs = struct.unpack_from('<%dI' % count, raw, 6 + 4 * count)
    order = sorted(range(count), key=lambda k: offs[k])
    ends = {}
    for n, k in enumerate(order):
        ends[k] = offs[order[n + 1]] if n + 1 < len(order) else len(raw) - base
    res = [(names[k], raw[base + offs[k]:base + ends[k]]) for k in range(count)]
    return raw, total, res, ega, note


def sprite_info(blob, ega):
    if len(blob) < 16:
        return None
    w, h, hx, hy, x, y = struct.unpack_from('<4H2h', blob, 0)
    pmap = blob[12:16]
    planes = [b & 0x0F for b in pmap if b & 0x0F] if ega else [0]
    # High nibble of byte 0 clears colour planes, of byte 1 sets them (port/spec/platform.md).
    # Rendered onto black, only the "set" planes matter.
    const = pmap[1] >> 4
    if not w or not h or len(blob) != 16 + w * h * len(planes):
        return None
    return dict(w=w, h=h, hx=hx, hy=hy, x=x, y=y, planes=planes, const=const if ega else 0)


def render(blob, info, ega):
    from PIL import Image
    w, h = info['w'], info['h']
    px = np.frombuffer(blob, np.uint8, offset=16)
    if not ega:
        bits = np.unpackbits(px.reshape(h, w), axis=1).reshape(h, w * 4, 2)
        idx = bits[:, :, 0] * 2 + bits[:, :, 1]
        return Image.fromarray(np.array(CGA_PAL, np.uint8)[idx])
    idx = np.full((h, w * 8), info['const'], np.uint8)
    for k, mask in enumerate(info['planes']):
        bits = np.unpackbits(px[k * w * h:(k + 1) * w * h].reshape(h, w), axis=1)
        idx |= bits * mask
    return Image.fromarray(np.array(EGA_PAL, np.uint8)[idx])


def main():
    cmd, path = sys.argv[1], sys.argv[2]
    raw, total, res, ega, note = load_archive(path)
    print('%s: decoded %d, total field %d, %d resources %s' %
          (os.path.basename(path), len(raw), total, len(res), note))
    outdir = sys.argv[3] if cmd == 'export' else None
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    for name, blob in res:
        info = sprite_info(blob, ega)
        if cmd == 'info':
            print('  %-5s len=%5d %s' % (name, len(blob), info or blob[:16].hex(' ')))
        if outdir:
            safe = name.replace('\0', '_') or '_'
            open(os.path.join(outdir, safe + '.bin'), 'wb').write(blob)
            if info:
                render(blob, info, ega).save(os.path.join(outdir, safe + '.png'))


if __name__ == '__main__':
    main()
