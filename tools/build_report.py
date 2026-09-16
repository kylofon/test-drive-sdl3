"""Builds work/report/index.html from tools/report_template.html with inlined stage and car data."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def field(fields, *words):
    for key, f in fields.items():
        if all(w in key for w in words):
            return f['value']
    raise KeyError(words)


stages = json.load(open(os.path.join(ROOT, 'work', 'stages_compact.json')))
cars = []
for name in ('counta', 'lotus', 'p911t', 'rossa', 'vette'):
    c = json.load(open(os.path.join(ROOT, 'work', 'cars', name.upper() + '.json')))
    f = c['fields']
    dash = next((v['value'] for k, v in f.items() if 'gauge' in k or 'dash' in k), None)
    cars.append({
        'name': name,
        'full': c['full_name'],
        'gears': field(f, 'gears'),
        'rpm_limit': field(f, 'rpm', 'limit'),
        'grip': field(f, 'grip'),
        'torque': field(f, 'torque'),
        'dash': 'needles' if dash == 1 else 'digital',
    })

html = open(os.path.join(ROOT, 'tools', 'report_template.html'), encoding='utf-8').read()
html = html.replace('/*STAGES*/null', json.dumps(stages, separators=(',', ':')))
html = html.replace('/*CARS*/null', json.dumps(cars, separators=(',', ':')))
out_dir = os.path.join(ROOT, 'work', 'report')
os.makedirs(out_dir, exist_ok=True)
open(os.path.join(out_dir, 'index.html'), 'w', encoding='utf-8').write(html)

# Copy images next to the page so it also works when opened from disk (file://).
import shutil
IMAGES = {
    'testdrv.png': 'sheets/TESTDRV_PES.png', 'lotus_ega.png': 'sheets/LOTUS_PES.png',
    'lotus_cga.png': 'sheets/LOTUS_CMP.png', 'countasb.png': 'sheets/COUNTASB_PES.png',
    'xroada.png': 'sheets/XROADA_PES.png', 'xroadb.png': 'sheets/XROADB_PES.png',
    'gas.png': 'sheets/GAS_PES.png', 'route.png': 'route_map.png',
}
os.makedirs(os.path.join(out_dir, 'img'), exist_ok=True)
for dst, src in IMAGES.items():
    shutil.copyfile(os.path.join(ROOT, 'work', src), os.path.join(out_dir, 'img', dst))
print('wrote', os.path.join(out_dir, 'index.html'), len(html), 'bytes;', [(c['name'], c['gears'], c['rpm_limit'], len(c['torque']), c['dash']) for c in cars])
