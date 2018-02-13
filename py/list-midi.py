#!/usr/bin/env python3

import rtmidi

midiin = rtmidi.RtMidiIn()

print('Port\tName')
for i in range(midiin.getPortCount()):
    print('{}\t{}'.format(i, midiin.getPortName(i)))
