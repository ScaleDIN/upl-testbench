#!/usr/bin/env python3
"""
upl_capture.py - pull measurement data off an R&S UPL over RS232 (COM2).

Requires the UPL "Remote Control" option UPL-B4 (which you have) and the UPL's
COM2 configured for remote control. Speaks the exact SCPI dialect used by the
R&S example programs shipped on the UPL install media (IEC_EXAM/*.BAS,
RS232_BT.BAS): commands and replies are terminated with a single LF (\\n),
arrays come back comma-separated, and files come back as 488.2 block data.

UPL side setup (front panel, once):
  OPTIONS panel:
    - Remote control destination .......... COM2 (RS232)   [not IEC-BUS]
    - COM2: Parity NONE, Data 8, Stop 1, Handshake RTS/CTS, Baud 115200 (confirmed working;
      set on the OPTIONS panel -- it's listed there even though older docs said 56000 was the max)
  Use an R&S 1050.0346 cable or an equivalent 9-pin null-modem cable with full
  RTS/CTS handshake, via a USB-serial adapter that exposes real RTS/CTS.

Examples:
  python upl_capture.py --port COM4 probe
  python upl_capture.py --port COM4 read
  python upl_capture.py --port COM4 sweep -o sweep.csv
  python upl_capture.py --port COM4 getfile "C:\\UPL\\MYTRACE.EXP" -o MYTRACE.exp
  python upl_capture.py --port COM4 raw "SENS:DATA?"
"""

import argparse
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    sys.exit("pyserial is required.  Install with:  python -m pip install pyserial")


class UPL:
    def __init__(self, port, baud=115200, timeout=10.0):
        # 8 data bits, no parity, 1 stop, hardware RTS/CTS handshake -- per RS232_BT.BAS
        self.ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            rtscts=True,
            timeout=timeout,
        )
        time.sleep(0.1)
        self.ser.reset_input_buffer()

    def write(self, cmd):
        """Send one command, LF-terminated (the UPL's Comout)."""
        self.ser.write(cmd.encode("latin1") + b"\n")
        self.ser.flush()

    def _read_until_lf(self):
        """Read single bytes until LF, return text without the LF (the UPL's Comin$)."""
        buf = bytearray()
        while True:
            b = self.ser.read(1)
            if not b:
                raise TimeoutError("no LF-terminated reply from UPL (check cable, COM2 remote, handshake)")
            if b == b"\n":
                break
            buf += b
        return buf.decode("latin1").strip()

    def query(self, cmd):
        self.write(cmd)
        return self._read_until_lf()

    def read_block(self, cmd):
        """Query returning 488.2 definite-length block  #<n><len><bytes>  (MMEM:DATA?)."""
        self.write(cmd)
        if self.ser.read(1) != b"#":
            raise ValueError("expected '#' at start of block reply")
        n = int(self.ser.read(1).decode("latin1"))
        length = int(self.ser.read(n).decode("latin1"))
        data = bytearray()
        while len(data) < length:
            chunk = self.ser.read(length - len(data))
            if not chunk:
                raise TimeoutError("short block read")
            data += chunk
        self.ser.read(1)  # trailing LF
        return bytes(data)

    def close(self):
        self.ser.close()


def cmd_probe(upl, args):
    idn = upl.query("*IDN?")
    print("*IDN? ->", idn)
    if "UPL" in idn.upper():
        print("OK: remote control (UPL-B4) is active on this port.")
        return 0
    print("WARNING: reply does not contain 'UPL'. Remote not confirmed.")
    return 1


def cmd_read(upl, args):
    # Mapping straight from IEC_EXAM/EXAM1.BAS
    fields = [
        ("CH1 function",   "SENS:DATA?"),
        ("CH1 input peak", "SENS2:DATA?"),
        ("CH1 frequency",  "SENS3:DATA?"),
        ("CH1 phase",      "SENS4:DATA?"),
        ("CH2 function",   "SENS:DATA2?"),
        ("CH2 input peak", "SENS2:DATA2?"),
    ]
    if not args.no_trigger:
        upl.write("INIT;*WAI")
        upl.query("*OPC?") if args.opc else time.sleep(0.2)
    for label, scpi in fields:
        print(f"{label:16s}: {upl.query(scpi)}")
    return 0


def cmd_sweep(upl, args):
    # From IEC_EXAM/EXAM2.BAS: single sweep, then trace + x-axis frequency list.
    upl.write("INIT:CONT OFF")
    upl.write("INIT;*WAI")
    upl.query("*OPC?") if args.opc else time.sleep(0.5)

    npts = int(float(upl.query("TRAC:POIN? TRAC1")))
    levels = [float(v) for v in upl.query("TRAC? TRAC1").split(",")]
    freqs = [float(v) for v in upl.query("SOUR:LIST:FREQ?").split(",")]

    rows = max(len(levels), len(freqs))
    out = open(args.output, "w") if args.output else sys.stdout
    out.write("point,frequency_Hz,level\n")
    for i in range(rows):
        f = freqs[i] if i < len(freqs) else ""
        l = levels[i] if i < len(levels) else ""
        out.write(f"{i+1},{f},{l}\n")
    if args.output:
        out.close()
        print(f"Wrote {rows} points (declared {npts}) to {args.output}")
    return 0


def cmd_autoexport(upl, args):
    """One shot: (optionally load a setup), trigger a fresh single sweep, and pull the
    trace(s) + x-axis straight over the wire to a timestamped CSV -- the same numbers
    the UPL's STORE TRACE LIST / EXPORT would write, but with no file created on the
    instrument. Uses only commands verified from the R&S examples (EXAM2/EXAM3)."""
    import datetime

    def grab_trace(sel):
        return [float(v) for v in upl.query(f"TRAC? {sel}").split(",") if v.strip() != ""]

    reps = args.repeat if args.repeat and args.repeat > 0 else 1
    for rep in range(reps):
        if args.setup:
            upl.write(f"MMEM:LOAD:STAT 0,'{args.setup}'")
        # ASCii format => TRAC? returns readable comma-separated numbers
        upl.write("FORM ASCii")
        upl.write("INIT:CONT OFF")
        upl.write("INIT;*WAI")
        upl.query("*OPC?") if args.opc else time.sleep(args.settle)

        npts = int(float(upl.query("TRAC:POIN? TRAC1")))
        freqs = [float(v) for v in upl.query("SOUR:LIST:FREQ?").split(",") if v.strip() != ""]
        lev1 = grab_trace("TRAC1")
        lev2 = grab_trace("TRAC2") if args.both else None

        ts = datetime.datetime.now()
        if args.output:
            name = ts.strftime(args.output) if "%" in args.output else args.output
        else:
            name = ts.strftime("upl_%Y%m%d_%H%M%S.csv")

        rows = max(len(freqs), len(lev1), len(lev2) if lev2 else 0)
        with open(name, "w") as out:
            out.write(f"# R&S UPL export  {ts.isoformat()}  points={npts}\n")
            out.write("# values in basic units (e.g. V for level); scale as needed\n")
            hdr = "point,frequency_Hz,ch1" + (",ch2" if lev2 else "") + "\n"
            out.write(hdr)
            for i in range(rows):
                f = freqs[i] if i < len(freqs) else ""
                a = lev1[i] if i < len(lev1) else ""
                line = f"{i+1},{f},{a}"
                if lev2 is not None:
                    line += f",{lev2[i] if i < len(lev2) else ''}"
                out.write(line + "\n")
        print(f"[{rep+1}/{reps}] wrote {rows} points -> {name}")
        if rep + 1 < reps:
            time.sleep(max(0.0, args.interval))
    return 0


def cmd_catalog(upl, args):
    print(upl.query(f"MMEM:CAT? '{args.path}'" if args.path else "MMEM:CAT?"))
    return 0


def cmd_getfile(upl, args):
    upl.write("INIT:FORC STOP")  # stop measurement for clean transfer (per RS232_BT.BAS)
    data = upl.read_block(f"MMEM:DATA? '{args.remote}'")
    with open(args.output, "wb") as f:
        f.write(data)
    print(f"Pulled {len(data)} bytes from '{args.remote}' -> {args.output}")
    try:
        print("UPL checksum:", upl.query(f"MMEM:CHECK? '{args.remote}'"))
    except Exception:
        pass
    return 0


def cmd_raw(upl, args):
    if args.command.rstrip().endswith("?"):
        print(upl.query(args.command))
    else:
        upl.write(args.command)
    return 0


def main():
    p = argparse.ArgumentParser(description="Pull data off an R&S UPL over RS232 (COM2).")
    p.add_argument("--port", required=True, help="host serial port, e.g. COM4 or /dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=115200, help="must match UPL COM2 (default 115200)")
    p.add_argument("--timeout", type=float, default=10.0, help="reply timeout seconds")
    p.add_argument("--opc", action="store_true", help="use *OPC? to wait instead of a fixed delay")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="send *IDN? to confirm remote control (UPL-B4) is live")

    r = sub.add_parser("read", help="read the standard live values (rms/peak/freq/phase, both channels)")
    r.add_argument("--no-trigger", action="store_true", help="do not send INIT;*WAI first")

    s = sub.add_parser("sweep", help="capture the current sweep trace to CSV")
    s.add_argument("-o", "--output", help="CSV file (default: stdout)")

    a = sub.add_parser("autoexport", help="trigger a fresh sweep and pull trace(s)+x-axis to a timestamped CSV")
    a.add_argument("-o", "--output", help="output name; may contain strftime codes (default upl_<timestamp>.csv)")
    a.add_argument("--setup", help="UPL setup file to MMEM:LOAD:STAT first, e.g. C:\\UPL\\MYSETUP.SAC")
    a.add_argument("--both", action="store_true", help="also capture channel 2 (TRAC2)")
    a.add_argument("--settle", type=float, default=0.5, help="seconds to wait after INIT if not using --opc")
    a.add_argument("--repeat", type=int, default=1, help="number of captures (for logging)")
    a.add_argument("--interval", type=float, default=0.0, help="seconds between repeats")

    c = sub.add_parser("catalog", help="list files on the UPL (MMEM:CAT?)")
    c.add_argument("path", nargs="?", help="optional directory, e.g. C:\\UPL")

    g = sub.add_parser("getfile", help="pull a file off the UPL (e.g. a stored EXPORT trace)")
    g.add_argument("remote", help="path on the UPL, e.g. C:\\UPL\\MYTRACE.EXP")
    g.add_argument("-o", "--output", required=True, help="local file to write")

    rw = sub.add_parser("raw", help="send one SCPI command; query if it ends with '?'")
    rw.add_argument("command")

    args = p.parse_args()
    upl = UPL(args.port, args.baud, args.timeout)
    try:
        return {
            "probe": cmd_probe,
            "read": cmd_read,
            "sweep": cmd_sweep,
            "autoexport": cmd_autoexport,
            "catalog": cmd_catalog,
            "getfile": cmd_getfile,
            "raw": cmd_raw,
        }[args.cmd](upl, args)
    finally:
        upl.close()


if __name__ == "__main__":
    sys.exit(main())
