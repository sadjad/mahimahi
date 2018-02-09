#!/usr/bin/env python3

import argparse
import time
import mmap
import struct
import curses
import os


SIZEOF_UINT64_T = 8
PACKET_SIZE = 1504
OUTAGE_LENGTH_IN_MS = 1000


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', type=str,
                        default='/tmp/mm-interactive',
                        help='Path to mmap control file to')
    parser.add_argument('-m', '--mode', type=str, default='keyboard',
                        choices=['keyboard', 'midi'],
                        help='Source of user interaction')
    parser.add_argument('--interval', type=int, default=1,
                        help='Min interval between packets in ms')
    return parser.parse_args()


def pps_to_mbps(pps):
    return pps * PACKET_SIZE * 8 / 10 ** 6


def scheduling_interval_to_pps(interval):
    return 1000 / float(interval)


def main(args):
    mode = args.mode
    if mode == 'midi':
        raise Exception('midi not supported yet')

    control_file = args.file

    min_scheduling_interval = args.interval
    if min_scheduling_interval < 1:
        raise Exception('Sceduling interval cannot be less than 1')
    if min_scheduling_interval >= OUTAGE_LENGTH_IN_MS:
        raise Exception('Sceduling interval cannot exceed link drop length')
    max_mbps = pps_to_mbps(scheduling_interval_to_pps(min_scheduling_interval))
    curr_interval = min_scheduling_interval

    with open(control_file, 'wb+') as f:
        f.write(bytes([0] * SIZEOF_UINT64_T))
        f.flush()
        mm = mmap.mmap(f.fileno(), SIZEOF_UINT64_T, prot=mmap.PROT_WRITE)

        window = curses.initscr()
        window.keypad(True)
        window.clear()
        curses.noecho()
        curses.cbreak()

        def write_interval_to_mm_region(interval):
            mm.seek(0)
            mm.write(struct.pack('=Q', interval))
            os.fsync(f.fileno())

        def refresh_window(interval):
            pps = scheduling_interval_to_pps(interval)
            mbps = pps_to_mbps(pps)
            window.clear()
            window.addstr(0, 0, 'Control mode: {}'.format(mode))
            window.addstr(1, 0, 'Max bandwidth: {:6.3f} Mbps'.format(max_mbps))
            window.addstr(2, 0, 'Current bandwidth: {:6.3f} Mbps'.format(mbps))
            window.addstr(3, 0, 'Packets per second: {:3.2f}'.format(pps))
            window.addstr(4, 0,
                          'Scheduling interval: {:4d} ms'.format(interval))
            window.refresh()

        write_interval_to_mm_region(curr_interval)
        refresh_window(curr_interval)

        # Wait for command by user
        while True:
            k = window.getch()
            if k == ord('\n') or k == curses.KEY_ENTER:
                write_interval_to_mm_region(OUTAGE_LENGTH_IN_MS)
                refresh_window(OUTAGE_LENGTH_IN_MS)
                curses.beep()
                time.sleep(OUTAGE_LENGTH_IN_MS / 1000.0)
            elif k == curses.KEY_DOWN:
                curr_interval = min(curr_interval + 1, OUTAGE_LENGTH_IN_MS)
            elif k == curses.KEY_UP:
                curr_interval = max(1, curr_interval - 1)
            else:
                # Ignored input
                continue

            # Update the display
            write_interval_to_mm_region(curr_interval)
            refresh_window(curr_interval)


if __name__ == '__main__':
    main(get_args())
