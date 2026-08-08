#!/usr/bin/env python3
"""
Sends a raw KISS command sequence to an RNode over serial, replicating RNS's
RNodeInterface.initRadio() exactly (set frequency, bandwidth, TX power,
spreading factor, coding rate, query radio lock, then request radio state
ON) -- printing every raw byte received at each step.

This bypasses both rnodeconf and RNS's RNodeInterface entirely, which turned
out to matter: the two tools apply different (and differently strict)
success criteria, so a raw byte-level view was needed to find the actual
root cause of two bugs during bring-up (see README.md Parts 7 and 8).

Correctly implements KISS byte-stuffing (escaping FEND/FESC bytes in
payloads) -- an early version of this script did not, which corrupted the
frequency command (it happens to contain a literal 0xC0/FEND byte) and
produced a misleading result. If you're adapting this for other boards or
other commands, don't skip the escaping step.

Usage: python3 raw_initradio_test.py /dev/cu.usbmodemXXXX
"""
import sys
import time
import serial

if len(sys.argv) != 2:
    print("Usage: python3 raw_initradio_test.py /dev/cu.usbmodemXXXX")
    sys.exit(1)

port = sys.argv[1]

FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD

# These match RNS's own RNS/Interfaces/RNodeInterface.py KISS class constants.
# Re-verify against your installed RNS version if these commands don't behave
# as expected -- don't assume they're stable across releases.
CMD_FREQUENCY = 0x01
CMD_BANDWIDTH = 0x02
CMD_TXPOWER = 0x03
CMD_SF = 0x04
CMD_CR = 0x05
CMD_RADIO_STATE = 0x06
CMD_RADIO_LOCK = 0x07
CMD_DETECT = 0x08
DETECT_REQ = 0x73


def kiss_escape(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == FEND:
            out += bytes([FESC, TFEND])
        elif b == FESC:
            out += bytes([FESC, TFESC])
        else:
            out.append(b)
    return bytes(out)


ser = serial.Serial(port=port, baudrate=115200, timeout=0)
time.sleep(0.5)


def send_and_listen(label, cmd_byte, payload, wait=0.3):
    escaped = kiss_escape(payload)
    frame = bytes([FEND, cmd_byte]) + escaped + bytes([FEND])
    ser.write(frame)
    time.sleep(wait)
    data = ser.read(4096)
    print(f"{label}: sent {frame.hex(' ')}  ->  received {len(data)} bytes: {data.hex(' ')}")
    return data


print("--- Detect ---")
send_and_listen("DETECT", CMD_DETECT, bytes([DETECT_REQ]))

print("\n--- Setting radio parameters (adjust these for your region/test) ---")
freq = 915000000
send_and_listen("FREQUENCY", CMD_FREQUENCY, freq.to_bytes(4, byteorder="big"))
bw = 125000
send_and_listen("BANDWIDTH", CMD_BANDWIDTH, bw.to_bytes(4, byteorder="big"))
send_and_listen("TXPOWER", CMD_TXPOWER, bytes([14]))
send_and_listen("SF", CMD_SF, bytes([7]))
send_and_listen("CR", CMD_CR, bytes([5]))

print("\n--- Querying radio lock status ---")
send_and_listen("RADIO_LOCK query", CMD_RADIO_LOCK, bytes([0x00]), wait=0.5)

print("\n--- Requesting radio state ON ---")
send_and_listen("RADIO_STATE=ON", CMD_RADIO_STATE, bytes([0x01]), wait=1.0)

print("\n--- Querying radio lock status again ---")
send_and_listen("RADIO_LOCK query 2", CMD_RADIO_LOCK, bytes([0x00]), wait=0.5)

ser.close()
