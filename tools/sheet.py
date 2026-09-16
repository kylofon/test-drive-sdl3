"""Contact sheets: one labelled PNG per archive with every sprite (scaled 2x, with 2:2.4 CGA/EGA pixel aspect)."""
import sys, os, glob
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(__file__))
import tdres

BG = (40, 44, 52)
MAX_W = 1400


def sheet(path, out_path):
    raw, total, res, ega, note = tdres.load_archive(path)
    tiles = []
    for name, blob in res:
        info = tdres.sprite_info(blob, ega)
        if not info:
            continue
        img = tdres.render(blob, info, ega)
        img = img.resize((img.width * 2, int(img.height * 2.4)), Image.NEAREST)
        tiles.append((name, img))
    if not tiles:
        return False
    pad, label_h = 8, 14
    rows, row, x, row_h = [], [], pad, 0
    for name, img in tiles:
        tw = max(img.width, 40)
        if row and x + tw + pad > MAX_W:
            rows.append((row, row_h)); row, x, row_h = [], pad, 0
        row.append((x, name, img)); x += tw + pad; row_h = max(row_h, img.height + label_h)
    rows.append((row, row_h))
    width = max(xx + max(im.width, 40) for r, _ in rows for xx, _, im in r) + pad
    height = sum(h + pad for _, h in rows) + pad + 20
    canvas = Image.new('RGB', (width, height), BG)
    d = ImageDraw.Draw(canvas)
    d.text((pad, 4), '%s  (%s, %d sprites) %s' % (os.path.basename(path), 'EGA' if ega else 'CGA', len(tiles), note),
           fill=(230, 230, 230))
    y = 24
    for r, h in rows:
        for xx, name, img in r:
            d.text((xx, y), name, fill=(200, 200, 120))
            canvas.paste(img, (xx, y + label_h))
        y += h + pad
    canvas.save(out_path)
    return True


if __name__ == '__main__':
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(sys.argv[1], '*.PES')) + glob.glob(os.path.join(sys.argv[1], '*.CMP'))):
        base = os.path.basename(p).replace('.', '_')
        if sheet(p, os.path.join(out, base + '.png')):
            print('sheet', base)
