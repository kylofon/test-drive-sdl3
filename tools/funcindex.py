"""Function index for an unpacked Test Drive executable.

Recursive-descent disassembly from the entry point plus every `push bp; mov bp,sp` prologue.
For each function: extent, callers/callees, DS globals read/written, DS strings referenced,
interrupts and port I/O. Writes port/functions.json and port/functions.csv.

usage: funcindex.py work/TDEGA_unp.exe 0xC9A0
"""
import json, os, re, struct, sys
from collections import defaultdict
from capstone import Cs, CS_ARCH_X86, CS_MODE_16
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_REG_INVALID

exe, ds_base = sys.argv[1], int(sys.argv[2], 16)
d = open(exe, 'rb').read()
img = d[struct.unpack_from('<H', d, 8)[0] * 16:]
entry_ip = struct.unpack_from('<H', d, 0x14)[0]
code_end = ds_base

md = Cs(CS_ARCH_X86, CS_MODE_16)
md.detail = True


def string_at(off):
    p = ds_base + off
    if not (ds_base <= p < len(img)) or (p > ds_base and img[p - 1] != 0):
        return None  # only accept offsets where a zero-terminated string starts
    m = re.match(rb'[\x20-\x7e\r\n]{4,}', img[p:p + 80])
    if m and (p + len(m.group(0)) < len(img)) and img[p + len(m.group(0))] == 0:
        return m.group(0).decode('latin-1')
    return None


insn_at = {}
seeds = {entry_ip} | {m.start() for m in re.finditer(rb'\x55\x8b\xec', img[:code_end])}
call_targets = set()
work = list(seeds)
seen = set()
while work:
    a = work.pop()
    while 0 <= a < code_end and a not in seen:
        chunk = img[a:a + 8]
        ins = next(md.disasm(chunk, a), None)
        if ins is None:
            break
        seen.add(a)
        insn_at[a] = ins
        mn = ins.mnemonic
        tgt = None
        if ins.operands and ins.operands[0].type == X86_OP_IMM and (mn == 'call' or mn.startswith('j') or mn == 'loop'):
            tgt = ins.operands[0].imm & 0xFFFF
        if mn == 'call' and tgt is not None:
            call_targets.add(tgt)
            work.append(tgt)
        elif mn.startswith('j') or mn.startswith('loop'):
            if tgt is not None:
                work.append(tgt)
            if mn == 'jmp':
                break
        if mn in ('ret', 'retf', 'iret', 'ljmp') or (mn == 'int' and ins.op_str == '0x20'):
            break
        a += ins.size

starts = sorted((seeds | call_targets) & set(insn_at))
funcs = {}
for i, s in enumerate(starts):
    nxt = starts[i + 1] if i + 1 < len(starts) else code_end
    f = dict(start=s, end=s, insns=0, calls=set(), callers=set(), reads=set(), writes=set(),
             strings={}, ints=set(), ports=set(), imm16=set(), indirect_calls=0, prologue=img[s:s + 3] == b'\x55\x8b\xec')
    funcs[s] = f
    a = s
    for addr in sorted(k for k in insn_at if s <= k < nxt):
        ins = insn_at[addr]
        f['insns'] += 1
        f['end'] = addr + ins.size
        mn = ins.mnemonic
        if mn == 'call':
            op = ins.operands[0]
            if op.type == X86_OP_IMM:
                f['calls'].add(op.imm & 0xFFFF)
            else:
                f['indirect_calls'] += 1
        if mn == 'int':
            f['ints'].add(ins.op_str)
        if mn in ('in', 'out'):
            f['ports'].add(ins.op_str)
        for k, op in enumerate(ins.operands):
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_INVALID and op.mem.index == X86_REG_INVALID \
                    and op.mem.segment in (X86_REG_INVALID,):
                disp = op.mem.disp & 0xFFFF
                written = k == 0 and mn in ('mov', 'add', 'sub', 'inc', 'dec', 'and', 'or', 'xor', 'adc', 'sbb',
                                            'shl', 'shr', 'sar', 'neg', 'not', 'pop', 'xchg', 'rol', 'ror')
                (f['writes'] if written else f['reads']).add(disp)
            if op.type == X86_OP_IMM and mn in ('mov', 'push'):
                v = op.imm & 0xFFFF
                sv = string_at(v)
                if sv:
                    f['strings'][v] = sv
                elif v >= 0x100:
                    f['imm16'].add(v)

for s, f in funcs.items():
    for c in f['calls']:
        if c in funcs:
            funcs[c]['callers'].add(s)

out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'port')
os.makedirs(out_dir, exist_ok=True)
tag = os.path.basename(exe).split('_')[0].lower()
h = lambda v: '%04x' % v
js = []
for s in starts:
    f = funcs[s]
    js.append(dict(start=h(s), end=h(f['end']), insns=f['insns'], prologue=f['prologue'],
                   calls=[h(c) for c in sorted(f['calls'])], callers=[h(c) for c in sorted(f['callers'])],
                   indirect_calls=f['indirect_calls'],
                   ds_reads=[h(v) for v in sorted(f['reads'])], ds_writes=[h(v) for v in sorted(f['writes'])],
                   strings={h(k): v for k, v in sorted(f['strings'].items())},
                   ints=sorted(f['ints']), ports=sorted(f['ports'])))
json.dump(js, open(os.path.join(out_dir, tag + '_functions.json'), 'w'), indent=1)
with open(os.path.join(out_dir, tag + '_functions.csv'), 'w') as fh:
    fh.write('start,end,insns,n_callers,n_calls,ints,ports,strings\n')
    for f in js:
        fh.write('%s,%s,%d,%d,%d,%s,%s,"%s"\n' % (f['start'], f['end'], f['insns'], len(f['callers']), len(f['calls']),
                 ' '.join(f['ints']), ' '.join(f['ports']), ' | '.join(f['strings'].values()).replace('"', "'")[:160]))
print('%s: %d functions, %d instructions decoded, %.0f%% of code bytes covered' %
      (tag, len(js), len(insn_at), 100 * sum(i.size for i in insn_at.values()) / code_end))
