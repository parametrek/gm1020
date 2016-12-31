#! /usr/bin/env python3

import glob
import time
import platform
from collections import OrderedDict

import serial

"""

pan servo must be on channel 0
tilt servo must be on channel 1
will need to adjust center and limits with their software

commands:
    should be 8N1 (default)
    target
        0x84, channel, low bits, high bits
        unit is 0.25 uS PWM width
    speed
        0x87, channel, low bits, high bits
        unit is 0.25 uS / 10 mS
    acceleration
        0x89, channel, low bits, high bits
        unit is 0.25 uS / 10 mS / 80 mS

todo:
    reverse-engineer all the setup commands
    crc?

"""

command_table = {
    'baud_detect': 0xAA,
    'target': 0x84,
    'velocity': 0x87,
    'acceleration': 0x89,
    'get_position': 0x90,
    'get_state': 0x93,
}

baud = 9600
timeout = 0.1
port = '/dev/ttyACM0'
com = None
servo_conf = OrderedDict()

def load_conf(path):
    for line in open(path):
        line,_,_ = line.partition('#')
        if ':' not in line:
            continue
        key,_,value = line.partition(':')
        servo_conf[key.strip()] = float(value.strip())
    return servo_conf

def init(port):
    global com
    com = serial.Serial(port, baud, timeout=timeout, bytesize=8, parity='N', stopbits=1)
    send([command_table['baud_detect']])
    send_command('velocity', 0, servo_conf['velocity'])
    send_command('acceleration', 0, servo_conf['acceleration'])

def cleanup():
    com.close()

def send(message):
    #print(message, ['0x%02X' % b for b in message])
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

def send_command(command, channel, n):
    command = command_table[command]
    command |= 0x80
    channel &= 0x07
    n = int(n)
    low = 0x7F & n
    high = 0x7F & (n >> 7)
    send([command, channel, low, high])

def is_moving():
    send([command_table['get_state']])
    r = listen(1)
    if not r:
        return None
    return bool(r[0])

def get_position(channel):
    send_command('get_position', channel, 0)
    low = listen(1)
    high = listen(1)
    if not low:
        return None
    return (256*high[0] + low[0]) // 4

def get_pan():
    return get_position(0)

def get_tilt():
    return get_position(1)

def set_pan(i):
    send_command('target', 0, i*4)

def set_tilt(i):
    send_command('target', 1, i*4)

def step_size():
    delta = servo_conf['pan-max'] - servo_conf['pan-min']
    per_degree = delta / servo_conf['pan-range']
    return int(round(servo_conf['resolution'] * per_degree))

def port_search():
    "sets up com, returns boolean success"
    # interrogate device number?  (default #12)
    os_type = platform.system()
    if os_type not in ['Linux', 'Windows', 'Darwin']:
        print("Unknown OS", os_type)
        return False
    pattern = []
    if os_type == 'Windows':
        pattern = ['COM%i' % n for n in range(1, 10)]
    if os_type == 'Linux':
        pattern = glob.glob('/dev/ttyACM*')
    if os_type == 'Darwin':
        pattern = glob.glob('/dev/cu.usbmodem*')
    for port in pattern:
        try:
            init(port)
        except:
            port = False
            #cleanup()
        if port:
            p = get_pan()
            if p is None:
                cleanup()
                continue
            return True
    return False

