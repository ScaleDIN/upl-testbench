#!/usr/bin/env python3
"""
dcx_thd_vs_thdn.py - separates DCX2496 THD+N into pure THD (harmonics only) vs noise
contribution, vs frequency. Reveals whether a "bad" THD+N number is really distortion
or just the DCX's noise floor -- see CLAUDE.md, 2026-09-23 for what this found.

Usage:
  python measurements/dcx_thd_vs_thdn.py --dcx-port COM2 --upl-port COM7 [--label NAME]

Output: results/dcx_thd_vs_thdn/<label>_<timestamp>/ (label defaults to the output
channel) -- report.html (table + graph), thd_vs_thdn.csv, summary.txt.
"""
import argparse
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


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dcx-port", default="COM2")
    p.add_argument("--upl-port", default="COM7", help="UPL port: COMn (RS-232) or GPIB0::20::INSTR (GPIB, e.g. 82357B)")
    p.add_argument("--out-ch", default="out1")
    p.add_argument("--level", type=float, default=1.0)
    add_output_args(p)
    args = p.parse_args()

    dcx = DCX2496(args.dcx_port)
    dcx.enable_remote()
    dcx.set_eq_switch(args.out_ch, False)
    dcx.set_crossover(args.out_ch, hp_type="off", lp_type="off")
    dcx.set_gain(args.out_ch, 0.0)
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

    rows = []
    with Run("dcx_thd_vs_thdn", label=args.label or args.out_ch, outdir=args.outdir,
             title="DCX2496 THD vs THD+N") as rep:
        rep.info("DCX output", f"{args.out_ch} (flat: EQ off, crossover off, gain 0 dB)")
        rep.info("Generator", f"B1 low distortion, {args.level:g} V")
        try:
            drain()
            for c in ["OUTP:TYPE BAL", "SOUR:FUNC SIN", "SOUR:LOWD ON", "SOUR:VOLT %.4f V" % args.level,
                      "INP:TYPE BAL", "INP:SEL CH2I",
                      "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'", "SENS:VOLT:RANG:AUTO ON"]:
                setc(c)
            drain()

            print("=== THD+N and THD (harmonics only), %s @ %.2fV RMS ===" % (args.out_ch, args.level))
            for f in np.geomspace(20, 20000, 24):
                setc("SOUR:FREQ %.2f HZ;*wai" % f, quiet=True)
                time.sleep(0.2)
                setc("SENS1:FUNCtion 'THDN'", quiet=True)
                u.write("init:cont off;*wai")
                thdn = parse_num(u.query("sens:data?"))
                setc("SENS1:FUNCtion 'THD'", quiet=True)
                u.write("init:cont off;*wai")
                thd = parse_num(u.query("sens:data?"))
                gap = float("nan") if is_na(thd) or is_na(thdn) else thd - thdn
                rows.append((float(f), thdn, thd, gap))
                print("  %8.1f Hz -> THD+N %7.2f dB   THD %7.2f dB   (noise contribution: %.1f dB)" %
                      (f, thdn, thd, gap))

            drain()
            u.write("sour:volt 0 V")
        finally:
            u.close()
            dcx.close()
            report(rep, rows)


def report(rep, rows):
    rep.csv("thd_vs_thdn.csv", ["freq_hz", "thdn_db", "thd_db", "noise_contribution_db"], rows)
    if not rows:
        return
    rep.note("THD counts harmonics only; THD+N adds noise. Where the two lines are far apart, "
             "noise dominates; where they meet, real harmonic distortion does. THD reads n/a at "
             "high frequencies when the harmonics fall outside the analyzer bandwidth.")
    xs = [r[0] for r in rows]
    rep.plot("thd_vs_thdn", [("THD+N", xs, [r[1] for r in rows]), ("THD", xs, [r[2] for r in rows])],
             xlabel="Frequency (Hz)", ylabel="dB", logx=True)
    rep.table(["Frequency (Hz)", "THD+N (dB)", "THD (dB)", "THD − THD+N (dB)"], rows,
              formats=[".1f", ".2f", ".2f", ".1f"])


if __name__ == "__main__":
    main()
