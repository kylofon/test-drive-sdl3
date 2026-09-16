"""16-bit x86 helpers for unpacked MZ images.
  dis.py EXE find <hex bytes>          -> image offsets of byte pattern
  dis.py EXE dis <image_off hex> <len> -> disassembly (addresses are image offsets)
"""
import struct, sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_16


def load(path):
    d = open(path, 'rb').read()
    hdr = struct.unpack_from('<H', d, 8)[0] * 16
    return d[hdr:]


def main():
    img = load(sys.argv[1])
    cmd = sys.argv[2]
    if cmd == 'find':
        pat = bytes.fromhex(''.join(sys.argv[3:]))
        i = img.find(pat)
        while i >= 0:
            print('%05x' % i)
            i = img.find(pat, i + 1)
    elif cmd == 'dis':
        start, n = int(sys.argv[3], 16), int(sys.argv[4], 0)
        md = Cs(CS_ARCH_X86, CS_MODE_16)
        for ins in md.disasm(img[start:start + n], start):
            print('%05x  %-20s %s %s' % (ins.address, ins.bytes.hex(), ins.mnemonic, ins.op_str))


if __name__ == '__main__':
    main()
