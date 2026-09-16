"""Cross-build address map: TDEGA.EXE -> TDCGA.EXE.

Both games are the same Microsoft C source linked with a different graphics layer, in the same order.
The script linearly disassembles the game-code region (EGA 0x0010-0x4941, CGA 0x0010-0x4857) and the
platform region (up to DGROUP) of both images, aligns the address-masked instruction streams and
records, from aligned runs of at least MIN_RUN instructions, every pair of addresses:

  func  EGA image offset -> CGA image offset   (call targets, aligned function starts)
  ds    EGA DS offset    -> CGA DS offset      (direct memory operands, [reg+disp] tables)
  cs    code-segment variables (asm)
  imm   pushed/moved immediates that differ    (DGROUP pointers are mapped; others are listed)

It also lists the unaligned stretches of the game-code region: those are the places where the CGA
build's game code differs and the port needs a build conditional.

usage: xmap.py        writes port/cga/xmap.json, port/cga/game_diffs.txt and port/cga/symbols_cga.csv
"""
import csv, difflib, json, os, struct
from collections import Counter, defaultdict
from capstone import Cs, CS_ARCH_X86, CS_MODE_16
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG, X86_REG_INVALID, X86_REG_BP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EGA = dict(exe='work/TDEGA_unp.exe', ds=0xC9A0, game_end=0x4941, funcs='port/tdega_functions.json')
CGA = dict(exe='work/TDCGA_unp.exe', ds=0xA8A0, game_end=0x4857, funcs='port/tdcga_functions.json')
MIN_RUN = 4
EDGE = 8        # votes from within EDGE instructions of an alignment boundary count less

# Verified by hand where the alignment is misled by nearby build differences (EGA DS -> CGA DS).
# CGA loads a single traffic archive (XROADB.CMP): sim_setup's xroadA list reads DS:CF8A.
DS_OVERRIDES = {
    0x7B1C: 0xCF8A, 0x7B1E: 0xCF8C,   # g_xroadA (main loads it in the CGA build)
    0x7B2A: 0xCF98, 0x7B2C: 0xCF9A,   # g_songHiScore (sng3)
    # Only referenced where the builds differ, or through ds:[bp+disp] (not voted); verified in the listings.
    0x08C0: 0x08C0,                   # marker_save_sprite (CGA 0x3606: mov cx, 0x8c0)
    0x13DB: 0x13AE, 0x13DD: 0x13B0,   # spr_roof (CGA run_stage 0x1D89)
    0x1B23: 0x1AF6,                   # row_cx            (CGA 0x28E2)
    0x1D03: 0x1CD6,                   # row_obj           (CGA 0x205E)
    0x1E43: 0x1E16,                   # row_cx_mirror     (CGA 0x2F8E)
    0x1FAB: 0x1F7E,                   # row_obj_mirror    (CGA 0x2491)
    0x21A5: 0x2178,                   # road_halfwidth_q4 (CGA 0x218A)
    0x2247: 0x221A,                   # row_depth_Z       (CGA 0x211F)
}
md = Cs(CS_ARCH_X86, CS_MODE_16)
md.detail = True


def load_img(b):
    d = open(os.path.join(ROOT, b['exe']), 'rb').read()
    return d[struct.unpack_from('<H', d, 8)[0] * 16:]


def tokens(ins):
    """(skeleton, addrs): skeleton masks addresses; addrs lists (kind, value) in operand order."""
    parts, addrs = [ins.mnemonic], []
    branch = ins.mnemonic == 'call' or ins.mnemonic.startswith('j') or ins.mnemonic.startswith('loop')
    for op in ins.operands:
        if op.type == X86_OP_REG:
            parts.append(ins.reg_name(op.reg))
        elif op.type == X86_OP_IMM:
            v = op.imm & 0xFFFF
            if branch:
                parts.append('T')
                addrs.append(('func' if ins.mnemonic == 'call' else 'jmp', v))
            else:
                parts.append('I%d' % op.size)
                addrs.append(('imm', v))
        elif op.type == X86_OP_MEM:
            m = op.mem
            base = ins.reg_name(m.base) if m.base != X86_REG_INVALID else ''
            idx = ins.reg_name(m.index) if m.index != X86_REG_INVALID else ''
            seg = ins.reg_name(m.segment) if m.segment != X86_REG_INVALID else ''
            if m.base == X86_REG_BP and not idx:
                parts.append('M%d[%s%s%+d]' % (op.size, seg, base, m.disp))     # stack frame: keep
            elif not base and not idx:
                parts.append('M%d[%s:D]' % (op.size, seg))
                addrs.append(('cs' if seg == 'cs' else 'mem', m.disp & 0xFFFF))
            else:
                parts.append('M%d[%s:%s+%s+X]' % (op.size, seg, base, idx))
                addrs.append(('csdisp' if seg == 'cs' else 'disp', m.disp & 0xFFFF))
    return ' '.join(parts), addrs


def linear(img, a, b):
    out = []
    while a < b:
        ins = next(md.disasm(img[a:a + 8], a), None)
        if ins is None:
            a += 1
            continue
        sk, ad = tokens(ins)
        out.append((ins.address, sk, ad, '%s %s' % (ins.mnemonic, ins.op_str)))
        a += ins.size
    return out


def align(le, lc):
    sm = difflib.SequenceMatcher(None, [x[1] for x in le], [x[1] for x in lc], autojunk=False)
    return sm


def main():
    ei, ci = load_img(EGA), load_img(CGA)
    efuncs = [int(f['start'], 16) for f in json.load(open(os.path.join(ROOT, EGA['funcs'])))]
    cfuncs = [int(f['start'], 16) for f in json.load(open(os.path.join(ROOT, CGA['funcs'])))]
    sym_funcs = [int(r['address'], 16) for r in csv.DictReader(open(os.path.join(ROOT, 'port', 'symbols.csv')))
                 if r['kind'] == 'func']
    efuncs = sorted(set(efuncs) | set(sym_funcs))
    regions = [(0x10, EGA['game_end'], 0x10, CGA['game_end']),
               (EGA['game_end'], EGA['ds'], CGA['game_end'], CGA['ds'])]
    votes = defaultdict(Counter)
    addr_pair = {}
    diffs = []
    imm_diff = []
    call_sites = []                 # (ega site, cga site, ega target, cga target) in the game-code region
    for ri, (ea, eb, ca, cb) in enumerate(regions):
        le, lc = linear(ei, ea, eb), linear(ci, ca, cb)
        sm = align(le, lc)
        for tag, a1, a2, b1, b2 in sm.get_opcodes():
            if tag == 'equal':
                if a2 - a1 < MIN_RUN:
                    continue
                for k in range(a2 - a1):
                    e, c = le[a1 + k], lc[b1 + k]
                    wt = 1 + min(k, a2 - a1 - 1 - k, EDGE)
                    addr_pair[e[0]] = c[0]
                    for (k1, v1), (k2, v2) in zip(e[2], c[2]):
                        if k1 == 'func':
                            votes[('func', v1)][v2] += wt
                            if ri == 0:
                                call_sites.append((e[0], c[0], v1, v2))
                        elif k1 in ('mem', 'disp'):
                            votes[('ds', v1)][v2] += wt
                        elif k1 in ('cs', 'csdisp'):
                            votes[('cs', v1)][v2] += wt
                        elif k1 == 'imm' and v1 != v2:
                            imm_diff.append((e[0], c[0], v1, v2, e[3]))
                            votes[('imm', v1)][v2] += wt
            elif ri == 0:
                diffs.append((le[a1][0] if a1 < len(le) else eb, a2 - a1, lc[b1][0] if b1 < len(lc) else cb, b2 - b1,
                              [x[3] for x in le[a1:a2]], [x[3] for x in lc[b1:b2]]))

    func_map = {}                   # call targets are the strongest evidence, aligned starts fill the gaps
    for (k, v), cnt in votes.items():
        if k == 'func':
            tgt, n = cnt.most_common(1)[0]
            func_map[v] = (tgt, 'called, weight %d' % n)
    for s in efuncs:
        if s in addr_pair and s not in func_map:
            func_map[s] = (addr_pair[s], 'aligned')
    ds_map = {}
    for (k, v), cnt in votes.items():
        if k == 'ds':
            tgt, n = cnt.most_common(1)[0]
            ds_map[v] = (tgt, n, 'mem', len(cnt))
    for (k, v), cnt in votes.items():      # pushed DGROUP pointers (strings, tables) not seen as operands
        if k == 'imm' and v not in ds_map and v >= 0x40:
            tgt, n = cnt.most_common(1)[0]
            ds_map[v] = (tgt, n, 'imm', len(cnt))
    for k, v in DS_OVERRIDES.items():
        ds_map[k] = (v, 0, 'manual', 1)
    taken = defaultdict(list)
    for k, v in ds_map.items():
        taken[v[0]].append(k)
    for v, ks in taken.items():                # a CGA offset claimed twice: keep the best-supported one
        if len(ks) > 1:
            ks.sort(key=lambda k: (ds_map[k][2] == 'manual', ds_map[k][1]), reverse=True)
            for k in ks[1:]:
                if ds_map[k][2] != 'manual':
                    del ds_map[k]
    cs_map = {v: cnt.most_common(1)[0][0] for (k, v), cnt in votes.items() if k == 'cs'}

    out = os.path.join(ROOT, 'port', 'cga')
    os.makedirs(out, exist_ok=True)
    mapped_c = {v[0] for v in func_map.values()}
    json.dump(dict(
        functions={'%04x' % k: dict(cga='%04x' % v[0], how=v[1]) for k, v in sorted(func_map.items())},
        unmatched_ega=['%04x' % s for s in efuncs if s not in func_map],
        unmatched_cga=['%04x' % s for s in cfuncs if s not in mapped_c],
        ds={'%04x' % k: dict(cga='%04x' % v[0], votes=v[1], kind=v[2], alternatives=v[3]) for k, v in sorted(ds_map.items())},
        cs={'%04x' % k: '%04x' % v for k, v in sorted(cs_map.items())},
        imm_diff=['%05x %05x %04x->%04x  %s' % x for x in imm_diff],
    ), open(os.path.join(out, 'xmap.json'), 'w'), indent=1)
    with open(os.path.join(out, 'call_swaps.txt'), 'w') as fh:
        fh.write('Game-code calls whose CGA target is not the usual image of the EGA target\n'
                 '(EGA site, CGA site, EGA target -> CGA target, usual CGA image of the EGA target)\n')
        for es, cs, et, ct in call_sites:
            if func_map.get(et, (None,))[0] != ct:
                fh.write('%05x %05x  %04x -> %04x   usual %s\n' % (es, cs, et, ct,
                         '%04x' % func_map[et][0] if et in func_map else '-'))
    with open(os.path.join(out, 'game_diffs.txt'), 'w') as fh:
        fh.write('Unaligned stretches of the game-code region (EGA | CGA)\n')
        for ea, na, ca, nc, el, cl in diffs:
            fh.write('\n== EGA %05x (%d insns)  |  CGA %05x (%d insns)\n' % (ea, na, ca, nc))
            for k in range(max(len(el), len(cl))):
                fh.write('  %-44s | %s\n' % (el[k] if k < len(el) else '', cl[k] if k < len(cl) else ''))

    rows = []
    for r in csv.DictReader(open(os.path.join(ROOT, 'port', 'symbols.csv'))):
        a = r['address']
        if r['kind'] == 'func':
            v = func_map.get(int(a, 16))
            cga = '0x%04X' % v[0] if v else ''
        else:
            v = ds_map.get(int(a.split(':')[1], 16))
            cga = 'DS:%04X' % v[0] if v else ''
        rows.append(dict(r, cga=cga))
    with open(os.path.join(out, 'symbols_cga.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    nf = sum(1 for r in rows if r['kind'] == 'func')
    print('game-code diff stretches %d; functions mapped %d/%d; symbols mapped: %d/%d funcs, %d/%d globals' % (
        len(diffs), len(func_map), len(efuncs),
        sum(1 for r in rows if r['kind'] == 'func' and r['cga']), nf,
        sum(1 for r in rows if r['kind'] != 'func' and r['cga']), len(rows) - nf))


if __name__ == '__main__':
    main()
