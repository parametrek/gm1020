#! /usr/bin/env python3

import sys
import copy
import time
import argparse
import datetime

import serial

default_port = '/dev/ttyUSB0'
baud = 19200
timeout = 0.2
default_timestamp = '%Y-%m-%d %H:%M:%S.%f'
com = None

"""
todo:
autodetect windows and OSX, use better defaults for them
figure out how to change settings and download logged data
port to C/C++ so windows-people don't need python
"""

lcd_7seg = {0x00:None, 0x7B:0, 0x60:1, 0x5E:2, 0x7C:3,
    0x65:4, 0x3D:5, 0x3F:6, 0x70:7, 0x7F:8, 0x7D:9,
    0x6B:'U', 0x2F:'b', 0x77:'A', 0x57:'P', 0x1F:'E', 0x1B:'C',
    0x6D:'d', 0x1F:'E', 0x6E:'d', 0x17:'F', 0x56:'?', 0x0B:'L',
    }
# key : (byte, mask, {bits:value})
lcd_table = {
    'big_1':    (1, 0x7F, lcd_7seg),
    'big_10':   (2, 0x7F, lcd_7seg),
    'big_100':  (3, 0x7F, lcd_7seg),
    'big_1000': (4, 0x7F, lcd_7seg),
    'lil_1':    (5, 0x7F, lcd_7seg),
    'lil_10':   (6, 0x7F, lcd_7seg),
    'lil_100':  (7, 0x7F, lcd_7seg),
    'lil_1000': (8, 0x7F, lcd_7seg),
    'big_10ths':   (2, 0x80, {0x00:False, 0x80:True}),
    'big_100ths':  (3, 0x80, {0x00:False, 0x80:True}),
    'big_1000ths': (4, 0x80, {0x00:False, 0x80:True}),
    'mode':  (11, 0xFF, {0x10:'hold', 0x20:'max', 0x40:'min'}),
    'auto':  (10, 0x02, {0x00:False, 0x02:True}),
    'scale':  (10, 0xF0, {0x00:2, 0x80:20, 0xC0:200, 0xE0:2000, 0xF0:20000}),
    'unit':  (9, 0x0C, {0x08:'lux', 0x04:'fc'}),
    'x10':   (9, 0x01, {0x00:False, 0x01:True}),
    'poweroff': (11, 0x02, {0x00:False, 0x02:True}),
    'batt':  (9, 0x10, {0x00:False, 0x10:True}),
    'rec':   (11, 0x01, {0x00:False, 0x01:True}),
    'usb':   (9, 0x20, {0x00:False, 0x20:True}),
    'menu':  (0, 0xFF, {0x20:'usb', 0x30:'apo', 0x40:'rec', 0x50:'code', 0x60:'def'}),
    # missing: rel, clock, load#, full, lil_colon
}
bitwise_fields = ['mode',]

def init(port):
    global com
    com = serial.Serial(port, baud, timeout=timeout)

def cleanup():
    com.close()

def build_parser():
    p = argparse.ArgumentParser(description='Utility for operating the Uni-T UT382 USB luxmeter.',
        epilog='  \n'.join((
            'Todo: program meter settings, start monitor remotely, download logged readings.'
            'To run --monitor for 12 hours and then automatically stop: "timeout -s INT 12h python3 ut382.py --monitor"',
            )))
    p.add_argument('--port', dest='port', default=default_port,
        help='Location of serial port (default: %s)' % default_port)
    p.add_argument('--file', dest='path', default='',
        help='Path to save TSV data to (default: display on stdout)')
    p.add_argument('--monitor', dest='monitor', action='store_true', default=False,
        help='Live samples from the meter.  8 per second.  Continues forever until ^C.')
    p.add_argument('--delta', dest='delta', action='store_true', default=False,
        help='Only output data when the measurement changes.  Implies --monitor.')
    p.add_argument('--moving-average', dest='moving', default=None, type=int, metavar='N',
        help='Average together the last N seconds for more stable readings.  Implies --monitor.')
    dumb_argparse = default_timestamp.replace('%', '%%')
    p.add_argument('--strftime', dest='strftime', default=default_timestamp, metavar='STRFTIME',
        help='  '.join(('Format string for timestamps during live monitoring.',
            'Visit http://strftime.org/ (default: %s)' % dumb_argparse)))
    return p

def load_options():
    parser = build_parser()
    options = parser.parse_args()
    if options.path == '-':
        option.path = ''
    return options

def listen(n=33):
    reply = list(com.read(n))
    if reply and type(reply[0]) == str:  # python2
        reply = [ord(n) for n in reply]
    return reply

def decode_lcd_byte(i, b):
    summary = {}
    for k,v in lcd_table.items():
        n,mask,lut = v
        if n != i:
            continue
        summary[k] = None
        b2 = mask & b
        if k in bitwise_fields:
            summary[k] = []
            for k2,v2 in lut.items():
                if k2 & b2:
                    summary[k].append(v2)
        else:
            if b2 in lut:
                summary[k] = lut[b2]
    return summary

def pretty_byte(i, b):
    summary = decode_lcd_byte(i, b)
    print('%2i' % i, '%8s' % str(bin(b)[2:]), '0x%02X' % b, str(summary))

def decode_raw(bs):
    weird = []
    if len(bs) != 33:
        weird.append('wrong message length %i' % len(bs))
    for i,b in enumerate(bs):
        if i >= 30:
            break
        if b & 0xF0 != 0x30:
            weird.append('bad byte prefix')
    if len(bs) > 30 and bs[30] != 0x0D:
        weird.append('bad byte 30')
    if len(bs) > 31 and bs[31] != 0x0A:
        weird.append('bad byte 31')
    # last byte might be a checksum?
    # usually consistent, sometimes wiggles between two values
    bs2 = []
    for i in range(1, len(bs), 2):
        if i >= 31:
            break
        bs2.append((bs[i-1]&0x0F) | ((bs[i]&0x0F)*16))
    if weird:
        sys.stderr.write(str(weird))
    return bs2, bool(weird)

def decode_summary(reply):
    summary = {}
    for i,b in enumerate(reply):
        summary.update(decode_lcd_byte(i, b))
    return summary

def decode_lux(summary):
    unit = summary['unit']
    digits = [summary['big_1000'], summary['big_100'], summary['big_10'], summary['big_1']]
    if digits == [None, 0, 'L', None]:
        return None, unit
    lux = 0.0
    for i,d in enumerate(reversed(digits)):
        if d is None:
            continue
        lux += d * 10**i
    if summary['big_10ths']:
        lux *= 0.1
    if summary['big_100ths']:
        lux *= 0.01
    if summary['big_1000ths']:
        lux *= 0.001
    if summary['x10']:
        lux *= 10
    if not any(summary[d] for d in ['big_10ths', 'big_100ths', 'big_1000ths']):
        lux = int(lux)
    return lux, unit

def live_raw():
    com.timeout = 0.02  # single byte timeout
    reply  = []
    reply2 = []
    while True:
        reply = listen(1)
        if reply:
            reply2.extend(reply)
            continue
        if not reply2:
            continue
        yield reply2
        reply2 = []

def live_sync():
    "throw away the first partial, then be efficient"
    err = True
    while True:
        if err:  # re-sync
            for bs in live_raw():
                if len(bs) != 33:
                    continue
                reply,err = decode_raw(bs)
                if not err:
                    yield reply
                    com.timeout = timeout
                    break
        # this uses 80% less CPU
        bs = listen(33)
        if len(bs) != 33:
            err = True
            continue
        reply,err = decode_raw(bs)
        if err:
            continue
        yield reply

def live_debug_raw():
    for bs in live_raw():
        for i,b in enumerate(bs):
            print('%2i' % i, '%8s' % str(bin(b)[2:]), '0x%02X' % b)
        print()

def live_debug():
    for bs in live_raw():
        reply,err = decode_raw(bs)
        for i,b in enumerate(reply):
            pretty_byte(i, b)
        summary = decode_summary(reply)
        print()

def live_monitor(strftime):
    for reply in live_sync():
        t = datetime.datetime.now().strftime(strftime)
        summary = decode_summary(reply)
        if summary['batt']:
            sys.stderr.write('Warning: battery low')
        if summary['menu']:
            continue
        lux, unit = decode_lux(summary)
        yield {'time':t, 'lux':lux, 'unit':unit}

def live_average(strftime, duration):
    samples = duration * 8.0
    history = []
    for data in live_monitor(strftime):
        if data['lux'] is None:
            continue
        history.append(data['lux'])
        if len(history) < samples:
            continue
        data['ave_lux'] = sum(history) / len(history)
        yield data
        history = []

def core(options):
    redirect = sys.stdout
    old = None
    new = None
    if options.path:
        redirect = open(options.path, 'w', 1)

    if options.moving:
        source = live_average(options.strftime, options.moving)
        k = 'ave_lux'
    elif options.monitor or options.delta:
        source = live_monitor(options.strftime)
        k = 'lux'
    if options.monitor or options.moving or options.delta:
        redirect.write('time\tlight\tunit\n')
        for data in source:
            num = '%.2f'
            if data[k] is None:
                continue
            if type(data[k]) == int:
                num = '%i'
            lux = num % data[k]
            new = lux
            if options.delta and new == old:
                continue
            old = new
            redirect.write('\t'.join([data['time'], lux, data['unit']]) + '\n')

    if options.path:
        redirect.close()

def main():
    options = load_options()
    init(options.port)

    try:
        #live_debug_raw()
        #live_debug()
        core(options)
    except KeyboardInterrupt:
        pass
    except:
        cleanup()
        raise

    cleanup()

if __name__ == "__main__":
    main()

