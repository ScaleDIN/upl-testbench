"""Back up files from the UPL's disk with MMEM:DATA?, over RS-232 or GPIB --
no SNDFILE, no front-panel steps -- and verify each one against the MD5 the
UPL computes itself (MMEM:CHECK?).

MMEM:DATA? '<path>' returns the file as an IEEE-488.2 block '#<n><len><data>'.
App Note 1GA42 says UPL->PC transfer isn't supported over the bus; on firmware
3.06 it is, on both interfaces (verified 2026-09-24, byte-identical to the
SNDFILE copies, binary included):
  RS-232, 115200 baud : ~9-10 kB/s  (the length header frames the binary data,
                        so no end-of-message signal is needed)
  GPIB (82357B)       : ~100-150 kB/s
MMEM:CHECK? '<path>' returns the file's MD5 as 32 hex digits, computed on the
instrument -- checked against a local MD5 for every file unless --no-md5.

MMEM:CAT? is broken on this firmware, so names have to come from elsewhere:
a DOS 'DIR C:\\ /S /A > C:\\DIRLIST.TXT' fetched first (--dirlist), the install
media, or strings in UPL_UI.EXE. A missing file gives no reply (timeout) plus
-200 "Could not open file '<path>'", so each --names entry is tried in each
--dirs entry with a short timeout, and the first hit is kept.

DON'T interrupt a transfer mid-file: over GPIB that hung UPL_UI.EXE until a
power cycle. Let the current file finish.

Usage:
  python tools/upl_backup.py --port COM2 --outdir results/CAL \
      --dirs C:\\UPL\\REF C:\\UPL\\SETUP --names AGEN.CAL ANLR0.CAL
  python tools/upl_backup.py --port COM2 --outdir results/X --paths C:\\DIRLIST.TXT
  python tools/upl_backup.py --port GPIB0::20::INSTR --outdir results/DISK \
      --dirlist results/DISK/DIRLIST.TXT --skip-existing

Writes <outdir>/<path on the UPL>, and appends to <outdir>/manifest.csv
(path, bytes, sha256, md5 check). Read-only on the instrument.
"""
import argparse
import csv
import hashlib
import ntpath
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from upl_capture import connect  # noqa: E402


def _missing(u):
    """After a timed-out MMEM:DATA?: confirm it was 'Could not open file' and
    empty the error queue (GPIB also queues a -420 for the unanswered read)."""
    err = u.query("SYST:ERR?")
    if not err.startswith("-200"):
        print(f"    unexpected: {err}")
    for _ in range(10):         # bounded: misaligned replies must not spin forever
        if u.query("SYST:ERR?").startswith("0,"):
            break


def resync(u):
    """Get back to a clean question/answer rhythm after a bad transfer. A lost
    byte on RS-232 left every later reply read as the answer to the previous
    query (live 2026-09-24). Flush, clear, and read until *IDN? really answers."""
    time.sleep(1.0)
    if hasattr(u, "inst"):
        u.drain()
    else:
        u.ser.reset_input_buffer()
    u.write("*CLS")
    u.write("*IDN?")
    read = u.inst.read if hasattr(u, "inst") else u._read_until_lf
    for _ in range(5):                  # skip any stale replies until the IDN itself
        try:
            if "UPL" in read():
                break
        except Exception:
            break


def _fetch_gpib(u, path, probe_timeout, read_timeout):
    import pyvisa
    # The whole block is read with the LF termchar OFF, i.e. to EOI. With it on,
    # VISA ends every read at each 0x0A in the payload, so a text file came in
    # one line per read: 26.7 kB/s instead of ~150 (measured live 2026-09-24).
    term, u.inst.read_termination = u.inst.read_termination, None
    try:
        u.set_timeout(probe_timeout)
        try:
            u.inst.write(f"MMEM:DATA? '{path}'")
            head = u.inst.read_bytes(2)          # '#n' -- arrives fast if the file exists
        except pyvisa.errors.VisaIOError:
            u.inst.read_termination = term
            _missing(u)
            return None
        u.set_timeout(read_timeout)
        if head[:1] != b"#":
            raise ValueError(f"{path}: reply starts {head!r}, not a 488.2 block")
        n = int(head[1:2])
        rest = u.inst.read_raw()                 # length digits + data + terminator, to EOI
        length = int(rest[:n])
        data = rest[n:n + length]
        if len(data) != length:
            raise ValueError(f"{path}: block says {length} bytes, got {len(data)}")
        return bytes(data)
    finally:
        u.inst.read_termination = term
        u.set_timeout(read_timeout)


def _fetch_serial(u, path, probe_timeout, read_timeout):
    # No EOI on RS-232: the '#<n><len>' header says exactly how many bytes
    # follow, so read that many, then the trailing LF.
    #
    # The timeout is set ONCE, before the request, and never touched while
    # data is flowing. pyserial on Windows applies a timeout change by
    # re-sending the whole port configuration, and doing that mid-transfer on
    # the PL2303 lost or garbled a byte every time -- exactly one byte short,
    # whatever the file size (live 2026-09-24). `getfile`, which never changes
    # it mid-stream, was clean. 5 s covers both a missing file (no reply at
    # all) and a stall: data flows continuously at ~10 kB/s.
    if u.xonxoff:
        raise SystemExit("upl_backup: binary transfers are unsafe under XON/XOFF "
                         "(',xon' port); use RTS/CTS or GPIB")
    s = u.ser
    u.set_timeout(max(probe_timeout, 5.0))
    try:
        u.write(f"MMEM:DATA? '{path}'")
        first = s.read(1)
        if not first:
            _missing(u)
            return None
        if first != b"#":
            raise ValueError(f"{path}: reply starts {first!r}, not a 488.2 block")
        n = int(s.read(1))
        length = int(s.read(n))
        data = bytearray()
        while len(data) < length:
            chunk = s.read(length - len(data))
            if not chunk:
                raise TimeoutError(f"{path}: stalled at {len(data)} of {length} bytes")
            data += chunk
        s.read(1)                                 # trailing LF, already on its way
        return bytes(data)
    finally:
        u.set_timeout(read_timeout)


def fetch(u, path, probe_timeout, read_timeout):
    """File bytes, or None if the UPL can't open it. The short timeout only has
    to cover the start of the reply; once the block is flowing, the read
    continues under read_timeout."""
    if hasattr(u, "inst"):
        return _fetch_gpib(u, path, probe_timeout, read_timeout)
    return _fetch_serial(u, path, probe_timeout, read_timeout)


def parse_dirlist(path):
    """Full paths + sizes from DOS 6 'DIR C:\\ /S /A > file' output:
      Directory of C:\\UPL\\REF
      AGEN     CAL           100 02-16-22  12:01a
    The 8.3 name is split into name/ext columns; <DIR> lines are skipped."""
    import re
    out, cur = [], None
    for line in open(path, encoding="latin1"):
        m = re.match(r"\s*Directory of (.+?)\s*$", line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"^(\S{1,8})\s+(\S{0,3})\s+([\d,]+) \d\d-\d\d-\d\d", line)
        if cur and m:
            name = m.group(1) + ("." + m.group(2) if m.group(2) else "")
            out.append((ntpath.join(cur, name), int(m.group(3).replace(",", ""))))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", required=True, help="COMn (RS-232, 115200) or GPIB0::20::INSTR")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--outdir", required=True)
    p.add_argument("--dirs", nargs="*", default=[], help=r"directories to try each --names entry in")
    p.add_argument("--names", nargs="*", default=[], help="bare file names")
    p.add_argument("--paths", nargs="*", default=[], help="full UPL paths, tried as-is")
    p.add_argument("--dirlist", help="'DIR C:\\ /S /A' output: fetch every file it lists")
    p.add_argument("--skip-existing", action="store_true",
                   help="with --dirlist: skip files already in outdir at the listed size")
    p.add_argument("--count-only", action="store_true", help="with --dirlist: just report totals")
    p.add_argument("--no-md5", action="store_true", help="skip the MMEM:CHECK? verification")
    p.add_argument("--retries", type=int, default=3, help="fetches per file before giving up")
    p.add_argument("--keep-running", action="store_true",
                   help="don't send INIT:FORC STOP first (corrupts RS-232 transfers)")
    p.add_argument("--probe-timeout", type=float, default=2.0)
    p.add_argument("--read-timeout", type=float, default=120.0)
    args = p.parse_args()

    listed = {}
    if args.dirlist:
        listed = dict(parse_dirlist(args.dirlist))
        total = sum(listed.values())
        print(f"{len(listed)} files, {total:,} bytes listed "
              f"(~{total / 9500 / 60:.0f} min over RS-232, ~{total / 120e3 / 60:.0f} min over GPIB)")
        if args.count_only:
            return 0
        for q, size in listed.items():
            local = os.path.join(args.outdir, *q.split(":", 1)[-1].lstrip("\\").split("\\"))
            if args.skip_existing and os.path.exists(local) and os.path.getsize(local) == size:
                continue
            args.paths.append(q)

    u = connect(args.port, args.baud, args.read_timeout)
    u.write("*CLS")
    # Stop the running measurement first, as RS232_BT.BAS and `getfile` do "for
    # clean transfer". Without it, over RS-232 with a continuous FFT running,
    # every file came back corrupted or one byte short -- repeatably, so not
    # line noise (live 2026-09-24). GPIB never showed it.
    if not args.keep_running:
        u.write("INIT:FORC STOP")
        u.query("*OPC?")
    os.makedirs(args.outdir, exist_ok=True)
    jobs = [[q] for q in args.paths] + [[ntpath.join(d, n) for d in args.dirs] for n in args.names]
    rows, missing, bad = [], [], []
    for candidates in jobs:
        for path in candidates:
            t = time.time()
            # Up to --retries fetches: a corrupted copy (MD5 mismatch) or a
            # stalled/garbled transfer is resynced and fetched again, and only
            # a copy that verifies is kept as good. Seen live on RS-232: a
            # burst of framing errors garbled 40 bytes and dropped one.
            data, md5, note = None, "skipped", ""
            for attempt in range(1, args.retries + 1):
                try:
                    data = fetch(u, path, args.probe_timeout, args.read_timeout)
                except (TimeoutError, ValueError) as e:
                    note = f"  [attempt {attempt}: {e}]"
                    print(f"  {path}: {e} -- resyncing")
                    resync(u)
                    data = None
                    continue
                if data is None or args.no_md5:
                    break
                theirs = u.query(f"MMEM:CHECK? '{path}'").strip().strip("'\"").lower()
                if theirs == hashlib.md5(data).hexdigest():
                    md5 = "ok" if attempt == 1 else f"ok after {attempt} tries"
                    break
                md5 = f"MISMATCH (UPL {theirs})"
                print(f"  {path}: MD5 mismatch on attempt {attempt} -- resyncing and retrying")
                resync(u)
            if data is None:
                if note:            # it exists but never came through cleanly
                    bad.append(path)
                    print(f"  {path}: FAILED{note}")
                    break
                continue            # not in this directory; try the next candidate
            dt = time.time() - t
            rel = path.split(":", 1)[-1].lstrip("\\")
            local = os.path.join(args.outdir, *rel.split("\\"))
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(data)
            flag = ""
            if path in listed and listed[path] != len(data):
                flag += f"  size differs from DIR ({listed[path]})"
            if md5.startswith("MISMATCH"):
                bad.append(path)
                flag += f"  MD5 {md5} -- copy kept but NOT verified"
            elif md5 != "ok":
                flag += f"  MD5 {md5}"
            print(f"  {path:32s} {len(data):8d} bytes  {dt:6.2f}s{flag}")
            rows.append([path, len(data), hashlib.sha256(data).hexdigest(), md5])
            break
        else:
            missing.append(ntpath.basename(candidates[0]))
            print(f"  -- {ntpath.basename(candidates[0])}: not found in {len(candidates)} location(s)")

    err = u.query("SYST:ERR?")
    if not err.startswith("0,"):
        print(f"  SYST:ERR? -> {err}")
    u.close()
    with open(os.path.join(args.outdir, "manifest.csv"), "a", newline="") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["upl_path", "bytes", "sha256", "md5_vs_upl"])
        w.writerows(rows)
    print(f"\n{len(rows)} file(s) saved, {len(missing)} not found, "
          f"{len(bad)} MD5 mismatch(es); manifest in {args.outdir}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
