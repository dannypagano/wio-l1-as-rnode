#!/usr/bin/env python3
"""
Like serial_logger.py, but logs raw hex bytes instead of decoded text, so
nothing is lost to encoding or terminal copy-paste. Auto-reconnects on
disconnect, same as before.

Usage: python3 serial_hexlog.py /dev/cu.usbmodemXXXX
Ctrl+C to stop.
"""
import sys
import time
import serial

if len(sys.argv) != 2:
    print("Usage: python3 serial_hexlog.py /dev/cu.usbmodemXXXX")
    sys.exit(1)

port_pattern = sys.argv[1]
log_path = "serial_hexlog.txt"

print(f"Logging raw hex to {log_path}. Ctrl+C to stop.")

with open(log_path, "a") as logfile:
    while True:
        try:
            ser = serial.Serial(port=port_pattern, baudrate=115200, timeout=0.5)
            print(f"[connected to {port_pattern}]")
            logfile.write(f"\n--- connected {time.strftime('%H:%M:%S')} ---\n")
            logfile.flush()
            while True:
                chunk = ser.read(256)
                if chunk:
                    hexstr = chunk.hex(' ')
                    ascii_repr = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                    stamped = f"[{time.strftime('%H:%M:%S')}] ({len(chunk)} bytes) {hexstr}  |{ascii_repr}|"
                    print(stamped)
                    logfile.write(stamped + "\n")
                    logfile.flush()
        except (serial.SerialException, OSError) as e:
            print(f"[disconnected: {e} -- retrying...]")
            logfile.write(f"--- disconnected {time.strftime('%H:%M:%S')}: {e} ---\n")
            logfile.flush()
            time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
