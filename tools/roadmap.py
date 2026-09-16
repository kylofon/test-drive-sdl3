"""Test Drive (1987) road layout extractor / route map renderer.

Data (TDEGA_unp.exe, DGROUP = image 0xC9A0):
  DS:0x2B70  record table, 0x6E entries x 4 bytes  [flag, curve, pitch, object]
  DS:0x2D28..0x6360  road byte stream, one byte per road unit, 5 stages, each ends with 0xFF
  DS:0x6361  5 x u16 stage start offsets (DS-relative); game starts at start+0x2D

Renderer (0x2054, forward view; 0x2480 = mirror view, walks backwards):
  per visible row (40 rows, 1 stream byte each):
    rec = table[byte]
    heading += (s8)rec.curve * 64      (8.8 fixed, high byte = degrees; clamped +-75 deg)
    x       += sin15(heading>>8) * 2
    slope   += (s8)rec.pitch * 4       (8.8 degrees)
    y       += sin15(slope>>8)
    objrow  = rec.object               (bit 0x80 = other side for signs)
So the map is built by integrating curve (deg/4 per unit) and pitch (deg/64 per unit).

usage: python tools/roadmap.py [work/TDEGA_unp.exe]
  -> work/road.json, work/route_map.png, work/elevation.png
"""
import json
import math
import os
import struct
import sys

from PIL import Image, ImageDraw

DS_IMG = 0xC9A0
TABLE = 0x2B70
NREC = 0x6E
STAGE_PTRS = 0x6361
NSTAGES = 5
START_SKIP = 0x2D

SIGNS = {2: 'right-turn sign', 3: 'left-turn sign', 4: 'two-way-traffic sign',
         5: 'speed limit sign (sp3x)', 6: 'speed limit sign (sp5x)', 7: 'speed limit sign (sp6x)',
         8: 'gas station sign'}
HAZARDS = {0: 'hazard 0x20', 1: 'hazard 0x21', 2: 'hazard 0x22', 3: 'hazard 0x23'}


def load_image(path):
    d = open(path, 'rb').read()
    return d[struct.unpack_from('<H', d, 8)[0] * 16:]


def s8(v):
    return v - 256 if v >= 128 else v


def describe_object(o):
    """Semantics verified from 0x2a4f (signs), 0x421e (speed limit), 0x467d..0x478f (spawns)."""
    t = o & 0x3F
    hi = o & 0xC0
    if o == 0:
        return None
    if 2 <= t <= 8:
        return {'kind': 'sign', 'type': t, 'name': SIGNS[t], 'side': 'b' if o & 0x80 else 'a'}
    if t == 1:
        return {'kind': 'police', 'spawn_threshold': hi}
    if 0x10 <= t <= 0x14:
        return {'kind': 'traffic_A', 'vehicle': t - 0x10, 'spawn_threshold': hi}
    if 0x18 <= t <= 0x1C:
        return {'kind': 'traffic_B', 'vehicle': t - 0x13, 'spawn_threshold': hi}
    if 0x20 <= t <= 0x23:
        return {'kind': 'hazard', 'type': t - 0x20, 'name': HAZARDS[t - 0x20], 'lane': hi >> 6}
    return {'kind': 'unknown', 'code': t, 'hi': hi}


def extract(img):
    ds = img[DS_IMG:]
    recs = [tuple(ds[TABLE + i * 4:TABLE + i * 4 + 4]) for i in range(NREC)]
    starts = struct.unpack_from('<%dH' % NSTAGES, ds, STAGE_PTRS)
    stages = []
    for n, st in enumerate(starts):
        end = ds.index(0xFF, st)
        stream = list(ds[st:end])
        stages.append({'stage': n + 1, 'ds_start': st, 'ds_end_ff': end,
                       'image_start': DS_IMG + st, 'length_units': len(stream),
                       'player_start_unit': START_SKIP, 'bytes': stream})
    return recs, stages


def build(recs, stages):
    heading = 0.0   # degrees
    slope = 0.0     # degrees
    x = y = z = 0.0
    dist = 0
    out = []
    for stg in stages:
        pts, prof, events, segs = [], [], [], []
        cur = None
        for i, b in enumerate(stg['bytes']):
            flag, curve, pitch, obj = recs[b]
            curve, pitch = s8(curve), s8(pitch)
            heading += curve * 64 / 256.0
            slope += pitch * 4 / 256.0
            x += math.sin(math.radians(heading))
            y -= math.cos(math.radians(heading))
            z += math.sin(math.radians(slope))
            dist += 1
            pts.append((round(x, 2), round(y, 2)))
            prof.append((dist, round(z, 3)))
            ev = describe_object(obj)
            if ev:
                ev.update(unit=i, code=b)
                events.append(ev)
            if flag != 0xFF:
                events.append({'kind': 'special_flag', 'unit': i, 'code': b, 'flag': flag})
            kind = 'L' if curve < 0 else 'R' if curve > 0 else 'S'
            if cur is None or cur['dir'] != kind:
                cur = {'dir': kind, 'unit': i, 'len': 0, 'turn_deg': 0.0}
                segs.append(cur)
            cur['len'] += 1
            cur['turn_deg'] += curve / 4.0
        hills = [{'unit': i, 'pitch': s8(recs[b][2])}
                 for i, b in enumerate(stg['bytes']) if recs[b][2]]
        o = dict(stg)
        o.update(points=pts, profile=prof, events=events,
                 segments=[s for s in segs], hill_units=hills,
                 exit_heading_deg=round(heading, 2))
        out.append(o)
    return out


def render_map(stages, path):
    W, H, M = 1600, 1600, 60
    allp = [p for s in stages for p in s['points']]
    minx, maxx = min(p[0] for p in allp), max(p[0] for p in allp)
    miny, maxy = min(p[1] for p in allp), max(p[1] for p in allp)
    sc = min((W - 2 * M) / (maxx - minx or 1), (H - 2 * M) / (maxy - miny or 1))

    def T(p):
        return (M + (p[0] - minx) * sc, M + (p[1] - miny) * sc)

    im = Image.new('RGB', (W, H), (250, 248, 240))
    dr = ImageDraw.Draw(im)
    cols = [(200, 40, 40), (40, 120, 200), (40, 160, 70), (170, 90, 200), (220, 140, 20)]
    for s, c in zip(stages, cols):
        dr.line([T(p) for p in s['points']], fill=c, width=4)
        p0 = T(s['points'][0])
        dr.ellipse([p0[0] - 9, p0[1] - 9, p0[0] + 9, p0[1] + 9], outline=(0, 0, 0), width=3)
        dr.text((p0[0] + 12, p0[1] - 6), 'Stage %d (gas station)' % s['stage'], fill=(0, 0, 0))
        for e in s['events']:
            px, py = T(s['points'][e['unit']])
            if e['kind'] == 'sign':
                dr.rectangle([px - 3, py - 3, px + 3, py + 3], fill=(0, 0, 0))
            elif e['kind'] == 'hazard':
                dr.polygon([(px, py - 5), (px - 5, py + 4), (px + 5, py + 4)], fill=(255, 0, 0))
            elif e['kind'] == 'police':
                dr.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(0, 0, 255))
    pe = T(stages[-1]['points'][-1])
    dr.ellipse([pe[0] - 10, pe[1] - 10, pe[0] + 10, pe[1] + 10], fill=(0, 0, 0))
    dr.text((pe[0] + 12, pe[1] - 6), 'end of stage 5 (dealership)', fill=(0, 0, 0))
    dr.text((10, 10), 'Test Drive (1987) route, integrated from DS:2B70 curve field '
            '(1 unit = 1 road byte; black square=sign, red=hazard, blue=police)', fill=(0, 0, 0))
    im.save(path)


def render_profile(stages, path):
    W, H, M = 1800, 500, 40
    allp = [p for s in stages for p in s['profile']]
    d0, d1 = allp[0][0], allp[-1][0]
    z0, z1 = min(p[1] for p in allp), max(p[1] for p in allp)
    im = Image.new('RGB', (W, H), (250, 248, 240))
    dr = ImageDraw.Draw(im)

    def T(p):
        return (M + (p[0] - d0) / (d1 - d0) * (W - 2 * M),
                H - M - (p[1] - z0) / ((z1 - z0) or 1) * (H - 2 * M))
    cols = [(200, 40, 40), (40, 120, 200), (40, 160, 70), (170, 90, 200), (220, 140, 20)]
    for s, c in zip(stages, cols):
        dr.line([T(p) for p in s['profile']], fill=c, width=3)
        x = T(s['profile'][0])[0]
        dr.line([(x, M), (x, H - M)], fill=(160, 160, 160))
        dr.text((x + 4, M), 'S%d' % s['stage'], fill=(0, 0, 0))
    dr.text((10, 10), 'Elevation (arbitrary units, integrated from pitch field) vs road units', fill=(0, 0, 0))
    im.save(path)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    exe = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, 'work', 'TDEGA_unp.exe')
    img = load_image(exe)
    recs, stages = extract(img)
    built = build(recs, stages)
    for s in built:
        del s['bytes']  # raw bytes kept below in compact hex
    raw = {s['stage']: img[DS_IMG + s['ds_start']:DS_IMG + s['ds_end_ff']].hex() for s in built}
    doc = {'source': os.path.basename(exe),
           'record_table': {'ds': TABLE, 'image': DS_IMG + TABLE,
                            'records': [list(r) for r in recs]},
           'stage_pointer_table': {'ds': STAGE_PTRS, 'image': DS_IMG + STAGE_PTRS},
           'raw_stream_hex': raw, 'stages': built}
    wd = os.path.join(root, 'work')
    json.dump(doc, open(os.path.join(wd, 'road.json'), 'w'), indent=1)
    render_map(built, os.path.join(wd, 'route_map.png'))
    render_profile(built, os.path.join(wd, 'elevation.png'))
    for s in built:
        turns = [g for g in s['segments'] if g['dir'] != 'S']
        kinds = {}
        for e in s['events']:
            kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
        print('stage %d: DS:%04x len=%d units, %d curves, net turn %.1f deg, events %s'
              % (s['stage'], s['ds_start'], s['length_units'], len(turns),
                 sum(g['turn_deg'] for g in turns), kinds))


if __name__ == '__main__':
    main()
