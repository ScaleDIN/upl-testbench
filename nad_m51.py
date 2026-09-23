#!/usr/bin/env python3
"""
nad_m51.py - control a NAD M51 DAC over its RS232 "V2.x" ASCII protocol.

Protocol (from NAD_RS232_M51_docs/nad_rs232_2.02.pdf + rs232_M51_commands.pdf,
2026-09-22): 115200 baud, 8 data, no parity, 1 stop, NO flow control (unlike the
UPL's COM2, which needs RTS/CTS). Commands: <Prefix>.<Variable><Operator><Value><CR>,
operators = / + / - / ? . Reply always uses "=". Confirmed live on COM2:
  Main.Source?  -> Main.Source=USB
  Main.Volume?  -> Main.Volume=-3dB          (note: reply appends "dB"; strip it)

Known variables (from the M51-specific command list):
  Main.Power   Off | On
  Main.Mute    Off | On
  Main.Source  PC LINK | HDMI 2 | HDMI 1 | OPT | COAX | AES   (live unit reports "USB"
               for the USB input, not "PC LINK" as the PDF's example suggests -- PDF
               may be for a slightly different firmware/model text; trust the live value)
  Main.Volume  -90 .. +10 dB, 1 dB steps
  Main.Polarity  Reversed | Positive
  Main.Version   (query only)
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial is required.  Install with:  python -m pip install pyserial")


class M51:
    def __init__(self, port, baud=115200, timeout=2.0):
        self.ser = serial.Serial(
            port=port, baudrate=baud, bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
            rtscts=False, dsrdtr=False, xonxoff=False, timeout=timeout,
        )
        time.sleep(0.1)
        self.ser.reset_input_buffer()

    def _cmd(self, s):
        self.ser.write(b"\r\n" + s.encode("ascii") + b"\r")
        self.ser.flush()

    def query(self, variable, settle=0.15):
        """Send '<variable>?' and return the raw value string after '='."""
        self._cmd(f"{variable}?")
        time.sleep(settle)
        raw = self.ser.read(200).decode("ascii", errors="replace")
        line = raw.strip().splitlines()[-1] if raw.strip() else ""
        return line.split("=", 1)[1].strip() if "=" in line else raw.strip()

    def set(self, variable, value, settle=0.15):
        self._cmd(f"{variable}={value}")
        time.sleep(settle)
        return self.ser.read(200).decode("ascii", errors="replace").strip()

    # -- convenience wrappers -------------------------------------------------
    def get_volume_db(self):
        v = self.query("Main.Volume").replace("dB", "").strip()
        return float(v)

    def set_volume_db(self, db):
        return self.set("Main.Volume", f"{db:g}")

    def get_source(self):
        return self.query("Main.Source")

    def set_source(self, name):
        return self.set("Main.Source", name)

    def set_mute(self, on):
        return self.set("Main.Mute", "On" if on else "Off")

    def close(self):
        self.ser.close()


def main():
    p = argparse.ArgumentParser(description="Control a NAD M51 over RS232.")
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200)
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("volume", help="get or set Main.Volume (dB)")
    v.add_argument("db", nargs="?", type=float, help="omit to query")

    src = sub.add_parser("source", help="get or set Main.Source")
    src.add_argument("name", nargs="?")

    m = sub.add_parser("mute", help="set Main.Mute on/off")
    m.add_argument("state", choices=["on", "off"])

    rw = sub.add_parser("raw", help="send one raw command, e.g. 'Main.Version?'")
    rw.add_argument("command")

    args = p.parse_args()
    dut = M51(args.port, args.baud)
    try:
        if args.cmd == "volume":
            if args.db is None:
                print(dut.get_volume_db(), "dB")
            else:
                print(dut.set_volume_db(args.db))
        elif args.cmd == "source":
            if args.name is None:
                print(dut.get_source())
            else:
                print(dut.set_source(args.name))
        elif args.cmd == "mute":
            print(dut.set_mute(args.state == "on"))
        elif args.cmd == "raw":
            if args.command.rstrip().endswith("?"):
                print(dut.query(args.command.rstrip().rstrip("?")))
            elif "=" in args.command:
                var, val = args.command.split("=", 1)
                print(dut.set(var, val))
            else:
                dut._cmd(args.command)
                print(dut.ser.read(200).decode("ascii", errors="replace").strip())
    finally:
        dut.close()


if __name__ == "__main__":
    sys.exit(main())
