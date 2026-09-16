"""Test Drive (1987) car data dumper.

Decodes Game/NAME.BIN (read by the EXE into DGROUP DS:268F, 0x4D6 bytes) and
Game/NAME.SS, writes work/cars/NAME.json and prints a comparison table.

Offsets are relative to the start of the .BIN file.  "verified" = the field is
read by code in TDEGA.EXE and its role follows from that code; "inferred" =
the role is guessed from the data only.

Usage:  python tools/cardata.py [GameDir] [OutDir]
"""
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'Game')
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'work', 'cars')

FULL_NAMES = {
    'counta': 'Lamborghini Countach', 'lotus': 'Lotus Esprit Turbo',
    'p911t': 'Porsche 911 Turbo', 'rossa': 'Ferrari Testarossa',
    'vette': 'Chevrolet Corvette',
}


def u16(b, o):
    return struct.unpack_from('<H', b, o)[0] if o + 2 <= len(b) else None


def pairs_u16(b, o, n):
    return [[u16(b, o + 4 * i), u16(b, o + 4 * i + 2)] for i in range(n)]


def decode(b):
    car = {}
    car['num_gears'] = {'off': '0x000', 'value': u16(b, 0), 'conf': 'verified',
                        'note': 'byte compared against target gear at 3D21 (keyboard shifting)'}
    car['unk_002'] = {'off': '0x002', 'value': u16(b, 2), 'conf': 'unreferenced in TDEGA'}
    car['rpm_limit'] = {'off': '0x004', 'value': u16(b, 4), 'conf': 'verified',
                        'note': 'rpm [0x91B] above this sets engine-damage state [0x929]=3; also tach index clamp'}
    car['unk_006'] = {'off': '0x006', 'value': u16(b, 6), 'conf': 'unreferenced in TDEGA'}
    car['grip_limit'] = {'off': '0x008', 'value': u16(b, 8), 'conf': 'verified',
                         'note': 'cornering load (speed x curve x ...) >= this => skid flag [0x924], tyre squeal'}
    car['skid_drift'] = {'off': '0x00A', 'value': b[0x0A], 'conf': 'verified (byte)',
                         'note': 'while skidding, lateral slip += (this<<8)>>3'}
    car['wheel_x'] = {'off': '0x00C', 'value': u16(b, 0x0C), 'conf': 'verified use, meaning inferred',
                      'note': 'base X of steering-wheel sprite, offset by steering table at 3685'}
    car['wheel_y'] = {'off': '0x00E', 'value': u16(b, 0x0E), 'conf': 'verified use, meaning inferred'}
    car['unk_010'] = {'off': '0x010', 'value': u16(b, 0x10), 'conf': 'unreferenced in TDEGA'}
    ratios = [u16(b, 0x12 + 2 * i) for i in range(7)]
    car['gear_ratio'] = {'off': '0x012', 'value': ratios, 'conf': 'verified',
                         'note': 'index = gear (0 = neutral). rpm = (ratio * speed16) >> 16, speed16 = [0x927]'}
    car['gear_knob_xy'] = {'off': '0x020', 'value': pairs_u16(b, 0x20, 7), 'conf': 'verified',
                           'note': 'shift-knob screen position per gear 0..6 (target of knob animation)'}
    car['gate_node_xy'] = {'off': '0x03C', 'value': pairs_u16(b, 0x3C, 16), 'conf': 'verified',
                           'note': 'knob position per shift-gate node (joystick shifting); read as +020[(node+7)*4]'}
    car['gate_transition'] = {'off': '0x07C',
                              'value': [list(b[0x7C + 16 * d:0x7C + 16 * d + 16]) for d in range(9)],
                              'conf': 'verified',
                              'note': 'next_node = table[joy_dir*16 + node]; 9 directions x 16 nodes'}
    car['gate_node_gear'] = {'off': '0x10C', 'value': list(b[0x10C:0x11C]), 'conf': 'verified',
                             'note': 'gear engaged when the knob sits on node n'}
    car['torque_curve'] = {'off': '0x11C', 'value': list(b[0x11C:0x16C]), 'conf': 'verified',
                           'note': 'index = rpm/128 (clamped 80); accel = (torque*ratio_hi [*1.5 in 1st] - drag[speed_hi/4]*64) >> 6'}
    analog = u16(b, 0x16C)
    car['analog_gauges'] = {'off': '0x16C', 'value': analog, 'conf': 'verified',
                            'note': '1 = needle speedo/tach drawn from tables below; otherwise digital digit sprites'}
    if analog == 1:
        car['speedo_pivot_xy'] = {'off': '0x16E', 'value': [b[0x16E], b[0x16F]], 'conf': 'verified'}
        car['tach_pivot_xy'] = {'off': '0x170', 'value': [b[0x170], b[0x171]], 'conf': 'verified'}
        car['unk_172'] = {'off': '0x172', 'value': [u16(b, 0x172 + 2 * i) for i in range(4)],
                          'conf': 'unreferenced in TDEGA (look like two x,y points)'}
        car['speedo_needle_xy'] = {'off': '0x17A', 'value': [[b[0x17A + 2 * i], b[0x17B + 2 * i]] for i in range(215)],
                                   'conf': 'verified',
                                   'note': 'needle tip per speed_hi (index clamped 160; car index 2 uses speed-18)'}
        car['tach_needle_xy'] = {'off': '0x328', 'value': [[b[0x328 + 2 * i], b[0x329 + 2 * i]] for i in range(215)],
                                 'conf': 'verified', 'note': 'needle tip per min(rpm, rpm_limit)/64'}
    else:
        tail = b[0x16E:]
        car['digital_dash_raw'] = {'off': '0x16E', 'value': tail.hex(), 'conf': 'inferred',
                                   'note': 'digital dash (Corvette): x,y word pairs e.g. speed digits at 0x16E..; '
                                           'not referenced by the analog path; digital draw code not located'}
    return car


def read_ss(path):
    if not os.path.exists(path):
        return None
    lines = open(path, 'rb').read().decode('latin-1').split('\r\n')
    n_frames, n_something = (int(x) for x in lines[0].split())
    chunks = lambda s: [s[i:i + 4] for i in range(0, len(s), 4)]
    return {'header': [n_frames, n_something], 'frame_lists': [chunks(l) for l in lines[1:] if l]}


def main():
    raw = open(os.path.join(GAME, 'CARS.TXT'), 'rb').read().split(b'\x1a')[0].decode('latin-1')
    names = [l.strip().lower() for l in raw.splitlines() if l.strip()]
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for idx, n in enumerate(names):
        b = open(os.path.join(GAME, n.upper() + '.BIN'), 'rb').read()
        car = decode(b)
        doc = {'name': n, 'car_index': idx, 'full_name': FULL_NAMES.get(n, n), 'file_size': len(b),
               'fields': car, 'ss': read_ss(os.path.join(GAME, n.upper() + '.SS'))}
        with open(os.path.join(OUT, n.upper() + '.json'), 'w') as f:
            json.dump(doc, f, indent=1)
        g = car['num_gears']['value']
        lim = car['rpm_limit']['value']
        top = car['gear_ratio']['value'][g]
        tq = car['torque_curve']['value']
        pk = max(range(len(tq)), key=lambda i: tq[i])
        rows.append((n, len(b), g, lim, car['grip_limit']['value'], car['skid_drift']['value'],
                     ' '.join('%5d' % r for r in car['gear_ratio']['value'][1:g + 1]),
                     lim * 256 // top, '%d@%d' % (tq[pk], pk * 128),
                     'analog' if car['analog_gauges']['value'] == 1 else 'digital',
                     car['unk_002']['value'], car['unk_006']['value'], car['unk_010']['value']))
    hdr = ('car', 'size', 'gears', 'rpmLim', 'grip', 'drift', 'ratios 1..N', 'vmax*', 'peakTq@rpm',
           'dash', 'u002', 'u006', 'u010')
    fmt = '%-7s %5s %5s %6s %5s %5s  %-29s %6s %11s %-7s %5s %4s %4s'
    print(fmt % hdr)
    for r in rows:
        print(fmt % r)
    print('* vmax = speed_hi (speedo units) at rpm_limit in top gear, ignoring drag.')
    print('JSON written to', OUT)


if __name__ == '__main__':
    main()
