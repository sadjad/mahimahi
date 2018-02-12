#!/usr/bin/env python3

import argparse
import time
import mmap
import struct
import curses
import os
import rtmidi
from collections import namedtuple


SIZEOF_UINT64_T = 8
PACKET_SIZE = 1504
OUTAGE_LENGTH_IN_MS = 1000

# 1000 packets per second
MAX_BW_MBPS = float(1000 * PACKET_SIZE * 8) / (10 ** 6)

# 1 packet per second
MIN_BW_MBPS = float(PACKET_SIZE * 8) / (10 ** 6)

DEFAULT_MIDI_CTRL_BW_SLIDER = 81
DEFAULT_MIDI_CTRL_DROP_BUTTON = 73
MIDI_CTRL_SLIDER_MAX = 127


AppConfig = namedtuple('AppConfig', ['window', 'midi_port', 'mm', 'f'])


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', type=str,
                        default='/tmp/mm-interactive',
                        help='Path to mmap control file to')
    parser.add_argument('-m', '--midi-port', type=int,
                        help='Midi port of the device to use')
    parser.add_argument('--midi-ctrl-bw', type=int,
                        default=DEFAULT_MIDI_CTRL_BW_SLIDER,
                        help='Midi controller number for bandwidth')
    parser.add_argument('--midi-ctrl-drop', type=int,
                        default=DEFAULT_MIDI_CTRL_DROP_BUTTON,
                        help='Midi controller number for drops')
    return parser.parse_args()


def mbps_to_pps(mbps):
    return mbps * (10 ** 6) / (8 * PACKET_SIZE)


def print_midi_message(midi):
    if midi.isNoteOn():
        print('on: ', midi.getMidiNoteName(midi.getNoteNumber()),
              midi.getVelocity())
    elif midi.isNoteOff():
        print('off:', midi.getMidiNoteName(midi.getNoteNumber()))
    elif midi.isController():
        print('controller', midi.getControllerNumber(),
              midi.getControllerValue())


def refresh_window(conf, mbps, link_on):
    pps = mbps_to_pps(mbps)
    conf.window.clear()

    line_count = 0

    def addstr(line):
        nonlocal line_count
        conf.window.addstr(line_count, 0, line)
        line_count += 1

    if conf.midi_port is None:
        addstr('Control MahiMahi with the UP/DOWN/ENTER keys')
    else:
        addstr('Control MahiMahi with midi port {}'.format(conf.midi_port))
    addstr('Max bandwidth: {:.3f} Mbps'.format(MAX_BW_MBPS))
    addstr('Min bandwidth: {:.3f} Mbps'.format(MIN_BW_MBPS))
    addstr('Current bandwidth: {:.3f} Mbps'.format(mbps))
    addstr('Packets per second: {:.2f}'.format(pps))
    addstr('Link status: {}'.format('running' if link_on else 'dead'))
    conf.window.refresh()


def write_to_mm_region(conf, mbps, link_on):
    # The first uint64_t is the bps and the second is
    # whether the link is running
    bps = int(mbps * (10 ** 6))
    conf.mm.seek(0)
    conf.mm.write(struct.pack('=QQ', bps, 1 if link_on else 0))
    os.fsync(conf.f.fileno())


def cause_temporary_outage(conf, mbps):
    write_to_mm_region(conf, mbps, False)
    refresh_window(conf, mbps, False)
    curses.beep()
    time.sleep(OUTAGE_LENGTH_IN_MS / 1000.0)


def main(args):
    control_file = args.file
    midi_port = args.midi_port
    midi_ctrl_bw = args.midi_ctrl_bw
    midi_ctrl_drop = args.midi_ctrl_drop

    curr_bw = MAX_BW_MBPS

    with open(control_file, 'wb+') as f:
        mmap_len = 2 * SIZEOF_UINT64_T
        f.write(bytes([0] * mmap_len))
        f.flush()
        mm = mmap.mmap(f.fileno(), mmap_len, prot=mmap.PROT_WRITE)

        window = curses.initscr()
        window.keypad(True)
        window.clear()
        curses.noecho()
        curses.cbreak()

        conf = AppConfig(window=window, midi_port=midi_port, mm=mm, f=f)

        write_to_mm_region(conf, curr_bw, True)
        refresh_window(conf, curr_bw, True)

        def keyboard_loop(conf):
            nonlocal curr_bw
            while True:
                k = window.getch()
                if k == ord('\n') or k == curses.KEY_ENTER:
                    cause_temporary_outage(conf, curr_bw)
                elif k == curses.KEY_UP:
                    curr_bw = min(curr_bw + 0.1, MAX_BW_MBPS)
                elif k == curses.KEY_DOWN:
                    curr_bw = max(MIN_BW_MBPS, curr_bw - 1)
                else:
                    # Ignored input
                    continue

                # Update the display
                write_to_mm_region(conf, curr_bw, True)
                refresh_window(conf, curr_bw, True)

        def midi_loop(conf, midi_ctrl_bw, midi_ctrl_drop):
            nonlocal curr_bw
            midiin = rtmidi.RtMidiIn()
            midiin.openPort(conf.midi_port)

            while True:
                m = midiin.getMessage(250)
                if not m:
                    continue

                # print_midi_message(m)
                if not m.isController():
                    continue

                ctrl_no = m.getControllerNumber()
                if ctrl_no == midi_ctrl_bw:
                    slider_val = m.getControllerValue()
                    assert(slider_val >= 0)
                    new_bw = (slider_val + 1) * 0.1
                    new_bw = min(MAX_BW_MBPS, new_bw)
                    new_bw = max(MIN_BW_MBPS, new_bw)
                    curr_bw = new_bw
                elif ctrl_no == midi_ctrl_drop:
                    cause_temporary_outage(conf, curr_bw)

                write_to_mm_region(conf, curr_bw, True)
                refresh_window(conf, curr_bw, True)

        if midi_port is not None:
            midi_loop(conf, midi_ctrl_bw, midi_ctrl_drop)
        else:
            keyboard_loop(conf)


if __name__ == '__main__':
    main(get_args())
