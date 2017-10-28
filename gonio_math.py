#! /usr/bin/env python3

import sys
import datetime
from math import sqrt, sin, cos, radians, pi, hypot

try:
    import maestro
except:
    pass

"""
todo:
output interpolation?
lantern mode for cylindrical symmetry
off-axis cosine correction (not worth it, 0.2% error)
trapezoidal lumen integral
runtime fade compensation
"""

def load_raw(path):
    "first line is csv k/v pairs, second is tsv headers, and then rest is tsv data"
    f = open(path)
    conf = [kv.split(':') for kv in next(f).split(',')]
    conf = dict((k.strip(),float(v.strip())) for k,v in conf)
    header = next(f).strip().split('\t')
    data = []
    for line in f:
        values = line.strip().split('\t')
        data.append(dict(zip(header, values)))
    f.close()
    for line in data:
        line['time'] = datetime.datetime.strptime(line['time'], '%Y-%m-%d %H:%M:%S.%f')
        line['pulse'] = float(line['pulse'])
        line['lux'] = float(line['lux'])
    return conf, data

def mid_error(data, mid):
    # lazy, assumes evenly spaced measurements
    cds = [d['candela'] for d in data]
    left = cds[mid-1::-1]
    right = cds[mid+1:]
    error = sum((c1-c2)**2 for c1,c2 in zip(left, right)) / min(len(left), len(right))
    return error

def center(data):
    "find the best-fit midpoint"
    #mid = len(data) // 2
    mid = max((line['lux'], i) for i,line in enumerate(data))[1]
    error = mid_error(data, mid)
    while True:
        error_L = mid_error(data, mid-1)
        error_R = mid_error(data, mid+1)
        if error_L < error:
            error = error_L
            mid -= 1
            continue
        if error_R < error:
            error = error_R
            mid += 1
            continue
        break
    return mid

def fold_over(data, mid):
    "coverts ±90 to 0-90"
    data2 = []
    left = data[mid-1::-1]
    right = data[mid+1:]
    middle = data[mid]
    angle_offset = middle['angle']
    data2.append({'angle':0, 'candela':middle['candela']})
    for i in range(max(len(left), len(right))):
        c_total = 0
        c_samples = 0
        angle = None
        try:
            c_total += left[i]['candela']
            c_samples += 1
            angle = abs(left[i]['angle'] - angle_offset)
        except IndexError:
            pass
        try:
            c_total += right[i]['candela']
            c_samples += 1
            angle = abs(right[i]['angle'] - angle_offset)
        except IndexError:
            pass
        assert angle is not None
        c_ave = c_total / c_samples
        data2.append({'angle':angle, 'candela':c_ave})
    return data2

def clean(data, scale=1.0, distance=100, offset=0):
    "convert lux to cd and apply all corrections"
    for line in data:
        angle = maestro.convert_deg(line['pulse'])
        meters = distance / 100.0
        meters -= cos(radians(angle)) * offset / 100.0
        candela = line['lux'] * scale * meters**2
        line['angle'] = angle
        line['candela'] = candela
    middle = center(data)
    #print('midpoint:', data[middle])
    folded = fold_over(data, middle)
    for line in folded:
        line['throw'] = sqrt(line['candela'] * 4)
    return folded

def cap_area(radius, angle):
    return 2 * pi * radius**2 * (1 - cos(radians(angle)))

def integrate_lumens(data):
    "requires folded data"
    # simple midpoint integral
    # lumens = lux * meters area
    # works with un-evenly spaced data
    lumens = 0
    lumens += data[0]['candela'] * cap_area(1, data[1]['angle']/2.0)
    for i in range(1, len(data) - 1):
        angle1 = (data[i]['angle'] + data[i-1]['angle']) / 2.0
        angle2 = (data[i]['angle'] + data[i+1]['angle']) / 2.0
        lumens += data[i]['candela'] * (cap_area(1, angle2) - cap_area(1, angle1))
    return lumens

def main(load_path, save_path):
    conf, data = load_raw(load_path)
    maestro.servo_conf = conf
    #print(conf)
    folded = clean(data, scale=conf['scale'], distance=conf['distance'], offset=conf['offset'])
    print('lumens:', integrate_lumens(folded))
    f = open(save_path, 'w')
    keys = ['angle', 'candela', 'throw']
    f.write('\t'.join(keys) + '\n')
    for line in folded:
        f.write('\t'.join(str(line[k]) for k in keys) + '\n')
    f.close()

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(sys.argv[0], 'raw_input.csv', 'cleaned_output.csv')
        sys.exit(1)
    load_path = sys.argv[1]
    save_path = sys.argv[2]
    main(load_path, save_path)

