#!/usr/bin/env python3

import argparse
import time
import mmap
import struct
import curses
import os


SIZEOF_UINT64_T = 8
PACKET_SIZE = 1504
DROP_LENGTH_IN_SECONDS = 1


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', type=str,
                        default='/tmp/mm-interactive',
                        help='Path to mmap control file to')
    parser.add_argument('-m', '--mode', type=str, default='keyboard',
                        choices=['keyboard', 'midi'],
                        help='Source of user interaction')
    parser.add_argument('-b', '--bandwidth', type=float, default=12.0,
                        help='Max bandwidth of the link in Mbps')
    return parser.parse_args()


def bw_to_pps(mbps):
    return int(mbps * (10 ** 6) / (8 * PACKET_SIZE))


def main(args):
    mode = args.mode
    if mode == 'midi':
        raise Exception('midi not supported yet')

    control_file = args.file

    max_bw = args.bandwidth
    curr_bw = max_bw

    with open(control_file, 'wb+') as f:
        f.write(bytes([0] * SIZEOF_UINT64_T))
        f.flush()
        mm = mmap.mmap(f.fileno(), SIZEOF_UINT64_T, prot=mmap.PROT_WRITE)

        window = curses.initscr()
        window.keypad(True)
        window.clear()
        curses.noecho()
        curses.cbreak()

        def write_pps_to_mm_region(bw):
            mm.seek(0)
            mm.write(struct.pack('=Q', bw_to_pps(bw)))
            os.fsync(f.fileno())

        def refresh_window(curr_bw):
            window.addstr(0, 0, 'Control mode: {}'.format(mode))
            window.addstr(1, 0, 'Max bandwidth: {:6.3f} Mbps'.format(max_bw))
            window.addstr(2, 0, 'Current bandwidth: {:6.3f} Mbps'.format(
                          curr_bw))
            window.addstr(3, 0, 'Packets per second: {:4d}'.format(
                          bw_to_pps(curr_bw)))
            window.refresh()

        write_pps_to_mm_region(curr_bw)
        refresh_window(curr_bw)

        # Wait for command by user
        while True:
            k = window.getch()
            if k == ord('\n') or k == curses.KEY_ENTER:
                write_pps_to_mm_region(0)
                refresh_window(0)
                curses.beep()
                time.sleep(DROP_LENGTH_IN_SECONDS)
            elif k == curses.KEY_UP:
                curr_bw = min(curr_bw + 0.1, max_bw)
            elif k == curses.KEY_DOWN:
                curr_bw = max(0, curr_bw - 0.1)
            else:
                # Ignored input
                continue

            # Update the display
            write_pps_to_mm_region(curr_bw)
            refresh_window(curr_bw)


if __name__ == '__main__':
    main(get_args())
