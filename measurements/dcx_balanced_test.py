#!/usr/bin/env python3
"""
dcx_balanced_test.py - compare a DCX2496 output measured balanced (XLR direct into the
UPL) vs single-ended (via XLR-to-RCA-to-XLR adapters into the same UPL jack). Run it once
per physical wiring state with a different mode label; give the second run --compare
<first run's folder> and its report shows both side by side.
See CLAUDE.md, 2026-09-23 "Balanced vs single-ended comparison" for the reference results.

IMPORTANT: the UPL analyzer input is always the same physical XLR jack (INP:TYPE BAL is the
only input-type option) -- "single-ended" here means only pin2/hot is actually driven
upstream, via the adapter chain, not a different UPL setting. If a run shows a level near
the analyzer's noise floor (~1e-5V) with THD+N near 0dB, the signal isn't actually reaching
the analyzer -- check the physical connections before trusting the numbers.

Usage:
  python measurements/dcx_balanced_test.py balanced     --dcx-port COM2 --upl-port COM7
  python measurements/dcx_balanced_test.py single_ended --dcx-port COM2 --upl-port COM7 \
      --compare results/dcx_balanced_test/balanced_<timestamp>

Output: results/dcx_balanced_test/<mode>_<timestamp>/ (--label overrides the mode as the
folder name) -- report.html, results.json (as before), freq_response.csv, summary.txt.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np  # noqa: E402
from upl_capture import connect  # noqa: E402
from dcx2496 import DCX2496  # noqa: E402
from report import Run, add_output_args, is_na  # noqa: E402


def parse_num(s):
    try:
        return float(s.strip().split()[0])
    except Exception:
        return float("nan")


def db(v, ref=1.0):
    return 20 * np.log10(v / ref) if (not is_na(v) and v > 0) else float("nan")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", help="a label for this run, e.g. 'balanced' or 'single_ended'")
    p.add_argument("--dcx-port", default="COM2")
    p.add_argument("--upl-port", default="COM7", help="UPL port: COMn (RS-232) or GPIB0::20::INSTR (GPIB, e.g. 82357B)")
    p.add_argument("--out-ch", default="out1")
    p.add_argument("--compare", metavar="RUN_DIR",
                   help="an earlier run's folder (or its results.json) to compare against in the report")
    add_output_args(p)
    args = p.parse_args()
    ch = args.out_ch
    other = load_other(args.compare) if args.compare else None

    dcx = DCX2496(args.dcx_port)
    dcx.enable_remote()
    dcx.set_eq_switch(ch, False)
    dcx.set_crossover(ch, hp_type="off", lp_type="off")
    dcx.set_limiter(ch, enable=False)
    dcx.set_gain(ch, 0.0)
    time.sleep(0.3)

    u = connect(args.upl_port, 115200, 12.0)

    def drain():
        for _ in range(20):
            if u.query("SYST:ERR?").startswith("0"):
                return

    def setc(cmd, quiet=False):
        u.write(cmd)
        e = u.query("SYST:ERR?")
        if not e.startswith("0") and not quiet:
            print("  ! rejected: %-30s [%s]" % (cmd, e))
        return e.startswith("0")

    results = {"mode": args.mode}
    with Run("dcx_balanced_test", label=args.label or args.mode, outdir=args.outdir,
             title=f"DCX2496 {args.mode} output") as rep:
        rep.info("Mode", args.mode)
        rep.info("DCX output", f"{ch} (flat)")
        if other:
            rep.info("Compared with", f"{other['mode']} ({args.compare})")
        try:
            drain()
            for c in ["OUTP:TYPE BAL", "SOUR:FUNC SIN", "SOUR:LOWD ON",
                      "INP:TYPE BAL", "INP:SEL CH2I", "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'",
                      "SENS:VOLT:RANG:AUTO ON"]:
                setc(c)
            drain()

            print("=== [%s] level @ 1kHz, 1.0V DCX in, INP:LOW default ===" % args.mode)
            setc("SENS1:FUNCtion 'RMS'")
            setc("SOUR:FREQ 1000 HZ;*wai")
            setc("SOUR:VOLT 1.0 V;*wai")
            time.sleep(0.3)
            u.write("init:cont off;*wai")
            lvl_default = parse_num(u.query("sens:data?"))
            print("  level:", lvl_default, "V  (%.2f dB rel 1V)" % db(lvl_default))
            results["level_default"] = lvl_default

            print("=== [%s] THD+N @ 1kHz, 1.0V ===" % args.mode)
            setc("SENS1:FUNCtion 'THDN'")
            u.write("init:cont off;*wai")
            thdn = parse_num(u.query("sens:data?"))
            print("  THD+N:", thdn, "dB")
            results["thdn"] = thdn
            if lvl_default < 1e-4 or abs(thdn) < 5:
                msg = ("level near noise floor and/or THD+N near 0dB -- signal probably isn't "
                       "reaching the analyzer. Check the physical connections before trusting this run.")
                print("  WARNING: " + msg)
                rep.note(msg, warn=True)

            print("=== [%s] noise floor, generator muted ===" % args.mode)
            setc("SENS1:FUNCtion 'RMS'")
            setc("SOUR:VOLT 1e-20 V;*wai")
            noise = results["noise"] = {}
            for lowset in ["FLOat", "GROund"]:
                ok = setc("INP:LOW %s" % lowset)
                time.sleep(0.3)
                u.write("init:cont off;*wai")
                n = parse_num(u.query("sens:data?"))
                print("  INP:LOW %-6s -> noise %.6e V  (%s)" %
                      (lowset, n, "ok" if ok else "rejected -- INP:LOW may not apply in BAL type"))
                noise[lowset] = n
            setc("INP:LOW FLOat")  # restore a sane default

            print("=== [%s] frequency response, 1.0V ===" % args.mode)
            setc("SOUR:VOLT 1.0 V;*wai")
            runFR = results["freq_response"] = []
            for f in np.geomspace(20, 20000, 24):
                setc("SOUR:FREQ %.2f HZ;*wai" % f, quiet=True)
                time.sleep(0.15)
                u.write("init:cont off;*wai")
                lvl = parse_num(u.query("sens:data?"))
                runFR.append((float(f), lvl))
                print("  %8.1f Hz -> %.6f V" % (f, lvl))

            drain()
            u.write("sour:volt 0 V")
        finally:
            u.close()
            dcx.close()
            report(rep, results, other)


def load_other(path):
    if os.path.isdir(path):
        path = os.path.join(path, "results.json")
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def report(rep, res, other=None):
    rep.json("results.json", res, "everything, in the old output format")
    runs = [res] + ([other] if other else [])
    rep.heading("Summary")

    def cell(r, fn):
        try:
            return fn(r)
        except (KeyError, TypeError, IndexError):
            return float("nan")
    items = [("Level @ 1 kHz (V)", lambda r: r["level_default"]),
             ("Level re 1 V (dB)", lambda r: db(r["level_default"])),
             ("THD+N @ 1 kHz (dB)", lambda r: r["thdn"]),
             ("Noise, INP:LOW FLOat (µV)", lambda r: r["noise"]["FLOat"] * 1e6),
             ("Noise, INP:LOW GROund (µV)", lambda r: r["noise"]["GROund"] * 1e6)]
    rows = []
    for name, fn in items:
        vals = [cell(r, fn) for r in runs]
        row = [name] + vals
        if other:
            a, b = vals
            row.append(a - b if not (is_na(a) or is_na(b)) else float("nan"))
        rows.append(row)
    hdr = ["", res["mode"]] + ([other["mode"], "difference"] if other else [])
    rep.table(hdr, rows, formats=[None] + [".3f"] * (len(hdr) - 1))
    fr = res.get("freq_response")
    if fr:
        rep.csv("freq_response.csv", ["freq_Hz", "level_V"], fr)
        rep.heading("Frequency response (1 V in)")
        series = [(r["mode"], [p[0] for p in r["freq_response"]], [db(p[1]) for p in r["freq_response"]])
                  for r in runs if r.get("freq_response")]
        rep.plot("freq_response", series, xlabel="Frequency (Hz)", ylabel="Level (dBV)", logx=True)


if __name__ == "__main__":
    main()
