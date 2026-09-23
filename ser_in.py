#!/usr/bin/env python3
"""
ser_in.py - Python re-implementation of R&S's SER_IN.EXE (a 16-bit DOS program that
won't run on 64-bit Windows), the PC-side receiver for the UPL's SNDFILE.BAS file-
transfer macro (see Application Note 1GA42_0E, "Transferring Files from a UPL Audio
Analyzer to an external PC via the RS-232-C Interface").

Wire protocol (confirmed from DISK2/USER/SNDFILE.BAS, firmware 3.06):
  COM2 on the UPL: 115200 baud (BASIC "115000"), no parity, 8 data bits, 1 stop bit,
  RTS/CTS hardware handshake. The UPL reads the source file in 1024-byte chunks and
  writes them straight to the port -- there is NO length header and NO end marker.
  The receiver has to detect "transfer finished" the same way SER_IN.EXE did: by an
  idle timeout after the last byte arrives.

Usage (manual / front-panel trigger -- the safe, well-documented path):
  1. On the UPL: FILE panel -> STORE INSTRUMENT STATE -> Info Text -> type the full
     path of the file to send, e.g.  C:\\UPL\\MYTRACE.EXP
     (1GA42 says "Display panel"; on firmware 3.06 it is the FILE panel field.)
  2. On this PC, start the receiver FIRST (it must be listening before you trigger
     the send):
       python ser_in.py --port COM2 out\\MYTRACE.EXP
  3. On the UPL: OPTIONS panel -> Exec Macro -> SELECT opens a file box of *.BAS
     -> C:\\UPL\\USER\\SNDFILE.BAS -> ENTER. It runs at once.
  Verified live 2026-09-23: 863-byte EXPort trace, identical to the SCPI readout.
  4. Watch this program; it stops automatically after the port goes idle and reports
     the byte count. Cross-check against the UPL's Info Text line, which will show
     "<n> bytes sent <filename>" or "file not found".

Remote/IEC trigger (needs care over RS232 -- see CLAUDE.md notes on port contention
between the SCPI session and SNDFILE.BAS's own COM2 open):
  upl_capture.py --port COM2 raw "MMEM:STOR:INFO 'C:\\UPL\\MYTRACE.EXP'"
  python ser_in.py --port COM2 out\\MYTRACE.EXP &     (start receiver first)
  upl_capture.py --port COM2 raw "SYST:PROG:EXEC 'C:\\UPL\\USER\\SNDFILE'"
  upl_capture.py --port COM2 raw "MMEM:STOR:INFO?"    (check "<n> bytes sent ..." )
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial is required.  Install with:  python -m pip install pyserial")


def receive(port, outfile, baud=115200, idle_timeout=1.0, max_seconds=120, quiet=False):
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.bytesize = serial.EIGHTBITS
    s.parity = serial.PARITY_NONE
    s.stopbits = serial.STOPBITS_ONE
    s.rtscts = True
    s.timeout = 0.2  # short poll interval; idle detection is done by us, not pyserial
    s.open()
    s.setDTR(True)
    s.setRTS(True)

    if not quiet:
        print(f"Listening on {port} at {baud} baud (8N1, RTS/CTS). "
              f"Waiting for data (idle timeout {idle_timeout}s)...")

    data = bytearray()
    started = False
    t_start = time.time()
    t_last_byte = None
    try:
        while True:
            chunk = s.read(4096)
            now = time.time()
            if chunk:
                if not started:
                    started = True
                    if not quiet:
                        print("  first bytes received, capturing...")
                data.extend(chunk)
                t_last_byte = now
            else:
                if started and t_last_byte is not None and (now - t_last_byte) >= idle_timeout:
                    break  # transfer finished: port has gone quiet
            if now - t_start > max_seconds:
                print(f"  WARNING: {max_seconds}s elapsed with no completed transfer; giving up.")
                break
    finally:
        s.close()

    if not data:
        print("No data received. Check: receiver started before SNDFILE was triggered, "
              "correct COM port, UPL COM2 set to 115200/8N1/RTS-CTS, cable has RTS/CTS wired.")
        return 1

    with open(outfile, "wb") as f:
        f.write(data)
    print(f"Received {len(data)} bytes -> {outfile}")
    return 0


def main():
    p = argparse.ArgumentParser(description="Receive a file streamed by the UPL's SNDFILE.BAS macro.")
    p.add_argument("outfile", help="local file to write the received bytes to")
    p.add_argument("--port", required=True, help="host serial port, e.g. COM2 or COM7")
    p.add_argument("--baud", type=int, default=115200, help="must match SNDFILE.BAS (115200)")
    p.add_argument("--idle-timeout", type=float, default=1.0,
                    help="seconds of silence after the last byte before declaring the transfer done")
    p.add_argument("--max-seconds", type=float, default=120,
                    help="give up if nothing completes within this long")
    args = p.parse_args()
    return receive(args.port, args.outfile, args.baud, args.idle_timeout, args.max_seconds)


if __name__ == "__main__":
    sys.exit(main())
