"""Merge port/spec/*_symbols.csv into port/symbols.csv and report naming conflicts.

Also writes port/symbols_ghidra.txt ("func 2054 name" / "global 18C5 name" lines) for
tools/ghidra/ApplySymbols.java.
"""
import csv, glob, os, re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = defaultdict(list)  # (kind, addr) -> [(spec, name, type, notes)]

for path in sorted(glob.glob(os.path.join(ROOT, 'port', 'spec', '*_symbols.csv'))):
    spec = os.path.basename(path)[:-len('_symbols.csv')]
    with open(path, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            kind = (r.get('kind') or '').strip().lower()
            addr = (r.get('address') or '').strip().upper().replace('0X', '')
            addr = addr.replace('DS:', '')
            name = re.sub(r'\W', '_', (r.get('name') or '').strip())
            if kind not in ('func', 'global') or not re.fullmatch(r'[0-9A-F]{1,5}', addr) or not name:
                continue
            rows[(kind, int(addr, 16))].append((spec, name, (r.get('type') or '').strip(), (r.get('notes') or '').strip()))

RANGES = [('game_flow', 0x0000, 0x1F4E), ('scene_render', 0x1F4E, 0x3B00),
          ('simulation', 0x3B00, 0x4941), ('platform', 0x4941, 0xC9A0)]  # from port/RE_GUIDE.md


def pick(kind, addr, entries):
    """Functions: the spec owning the address range wins. Globals: most common name, then longest notes."""
    if kind == 'func':
        owner = next((r[0] for r in RANGES if r[1] <= addr < r[2]), None)
        for e in entries:
            if e[0] == owner:
                return e
    return max(entries, key=lambda e: (sum(1 for x in entries if x[1] == e[1]), len(e[3])))


conflicts = []
with open(os.path.join(ROOT, 'port', 'symbols.csv'), 'w', newline='', encoding='utf-8') as out, \
        open(os.path.join(ROOT, 'port', 'symbols_ghidra.txt'), 'w') as gh:
    w = csv.writer(out)
    w.writerow(['kind', 'address', 'name', 'type', 'owner', 'other_names', 'notes'])
    for (kind, addr), entries in sorted(rows.items()):
        names = sorted({e[1] for e in entries})
        best = pick(kind, addr, entries)
        if len(names) > 1:
            conflicts.append((kind, addr, entries))
        a = ('0x%04X' % addr) if kind == 'func' else ('DS:%04X' % addr)
        w.writerow([kind, a, best[1], best[2], best[0], ' '.join(n for n in names if n != best[1]),
                    ' | '.join(e[3] for e in entries if e[3])])
        gh.write('%s %04X %s\n' % (kind, addr, best[1]))

with open(os.path.join(ROOT, 'port', 'symbol_conflicts.txt'), 'w', encoding='utf-8') as fh:
    for kind, addr, entries in conflicts:
        fh.write('%s %04X: %s\n' % (kind, addr, '; '.join('%s=%s' % (e[0], e[1]) for e in entries)))

print('%d symbols (%d funcs, %d globals), %d with conflicting names' % (
    len(rows), sum(1 for k in rows if k[0] == 'func'), sum(1 for k in rows if k[0] == 'global'), len(conflicts)))
