"""Rename Ghidra's linear-address globals to DS offsets and build a globals cross-reference.

  iRam00023e18  -> i_DS7478     (linear 0x23E18 - DGROUP linear 0x1C9A0)
  LAB_1c9a_0929 -> DS_0929

usage: postprocess.py port/decomp/tdega.c   (writes tdega_ds.c and tdega_globals_xref.txt next to it)
"""
import os, re, sys
from collections import defaultdict

DG_LINEAR = 0x10000 + 0xC9A0  # load segment 0x1000 + DGROUP 0x0C9A, as linear address

src = sys.argv[1]
text = open(src, encoding='utf-8').read()


def ram(m):
    prefix, linear = m.group(1), int(m.group(2), 16)
    off = linear - DG_LINEAR
    if 0 <= off < 0x10000:
        return '%s_DS%04X' % (prefix, off)
    return m.group(0)


text = re.sub(r'\b([a-zA-Z]*)Ram000([0-9a-f]{5})\b', ram, text)
text = re.sub(r'\bLAB_1c9a_([0-9a-f]{4})\b', lambda m: 'DS_%s' % m.group(1).upper(), text)

xref = defaultdict(set)
current = None
for line in text.splitlines():
    m = re.match(r'// ==== (\S+)\s+image (0x[0-9a-f]+)', line)
    if m:
        current = '%s@%s' % (m.group(1), m.group(2))
        continue
    if current:
        for g in re.findall(r'\b[a-zA-Z]*_DS([0-9A-F]{4})\b|\bDS_([0-9A-F]{4})\b', line):
            xref[g[0] or g[1]].add(current)

out_dir = os.path.dirname(src)
base = os.path.splitext(os.path.basename(src))[0]
open(os.path.join(out_dir, base + '_ds.c'), 'w', encoding='utf-8').write(text)
with open(os.path.join(out_dir, base + '_globals_xref.txt'), 'w') as fh:
    for off in sorted(xref, key=lambda s: int(s, 16)):
        fns = sorted(xref[off])
        fh.write('DS:%s  %2d fns  %s\n' % (off, len(fns), ' '.join(fns)))
print('globals referenced:', len(xref), '->', base + '_ds.c, ' + base + '_globals_xref.txt')
