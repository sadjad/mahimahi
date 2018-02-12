#!/usr/bin/env python3

import argparse
import struct
import os


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', type=str,
                        default='/tmp/mm-static',
                        help='Path to mmap control file to')
    parser.add_argument('--mbps', type=int, default=12.032,
                        help='Interval between packets in ms')
    return parser.parse_args()


def main(args):
    static_file = args.file
    if os.path.exists(static_file):
        raise Exception('File already exists: {}'.format(static_file))

    bps = int(args.mbps * (10 ** 6))
    with open(static_file, 'wb') as f:
        f.write(struct.pack('=QQ', bps, 1))


if __name__ == '__main__':
    main(get_args())
