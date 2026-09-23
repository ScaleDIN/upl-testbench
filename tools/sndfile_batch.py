"""Pull a list of files off the UPL with SNDFILE.BAS, doing everything but the
front-panel part from the PC.

Per file, the PC side:
  1. waits for the SCPI link (every SNDFILE run takes COM2 away from the remote
     handler; it comes back only after OPTIONS -> Remote via -> IEC -> COM2),
  2. reads the previous file's "<n> bytes sent <file>" note via MMEM:STOR:INFO?
     and checks it against the byte count actually received,
  3. sets MMEM:STOR:INFO '<next file>' -- the Info Text SNDFILE reads,
  4. closes the SCPI port and listens with ser_in.receive().

Operator, per file (prompted on the console):
  LOCAL -> OPTIONS -> Exec Macro -> SELECT -> SNDFILE.BAS -> ENTER (once!)
  -> then Remote via IEC -> COM2.

GPIB mode (--port GPIB0::20::INSTR --data-port COM2) needs no operator at all:
SCPI goes over GPIB, so COM2 stays free for the macro -- the setup App Note
1GA42 assumes. Per file: set Info Text, start the receiver, send
SYST:PROG:EXEC 'C:\\UPL\\USER\\SNDFILE', wait on *OPC?, check the count.
UPL: OPTIONS -> Remote via -> IEC.

Writes <outdir>/<basename> for each file plus <outdir>/manifest.csv.

Usage:
  python tools/sndfile_batch.py --port COM2 --outdir results/REF \
      C:\\UPL\\REF\\FLAT1AC.CAL C:\\UPL\\REF\\FLAT1DC.CAL
  python tools/sndfile_batch.py --port GPIB0::20::INSTR --data-port COM2 \
      --outdir results/SETUP C:\\UPL\\SETUP\\CAL_GEN.SET ...

Serial mode verified live 2026-09-23 (10 REF files). GPIB mode not yet run.
"""
import argparse
import csv
import ntpath
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from upl_capture import UPL, connect  # noqa: E402
from ser_in import receive  # noqa: E402

SNDFILE = r"C:\UPL\USER\SNDFILE"


def wait_link(port, baud):
    """Poll *IDN? until the UPL answers; returns an open UPL."""
    told = False
    while True:
        try:
            u = UPL(port, baud, 2.0)
        except Exception:
            time.sleep(2)
            continue
        try:
            if "UPL" in u.query("*IDN?"):
                return u
        except TimeoutError:
            pass
        u.ser.close()
        if not told:
            print("  waiting for the remote link -- toggle OPTIONS > Remote via: IEC -> COM2")
            told = True
        time.sleep(2)


def cal_self_check(local):
    """REF *.CAL files open with 7 header lines, the 5th being the point count,
    then '#--X--Y--' and one X/Y row per point. Returns (ok, detail) or
    (None, reason) for files not in that format."""
    try:
        lines = open(local, encoding="latin1").read().splitlines()
        declared = int(lines[4])
        if not lines[7].startswith("#"):
            return None, "not CAL format"
    except (ValueError, IndexError):
        return None, "not CAL format"
    rows = sum(1 for s in lines[8:] if re.match(r"^\s*[\d.eE+-]+\s+[\d.eE+-]+\s*$", s))
    return rows == declared, f"{rows}/{declared} rows"


def upl_reported(u):
    """(bytes, raw) from the Info Text SNDFILE leaves behind."""
    raw = u.query("MMEM:STOR:INFO?").strip().strip("'")
    m = re.match(r"\s*(\d+)\s+bytes sent", raw)
    return (int(m.group(1)) if m else None), raw


def check(u, prev):
    """Manifest row for a received file: the UPL's byte count, plus the .CAL
    header point count where there is one. The UPL's note is lost if SNDFILE
    runs a second time (it then reads its own "n bytes sent" sentence as a
    file name -> 'file not found'); the CAL self-check still stands then."""
    path, local, got = prev
    n, raw = upl_reported(u)
    self_ok, detail = cal_self_check(local)
    if n is not None:
        ok = n == got and self_ok is not False
        why = f"UPL {n} bytes" + (f", {detail}" if self_ok is not None else "")
    else:
        ok = bool(self_ok)
        why = f"UPL note {raw!r}; {detail}"
    print(f"  {why}  -> {'OK' if ok else 'CHECK'}")
    return [path, local, got, n, "ok" if ok else f"CHECK: {why}"]


def run_gpib(args, rows):
    """No operator: SCPI on GPIB, file data on the serial port."""
    u = connect(args.port, timeout=10.0)
    print("  " + u.query("*IDN?"))
    for i, path in enumerate(args.files):
        print(f"\n[{i + 1}/{len(args.files)}] {path}")
        u.write(f"MMEM:STOR:INFO '{path}'")
        back = u.query("MMEM:STOR:INFO?").strip().strip("'")
        if back != path:
            print(f"  Info Text read back as {back!r}, not {path!r} -- stopping.")
            break
        local = os.path.join(args.outdir, ntpath.basename(path))
        if os.path.exists(local):
            os.remove(local)
        # Receiver first -- it must be listening before the macro starts sending.
        rx = threading.Thread(target=receive, daemon=True, args=(
            args.data_port, local, args.baud, args.idle_timeout, args.max_seconds, True))
        rx.start()
        time.sleep(0.5)
        u.set_timeout(args.max_seconds)
        try:
            u.write(f"SYST:PROG:EXEC '{SNDFILE}'")
            u.query("*OPC?")  # returns once the macro has quit
        finally:
            u.set_timeout(10.0)
        rx.join(args.idle_timeout + 5)
        if not os.path.exists(local):
            print(f"  nothing received; UPL says {u.query('MMEM:STOR:INFO?')!r} -- stopping.")
            rows.append([path, local, 0, None, "nothing received"])
            break
        got = os.path.getsize(local)
        print(f"  received {got} bytes -> {local}")
        rows.append(check(u, (path, local, got)))
    err = u.query("SYST:ERR?")
    if not err.startswith("0,"):
        print(f"  SYST:ERR? -> {err}")
    u.close()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("files", nargs="+", help=r"UPL paths, e.g. C:\UPL\REF\FLAT1AC.CAL")
    p.add_argument("--port", required=True,
                   help="SCPI link: COMn (operator-assisted) or GPIB0::20::INSTR (unattended)")
    p.add_argument("--data-port", help="serial port SNDFILE sends on (default: --port if serial)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--outdir", required=True)
    p.add_argument("--idle-timeout", type=float, default=2.0)
    p.add_argument("--max-seconds", type=float, default=1800)
    args = p.parse_args()
    gpib = args.port.upper().startswith("GPIB")
    if gpib and not args.data_port:
        p.error("GPIB mode needs --data-port (the PC serial port wired to UPL COM2)")

    os.makedirs(args.outdir, exist_ok=True)
    rows = []
    prev = None  # (upl_path, local_path, received_bytes)

    for i, path in enumerate([] if gpib else args.files + [None]):
        u = wait_link(args.port, args.baud)
        if prev:
            rows.append(check(u, prev))
        if path is None:
            u.ser.close()
            break

        u.write(f"MMEM:STOR:INFO '{path}'")
        back = u.query("MMEM:STOR:INFO?").strip().strip("'")
        u.ser.close()
        if back != path:
            print(f"  Info Text read back as {back!r}, not {path!r} -- stopping.")
            break

        local = os.path.join(args.outdir, ntpath.basename(path))
        print(f"\n[{i + 1}/{len(args.files)}] {path}")
        print("  UPL: LOCAL -> OPTIONS -> Exec Macro -> SNDFILE.BAS -> ENTER (once)")
        if receive(args.port, local, args.baud, args.idle_timeout, args.max_seconds, quiet=True):
            rows.append([path, local, 0, None, "nothing received"])
            prev = None
            print("  nothing received -- stopping.")
            break
        got = os.path.getsize(local)
        print(f"  received {got} bytes -> {local}")
        print("  now toggle Remote via: IEC -> COM2")
        prev = (path, local, got)

    if gpib:
        run_gpib(args, rows)

    with open(os.path.join(args.outdir, "manifest.csv"), "a", newline="") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["upl_path", "local_path", "received_bytes", "upl_reported_bytes", "status"])
        w.writerows(rows)
    bad = [r for r in rows if r[4] != "ok"]
    print(f"\n{len(rows) - len(bad)}/{len(rows)} files verified; manifest in {args.outdir}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
