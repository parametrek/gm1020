#! /usr/bin/env python3

import sys
import copy
import glob
import time
import argparse
import datetime
import platform

import serial

baud = 19200
timeout = 0.05
default_timestamp = '%Y-%m-%d %H:%M:%S.%f'
com = None

"""
todo:
breaks if turned on after being plugged in
figure out what the "fixed" monitoring values do
port to C/C++ so windows-people don't need python
"""

message_bits = {
    'blank':      [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
    # commands
    'status':     [0x1e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1e],  # 30
    'dump_mem':   [0x2d, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x2d],  # 45
    'live_start': [0x3c, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3d],  # 60
    'live_stop':  [0x3c, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3e],  # 60
    'clear_mem':  [0x4b, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x4b],  # 75
    'configure':  [0x5a, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],  # 90
    # settings (bitmasks to fill out 'configure')
    'auto_power': [0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
    'auto_log':   [0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00],
    'fahrenheit': [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00],
    'footcandle': [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02, 0x00],
    }

def init(port):
    global com
    com = serial.Serial(port, baud, timeout=timeout)

def cleanup():
    com.close()

def build_parser():
    p = argparse.ArgumentParser(description='Utility for operating the Benetech GM1020 logging luxmeter.',
        epilog='  '.join((
            'Be aware that the meter does not log time.  All timestamps are inferred from the logging timer.',
            'Changing the logging timer during a run or before the data is downloaded is a BAD IDEA.',
            'Multiple flags can be combined.  It is possible to download, wipe, change the logging interval and continue logging in one command.',
            'To run --monitor for 12 hours and then automatically stop: "timeout -s INT 12h python3 gm1020.py --monitor"',
            )))
    p.add_argument('--port', dest='port', default=None,
        help='Location of serial port (default: autodetect)')
    p.add_argument('--file', dest='path', default='',
        help='Path to save TSV data to (default: display on stdout)')
    p.add_argument('--unit', dest='unit', default=None, metavar='STRING',
        help='  '.join(('Configure the display unit.  Valid units are lux,fc,F,C.',
             'Only affects the LCD display, not logging.',
             '"--unit lux,C" (no spaces) to set multiple.')))
    p.add_argument('--shutdown-timer', dest='shutdown_timer', default=0, metavar='N', type=int,
        help='Minutes of inactivity before the meter turns off.  Valid range is 1 to 240.')
    p.add_argument('--shutdown', dest='shutdown', default=None, metavar='yes/no', choices=['yes', 'no'],
        help='Enable or disable automatic shutdown.')
    p.add_argument('--logging-timer', dest='logging_timer', default=0, metavar='N', type=int,
        help='  '.join(('When logging, store a lux reading every N seconds.',
             'Valid range is 1 to 3600.',
             'If set to 1 second all 1900 memory slots will be full in 31.6 minutes!')))
    p.add_argument('--logging', dest='logging', default=None, metavar='start/stop', choices=['start', 'stop'],
        help='Enable or disable automatic logging.  Only logs lux.  Begins immediately!')
    p.add_argument('--show-setup', dest='show_setup', action='store_true', default=False,
        help='Display the settings programmed into the device.')
    p.add_argument('--download', dest='download', action='store_true', default=False,
        help='Download samples stored in EEPROM, with times in seconds from when logging started.')
    p.add_argument('--download-offset', dest='download_offset', default=0, type=int, metavar='N',
        help='Adjust the starting time of the data log.  Useful for combining multiple runs.  Implies --download.')
    p.add_argument('--download-backdate', dest='download_backdate', action='store_true', default=False,
        help='  '.join(('Assume the last data point happened right now and backdate all the data points.',
            'Implies --download and ignores offset.')))
    p.add_argument('--wipe', dest='wipe', action='store_true', default=False,
        help='Delete the samples stored in EEPROM.')
    p.add_argument('--monitor', dest='monitor', action='store_true', default=False,
        help='Live samples from the meter.  2 per second with temperature.  Continues forever until ^C.')
    dumb_argparse = default_timestamp.replace('%', '%%')
    p.add_argument('--strftime', dest='strftime', default=default_timestamp, metavar='STRFTIME',
        help='  '.join(('Format string for timestamps during live monitoring and backdated downloads.',
            'Visit http://strftime.org/ (default: %s)' % dumb_argparse)))
    return p

def load_options():
    parser = build_parser()
    options = parser.parse_args()

    if type(options.unit) == str:
        options.unit = options.unit.split(',')

    if options.download_offset:
        options.download = True
    if options.download_backdate:
        options.download = True

    if options.shutdown_timer:
        try:
            i = int(options.shutdown_timer)
            assert 1 <= i <= 240
            options.shutdown_timer = i
        except:
            print('shutdown-timer must be between 1 and 240')
            sys.exit()

    if options.logging_timer:
        try:
            i = int(options.logging_timer)
            assert 1 <= i <= 3600
            options.logging_timer = i
        except:
            print('logging-timer must be between 1 and 3600')
            sys.exit()

    if options.path == '-':
        option.path = ''

    setup_actions = ['download', 'show_setup', 'unit', 'shutdown',
                     'shutdown_timer', 'logging', 'logging_timer']
    options._get_setup = any(vars(options)[k] for k in setup_actions)

    setup_update = ['unit', 'shutdown', 'shutdown_timer', 'logging',
                    'logging_timer', ]
    options._push_setup = any(vars(options)[k] for k in setup_update)

    return options

def port_search():
    "sets up com, returns boolean success"
    os_type = platform.system()
    if os_type not in ['Linux', 'Windows', 'Darwin']:
        print("Unknown OS", os_type)
        return False
    pattern = []
    if os_type == 'Windows':
        pattern = ['COM%i' % n for n in range(1, 10)]
    if os_type == 'Linux':
        pattern = glob.glob('/dev/ttyUSB*')
    if os_type == 'Darwin':
        pattern = glob.glob('/dev/tty.usbserial-*')
    for port in pattern:
        try:
            init(port)
        except:
            port = False
            #cleanup()
        if port:
            send(message_bits['status'])
            reply = listen()
            if len(reply) != 8:
                cleanup()
                continue
            return True
    return False

def checksum(message):
    message[-1] = sum(message[:-1]) % 256
    return message

def byte_add(m1, m2):
    assert len(m1) == len(m2)
    return [b1 | b2 for b1,b2 in zip(m1, m2)]

def power_time_set(message, minutes):
    assert 1 <= minutes <= 240
    message[2] = minutes
    return message

def logging_time_set(message, seconds):
    assert 1 <= seconds <= 3600
    high = seconds >> 8
    low  = seconds % 256
    message[4] = high
    message[5] =  low
    return message

def generate_settings(**kwargs):
    message = copy.copy(message_bits['configure'])
    for k in ['auto_power', 'auto_log', 'fahrenheit', 'footcandle']:
        if k in kwargs and kwargs[k] == True:
            message = byte_add(message, message_bits[k])
    power_time = 5
    logging_time = 300
    if 'power_time' in kwargs:
        power_time = kwargs['power_time']
    if 'logging_time' in kwargs:
        logging_time = kwargs['logging_time']
    message = power_time_set(message, power_time)
    message = logging_time_set(message, logging_time)
    message = checksum(message)
    return message

def send(message):
    for b in message:
        try:
            com.write(b.to_bytes(1, byteorder='big'))
        except AttributeError:  # python2
            com.write([b])

def listen(n=8):
    reply = list(com.read(n))
    if reply and type(reply[0]) == str:  # python2
        reply = [ord(n) for n in reply]
    return reply

def send_and_confirm(message):
    send(message)
    reply = listen()
    return message == reply

def retrieve_settings():
    conf = {'auto_power':   False,
            'auto_log':     False,
            'fahrenheit':   False,
            'footcandle':   False,
            'centigrade':   True,
            'lux':          True,
            'power_time':   0,
            'logging_time': 0,
            'samples':      0,
           }
    send(message_bits['status'])
    reply = listen()
    # and now extract everything
    # similar to the conf_set format
    conf['samples']    = 256*int(reply[0]) + int(reply[1])
    conf['auto_power'] = bool(reply[2])
    conf['power_time'] =  int(reply[3])
    conf['auto_log']   = bool(reply[4])
    conf['logging_time'] = 256*int(reply[5]) + int(reply[6])
    conf['fahrenheit'] = bool(reply[7] & 0x01)
    conf['centigrade'] = not conf['fahrenheit']
    conf['footcandle'] = bool(reply[7] & 0x02)
    conf['lux']        = not conf['footcandle']
    return conf

def decode_lux(b1, b2):
    reading = b1*256 + b2
    lux = (reading & 0xFFF) / 10.0
    decimal = True
    if reading & 0x4000:
        lux *= 10
        decimal = False
    if reading & 0x8000:
        lux *= 100
        decimal = False
    if decimal:
        return '%.1f' % lux
    return '%i' % lux

def decode_temp(b1, b2):
    temp = '%.1f' % ((b1*256 + b2) / 10.0)
    return temp

def live_monitor(strftime):
    com.timeout = 1  # wait for data
    send(message_bits['live_start'])
    while True:
        try:
            reply = listen()
            t = datetime.datetime.now().strftime(strftime)
            if reply[0] != 0x33 or reply[1] != 0x22 or reply[4] != 0x01 or reply[7] != 0x11:
                print('You have discovered something new!  Please report this bug. ', 
                      ' '.join('0x%x' % b for b in reply))
            temp = decode_temp(reply[5], reply[6])
            lux = decode_lux(reply[2], reply[3])
            yield {'time':t, 'C':temp, 'lux':lux}
        except:
            break
    send(message_bits['live_stop'])
    com.timeout = timeout

def dump_memory():
    # could be clever and use the number of samples
    # or walk the whole thing instead
    send(message_bits['dump_mem'])
    while True:
        reply = listen(2)
        if not reply:
            break
        b1,b2 = reply
        if b1 == b2 == 255:
            break
        yield decode_lux(b1, b2)

def pretty_conf(conf):
    print('automatic shutdown:', ['no', 'yes'][conf['auto_power']])
    print('shutdown timer:', conf['power_time'],
        ['minutes', 'minute'][conf['power_time'] == 1])
    print('automatic logging:', ['no', 'yes'][conf['auto_log']])
    print('logging timer:', conf['logging_time'],
        ['seconds', 'second'][conf['logging_time'] == 1])
    print('stored samples:', conf['samples'])
    print('unit:', ['', 'lux'][conf['lux']], ['', 'fc'][conf['footcandle']],
          ['', 'C'][conf['centigrade']], ['', 'F'][conf['fahrenheit']])

def core(options):
    conf = {}

    if options._get_setup:
        conf = retrieve_settings()

    redirect = sys.stdout
    if options.path:
        redirect = open(options.path, 'w', 1)

    if options.show_setup:
        pretty_conf(conf)

    if options.download:
        rate = conf['logging_time']
        delta = datetime.timedelta(seconds=rate)
        stop_time = datetime.datetime.now()
        start_time = stop_time - delta * conf['samples']
        redirect.write('time\tlux\n')
        strftime2 = options.strftime.replace('.%f', '')  # sensible?
        for i, lux in enumerate(dump_memory()):
            tick = str(i*rate + options.download_offset)
            if options.download_backdate:
                tick = (start_time + i*delta).strftime(strftime2)
            redirect.write('%s\t%s\n' % (tick, lux))

    if options.wipe:
        status = send_and_confirm(message_bits['clear_mem'])
        if status:
            print('Wipe successful.')
            conf['samples'] = 0
        else:
            print('Wipe failed?')

    if options.unit:
        if 'fc' in options.unit:
            conf['footcandle'] = True
            conf['lux'] = False
        if 'lux' in options.unit:
            conf['footcandle'] = False
            conf['lux'] = True
        if 'F' in options.unit:
            conf['fahrenheit'] = True
            conf['centigrade'] = False
        if 'C' in options.unit:
            conf['fahrenheit'] = False
            conf['centigrade'] = True

    if options.shutdown:
        conf['auto_power'] = options.shutdown.lower() == 'yes'

    if options.shutdown_timer:
        conf['power_time'] = options.shutdown_timer

    if options.logging:
        conf['auto_log'] = options.logging.lower() == 'start'

    if options.logging_timer:
        conf['logging_time'] = int(options.logging_timer)

    if options._push_setup:
        send_and_confirm(generate_settings(**conf))
        if options.show_setup:
            print()
            pretty_conf(conf)

    if options.monitor:
        redirect.write('time\tlux\tC\n')
        for data in live_monitor(options.strftime):
            redirect.write('\t'.join([data['time'], data['lux'], data['C']]) + '\n')

    if options.path:
        redirect.close()


def main():
    options = load_options()
    if options.port:
        init(options.port)
    else:
        status = port_search()
        if not status:
            print("Port detection failed, please manually specify --port")
            sys.exit()

    try:
        core(options)
    except:
        cleanup()
        raise

    cleanup()

if __name__ == "__main__":
        main()

