"""Amiga Test Drive (`td`, Manx Aztec C, small code/data model): disassembly and function index.

    python tools/amigaidx.py TD index OUT_PREFIX     -> OUT_PREFIX.json / OUT_PREFIX.csv
    python tools/amigaidx.py TD dis ADDR [LEN]       -> disassembly with calls and globals named
    python tools/amigaidx.py TD map                  -> hunk bases, A4, the call table

Addresses are those of `tools/hunk.py image` (base 0x10000; root code hunk 0 at 0x10000, data hunk 1
at 0x17C10, overlays laid out after the root as if all were loaded).

Model (see port/amiga/README.md):
* A4 = data hunk + 0x7FFE. Globals are d16(A4); they are named `D:xxxx`, the offset in the data hunk
  (initialised data 0x0000-0x1E93, then its BSS part up to 0x32A3).
* Calls between modules go through the call table at the start of the data hunk: `jsr d16(A4)` hits
  either a 6-byte `jmp abs.l` (root functions) or an 8-byte overlay stub `bsr ovlmgr ; dc.w node<<8,
  offset`, which loads overlay `node` (1 = hunk 3, 2 = hunk 4) and jumps to that offset in it.
* Within a module, calls are `jsr d16(pc)` / `bsr`. Library calls are `jsr d16(A6)` (LVO offsets).
"""
import csv
import json
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

from capstone import CS_ARCH_M68K, CS_MODE_BIG_ENDIAN, CS_MODE_M68K_000, Cs
from capstone.m68k import (M68K_AM_PCI_DISP, M68K_AM_REGI_ADDR_DISP, M68K_OP_IMM, M68K_OP_MEM,
                           M68K_REG_A4, M68K_REG_A6)

sys.path.insert(0, str(Path(__file__).parent))
import hunk  # noqa: E402

BASE = 0x10000
WRITES = {"move", "movea", "clr", "add", "adda", "addq", "addi", "addx", "sub", "suba", "subq", "subi",
          "subx", "and", "andi", "or", "ori", "eor", "eori", "neg", "negx", "not", "lsl", "lsr", "asl",
          "asr", "rol", "ror", "roxl", "roxr", "st", "sf", "seq", "sne", "bset", "bclr", "bchg", "moveq",
          "lea", "exg", "swap", "ext", "tas", "mulu", "muls", "divu", "divs", "nbcd", "abcd", "sbcd"}


class Td:
    def __init__(self, path):
        self.hunks, self.overlay_table = hunk.load(path)
        self.img, self.bases = hunk.image(self.hunks, BASE)
        self.data = self.bases[1]
        self.a4 = self.data + 0x7FFE
        self.md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN | CS_MODE_M68K_000)
        self.md.detail = True
        self._call_table()

    def rd(self, addr, n):
        return self.img[addr - BASE:addr - BASE + n]

    def w(self, addr):
        return struct.unpack(">H", self.rd(addr, 2))[0]

    def l(self, addr):
        return struct.unpack(">L", self.rd(addr, 4))[0]

    def hunk_of(self, addr):
        for i, (h, b) in enumerate(zip(self.hunks, self.bases)):
            if b <= addr < b + h.size:
                return i
        return None

    def code_ranges(self):
        return [(b, b + h.size) for h, b in zip(self.hunks, self.bases) if h.kind == "CODE"]

    def _call_table(self):
        """slot address -> (target, description) for the jump table and overlay stubs."""
        self.jt = {}
        a = self.data
        while self.w(a) == 0x4EF9:
            self.jt[a] = self.l(a + 2)
            a += 6
        self.jt_end_plain = a
        # overlay stubs: bsr.w ovlmgr ; dc.w node<<8 ; dc.w offset  (slots start 2 bytes on)
        a += 2
        self.ovl_stubs = {}
        while self.w(a) == 0x6100:
            node, off = self.rd(a + 4, 1)[0], self.w(a + 6)
            hunk_index = 2 + node
            self.ovl_stubs[a] = (node, off)
            self.jt[a] = self.bases[hunk_index] + off
            a += 8
        self.ovlmgr = a  # the stubs' bsr lands on "jmp ovlmgr" right after them

    def g(self, disp):
        return f"D:{self.a4 + disp - self.data:04X}"

    def string_at(self, addr):
        """A zero-terminated string starting at addr: in the data hunk, or a literal in code that
        is referenced PC-relative."""
        h = self.hunk_of(addr)
        if h is None or addr - self.bases[h] >= len(self.hunks[h].data):
            return None
        if h == 1 and addr > self.data and self.img[addr - BASE - 1] != 0:
            return None  # inside another string
        m = re.match(rb"[\x20-\x7e\n\t%]{3,}", self.rd(addr, 100))
        if m and self.img[addr - BASE + len(m.group(0))] == 0:
            return m.group(0).decode("latin-1")
        return None

    def insn(self, addr):
        ins = next(self.md.disasm(self.rd(addr, 12), addr), None)
        if ins is None or ins.id == 0:  # capstone's data pseudo-instruction
            return None
        return ins

    def target(self, ins):
        """Direct call/branch target of ins, resolving the A4 call table."""
        mn = ins.mnemonic.split(".")[0]
        if not (mn in ("bsr", "jsr", "jmp", "bra", "dbra") or mn.startswith("b") or mn.startswith("db")):
            return None
        ops = ins.operands
        if not ops:
            return None
        op = ops[-1]
        if op.type == M68K_OP_IMM and mn not in ("jsr", "jmp"):
            return op.imm
        if op.type == M68K_OP_MEM:
            m = op.mem
            if op.address_mode == M68K_AM_PCI_DISP:
                return ins.address + 2 + m.disp
            if op.address_mode == M68K_AM_REGI_ADDR_DISP and m.base_reg == M68K_REG_A4:
                return self.jt.get(self.a4 + m.disp)
        # capstone prints bsr/bra targets as immediates in op_str
        mt = re.search(r"\$([0-9a-f]+)$", ins.op_str)
        if mt and mn.startswith("b"):
            return int(mt.group(1), 16)
        return None

    def annotate(self, ins):
        notes = []
        for op in ins.operands:
            if op.type == M68K_OP_MEM and op.address_mode == M68K_AM_REGI_ADDR_DISP:
                if op.mem.base_reg == M68K_REG_A4:
                    a = self.a4 + op.mem.disp
                    if a in self.jt:
                        notes.append(f"-> {self.jt[a]:06x}")
                    else:
                        notes.append(self.g(op.mem.disp))
                        s = self.string_at(a)
                        if s:
                            notes.append(repr(s))
                elif op.mem.base_reg == M68K_REG_A6 and ins.mnemonic == "jsr":
                    notes.append(f"LVO {op.mem.disp}")
            elif op.type == M68K_OP_MEM and op.address_mode == M68K_AM_PCI_DISP and ins.mnemonic.split(".")[0] in ("lea", "pea"):
                s = self.string_at(ins.address + 2 + op.mem.disp)
                if s:
                    notes.append(repr(s))
        t = self.target(ins)
        if t is not None and ins.mnemonic.split(".")[0] in ("jsr", "bsr") and not any(n.startswith("->") for n in notes):
            notes.append(f"-> {t:06x}")
        return notes


def index(td):
    ranges = td.code_ranges()

    def in_code(a):
        return any(s <= a < e for s, e in ranges)

    entry = td.l(BASE) and BASE + 2 + struct.unpack(">h", td.rd(BASE + 2, 2))[0]
    seeds = {entry} | set(td.jt.values())
    for s, e in ranges:
        for a in range(s, e, 2):
            if td.w(a) == 0x4E55:  # link a5
                seeds.add(a)
    seen, insn_at, calls = set(), {}, set()
    work = list(seeds)
    while work:
        a = work.pop()
        while in_code(a) and a not in seen:
            ins = td.insn(a)
            if ins is None:
                break
            seen.add(a)
            insn_at[a] = ins
            mn = ins.mnemonic.split(".")[0]
            t = td.target(ins)
            if t is not None and in_code(t):
                if mn in ("jsr", "bsr"):
                    calls.add(t)
                work.append(t)
            if mn in ("rts", "rte", "jmp", "bra") or mn == "illegal":
                break
            a += ins.size
    starts = sorted((seeds | calls) & set(insn_at))
    funcs = []
    for i, s in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else None
        hs = td.hunk_of(s)
        a, n = s, 0
        body = []
        while a in insn_at and (nxt is None or a < nxt) and td.hunk_of(a) == hs:
            body.append(insn_at[a])
            a += insn_at[a].size
            n += 1
        f = {"start": f"{s:06x}", "end": f"{a:06x}", "hunk": hs, "insns": n,
             "link": td.w(s) == 0x4E55, "calls": set(), "reads": set(), "writes": set(),
             "strings": {}, "lvo": set(), "ints": set()}
        for ins in body:
            t = td.target(ins)
            if t is not None and ins.mnemonic.split(".")[0] in ("jsr", "bsr"):
                f["calls"].add(f"{t:06x}")
            for k, op in enumerate(ins.operands):
                if op.type == M68K_OP_MEM and op.address_mode == M68K_AM_REGI_ADDR_DISP:
                    if op.mem.base_reg == M68K_REG_A4 and td.a4 + op.mem.disp not in td.jt:
                        name = td.g(op.mem.disp)
                        s_ = td.string_at(td.a4 + op.mem.disp)
                        if s_:
                            f["strings"][name] = s_
                        elif ins.mnemonic.split(".")[0] in ("lea", "pea"):
                            f["reads"].add(name)
                        elif k == len(ins.operands) - 1 and ins.mnemonic.split(".")[0] in WRITES \
                                and len(ins.operands) > 1 or ins.mnemonic.split(".")[0] in ("clr", "st", "sf", "neg", "not"):
                            f["writes"].add(name)
                        else:
                            f["reads"].add(name)
                    elif op.mem.base_reg == M68K_REG_A6 and ins.mnemonic == "jsr":
                        f["lvo"].add(op.mem.disp)
                elif op.type == M68K_OP_MEM and op.address_mode == M68K_AM_PCI_DISP                         and ins.mnemonic.split(".")[0] in ("lea", "pea"):
                    a_ = ins.address + 2 + op.mem.disp
                    s_ = td.string_at(a_)
                    if s_:
                        f["strings"][f"{a_:06x}"] = s_
                elif op.type == M68K_OP_IMM and abs(op.imm) > 8 and ins.mnemonic.split(".")[0] != "link":
                    f["ints"].add(op.imm)
        funcs.append(f)
    callers = defaultdict(set)
    for f in funcs:
        for c in f["calls"]:
            callers[c].add(f["start"])
    for f in funcs:
        f["callers"] = sorted(callers[f["start"]])
        for k in ("calls", "reads", "writes", "lvo", "ints"):
            f[k] = sorted(f[k])
    return funcs


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    td = Td(sys.argv[1])
    cmd = sys.argv[2]
    if cmd == "map":
        for i, (h, b) in enumerate(zip(td.hunks, td.bases)):
            print(f"hunk {i} {h.kind}{' overlay' if h.overlay else ''} {b:06x}-{b + h.size:06x}")
        print(f"A4 = {td.a4:06x}; call table {td.data:06x}-{td.jt_end_plain:06x} (jmp), overlay stubs up to "
              f"{td.ovlmgr:06x}, overlay manager jump at {td.ovlmgr:06x}")
        for slot, t in td.jt.items():
            extra = ""
            if slot in td.ovl_stubs:
                node, off = td.ovl_stubs[slot]
                extra = f" (overlay {node} +{off:04x})"
            print(f"  jsr {slot - td.a4:#x}(a4)  slot {slot:06x} -> {t:06x}{extra}")
    elif cmd == "dis":
        a = int(sys.argv[3], 16)
        end = a + (int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x100)
        while a < end:
            ins = td.insn(a)
            if ins is None:
                print(f"{a:06x}: {td.w(a):04x}  dc.w")
                a += 2
                continue
            notes = td.annotate(ins)
            print(f"{a:06x}: {ins.bytes.hex():20} {ins.mnemonic:8} {ins.op_str:32}"
                  f"{'  ; ' + ', '.join(notes) if notes else ''}")
            a += ins.size
    elif cmd == "index":
        funcs = index(td)
        out = Path(sys.argv[3])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".json").write_text(json.dumps(funcs, indent=1))
        with open(out.with_suffix(".csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["start", "end", "hunk", "insns", "link", "ncalls", "ncallers", "strings"])
            for f in funcs:
                w.writerow([f["start"], f["end"], f["hunk"], f["insns"], int(f["link"]), len(f["calls"]),
                            len(f["callers"]), " | ".join(f["strings"].values())[:200]])
        print(f"{len(funcs)} functions")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
