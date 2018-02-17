#!/usr/bin/env python3

import rtmidi

midiin = rtmidi.RtMidiIn()

print('Port\tName (IN)')
for i in range(midiin.getPortCount()):
    print('{}\t{}'.format(i, midiin.getPortName(i)))

midiout = rtmidi.RtMidiIn()

print('Port\tName (OUT)')
for i in range(midiout.getPortCount()):
    print('{}\t{}'.format(i, midiout.getPortName(i)))
