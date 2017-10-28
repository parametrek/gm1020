#! /usr/bin/env python3

import sys
import json
import time
import argparse
from collections import OrderedDict

import gm1020
import maestro
import gonio_math

"""
log everything!
LMS midpoint search
output interpolation

todo:
    choice of meters besides gm1020
    lantern mode for cylindrical symmetry
    off-axis position
    off-axis cosine correction

"""

essential_settings = ['pan-min', 'pan-max', 'pan-range', 'distance', 'offset', 'scale']

def build_parser():
    p = argparse.ArgumentParser(description='Utility for producing polar sweeps of intensity.',
        epilog='  '.join((
            'It is highly recommended to make several small configuration files.',
            'One for each component: servo, luxmeter, flashlight, and equipment layout.',
            'For example: python3 gonio.py servo.s3151.conf lux.gm1020.conf layout.p60.conf --file p60.csv')))
    p.add_argument('configs', metavar='conf', type=str, nargs='+',
        help='Config file, see examples.')
    p.add_argument('--file', dest='path', default=None,
        help='Path to save TSV data to (default: display on stdout)')
    p.add_argument('--set', dest='custom_set', default='',
        help='Override config settings, "--set foo:0.5,bar:20"')
    return p

def load_options():
    parser = build_parser()
    options = parser.parse_args()
    conf = OrderedDict()
    # config files
    for path in options.configs:
        for k,v in load_conf(path).items():
            conf[k] = v
    # overrides
    for kv in options.custom_set.split(','):
        kv = kv.strip()
        if not kv:
            continue
        k,_,v = kv.partition(':')
        conf[k.strip()] = float(v.strip())
    # misc
    conf['save'] = options.path
    return conf

def load_conf(path):
    conf = OrderedDict()
    for line in open(path):
        line,_,_ = line.partition('#')
        if ':' not in line:
            continue
        key,_,value = line.partition(':')
        conf[key.strip()] = float(value.strip())
    return conf

def run_gm1020_test(conf):
    maestro.servo_conf = conf

    assert maestro.port_search()
    assert gm1020.port_search()

    redirect = sys.stdout
    if conf['save']:
        redirect = open(conf['save'], 'w', 1)

    header = ', '.join(k+': '+str(conf[k]) for k in essential_settings)
    redirect.write(header + '\n')
    redirect.write('time\tpulse\tlux\n')

    maestro.set_pan(int(conf['pan-min']))
    while maestro.is_moving():
        time.sleep(conf['settle'])
    meter = gm1020.live_monitor()

    for i in range(int(conf['pan-min']), int(conf['pan-max']), int(maestro.step_size())):
        maestro.set_pan(i)
        while maestro.is_moving():
            time.sleep(conf['settle'])
        samples = []
        # discard
        gm1020.com.reset_input_buffer()
        while len(samples) < conf['samples']:
            samples.append(next(meter))
        lux = sum(float(s['lux']) for s in samples) / len(samples)
        row = [samples[0]['time'], str(i), str(lux)]
        redirect.write('\t'.join(row) + '\n')

    if conf['save']:
        redirect.close()

    time.sleep(1)
    maestro.cleanup()
    gm1020.send(gm1020.message_bits['live_stop'])
    gm1020.cleanup()


if __name__ == '__main__':
    conf = load_options()
    run_gm1020_test(conf)

