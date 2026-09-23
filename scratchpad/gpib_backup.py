"""Back up files from the UPL's disk over GPIB with MMEM:DATA? -- no SNDFILE,
no COM2, no front-panel steps.

MMEM:DATA? '<path>' returns the file as an IEEE-488.2 block. App Note 1GA42
says UPL->PC transfer isn't supported over the bus; on firmware 3.06 over GPIB
it is -- verified 2026-09-24, five files byte-identical to their SNDFILE copies
(binary included), ~150 kB/s.

MMEM:CAT? is broken on this firmware, so names have to come from elsewhere:
the install media, or strings in UPL_UI.EXE. A missing file gives no reply
(timeout) plus -200 "Could not open file '<path>'", so each name is tried in
each --dirs entry with a short timeout, and the first hit is kept.

Usage:
  python scratchpad/gpib_backup.py --outdir results/CAL \
      --dirs C:\\UPL\\REF C:\\UPL\\SETUP C:\\UPL  --names AGEN.CAL ANLR0.CAL
  python scratchpad/gpib_backup.py --outdir results/X --paths C:\\UPL\\UPL.SET

Writes <outdir>/<dir-relative path>, and <outdir>/manifest.csv (path, bytes,
sha256). Read-only on the instrument.
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


def fetch(u, path, probe_timeout, read_timeout):
    """File bytes, or None if the UPL can't open it. The short timeout only has
    to cover the start of the reply; once the block is flowing, the read
    continues under read_timeout."""
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
            err = u.query("SYST:ERR?")
            if not err.startswith("-200"):
                print(f"    unexpected: {err}")
            while not u.query("SYST:ERR?").startswith("0,"):   # drop the -420 the timeout queued
                pass
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
    p.add_argument("--port", default="GPIB0::20::INSTR")
    p.add_argument("--outdir", required=True)
    p.add_argument("--dirs", nargs="*", default=[], help=r"directories to try each --names entry in")
    p.add_argument("--names", nargs="*", default=[], help="bare file names")
    p.add_argument("--paths", nargs="*", default=[], help="full UPL paths, tried as-is")
    p.add_argument("--dirlist", help="'DIR C:\\ /S /A' output: fetch every file it lists")
    p.add_argument("--skip-existing", action="store_true",
                   help="with --dirlist: skip files already in outdir at the listed size")
    p.add_argument("--count-only", action="store_true", help="with --dirlist: just report totals")
    p.add_argument("--probe-timeout", type=float, default=2.0)
    p.add_argument("--read-timeout", type=float, default=120.0)
    args = p.parse_args()

    listed = {}
    if args.dirlist:
        listed = dict(parse_dirlist(args.dirlist))
        print(f"{len(listed)} files, {sum(listed.values()):,} bytes listed")
        if args.count_only:
            return 0
        for q, size in listed.items():
            local = os.path.join(args.outdir, *q.split(":", 1)[-1].lstrip("\\").split("\\"))
            if args.skip_existing and os.path.exists(local) and os.path.getsize(local) == size:
                continue
            args.paths.append(q)

    u = connect(args.port, timeout=args.read_timeout)
    u.write("*CLS")
    os.makedirs(args.outdir, exist_ok=True)
    jobs = [[q] for q in args.paths] + [[ntpath.join(d, n) for d in args.dirs] for n in args.names]
    rows, missing = [], []
    for candidates in jobs:
        for path in candidates:
            t = time.time()
            data = fetch(u, path, args.probe_timeout, args.read_timeout)
            if data is None:
                continue
            rel = path.split(":", 1)[-1].lstrip("\\")
            local = os.path.join(args.outdir, *rel.split("\\"))
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(data)
            sha = hashlib.sha256(data).hexdigest()
            flag = ""
            if path in listed and listed[path] != len(data):
                flag = f"  SIZE MISMATCH (DIR says {listed[path]})"
            print(f"  {path:32s} {len(data):8d} bytes  {time.time() - t:5.2f}s{flag}")
            rows.append([path, len(data), sha])
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
            w.writerow(["upl_path", "bytes", "sha256"])
        w.writerows(rows)
    print(f"\n{len(rows)} file(s) saved, {len(missing)} not found; manifest in {args.outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
