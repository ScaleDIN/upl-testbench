#!/usr/bin/env python3
"""
dcx_thdn.py - DCX2496 THD+N vs frequency and vs level, through the UPL (B1 generator +
analyzer), flat passthrough on the chosen output channel (EQ off, crossover off, unity gain).

Usage:
  python measurements/dcx_thdn.py --dcx-port COM2 --upl-port COM7
  python measurements/dcx_thdn.py --dcx-port COM2 --upl-port COM7 --label out3_after_recap

Output: results/dcx_thdn/<label>_<timestamp>/ (label defaults to the output channel) --
report.html (tables + graphs), freq_sweep.csv, level_sweep.csv, summary.txt.
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


def pct(db):
    """dB ratio -> %, or NaN for a UPL 'no value' reading."""
    return float("nan") if is_na(db) else 100 * 10 ** (db / 20)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dcx-port", default="COM2")
    p.add_argument("--upl-port", default="COM7", help="UPL port: COMn (RS-232) or GPIB0::20::INSTR (GPIB, e.g. 82357B)")
    p.add_argument("--out-ch", default="out1")
    p.add_argument("--level", type=float, default=1.0, help="generator level, V RMS, for the frequency sweep")
    p.add_argument("--freq", type=float, default=1000.0, help="fixed frequency for the level sweep")
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

    runA, runB = [], []
    with Run("dcx_thdn", label=args.label or args.out_ch, outdir=args.outdir,
             title="DCX2496 THD+N vs frequency and level") as rep:
        rep.info("DCX output", f"{args.out_ch} (flat: EQ off, crossover off, gain 0 dB)")
        rep.info("Generator", f"B1 low distortion; {args.level:g} V for the frequency sweep, "
                              f"{args.freq:g} Hz for the level sweep")
        try:
            drain()
            print("=== base config: B1 low-dist gen, external balanced path, THD+N ===")
            for c in ["OUTP:TYPE BAL", "SOUR:FUNC SIN", "SOUR:LOWD ON",
                      "INP:TYPE BAL", "INP:SEL CH2I",
                      "SENS1:FUNCtion 'THDN'", "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'",
                      "SENS:VOLT:RANG:AUTO ON"]:
                setc(c)
            drain()

            print("\n=== TEST A: THD+N vs frequency @ %.2fV ===" % args.level)
            setc("SOUR:VOLT %.3f V;*wai" % args.level)
            for f in np.geomspace(20, 20000, 24):
                setc("SOUR:FREQ %.2f HZ;*wai" % f, quiet=True)
                time.sleep(0.2)
                u.write("init:cont off;*wai")
                thdn = parse_num(u.query("sens:data?"))
                runA.append((float(f), thdn, pct(thdn)))
                print("  %8.1f Hz -> %7.2f dB" % (f, thdn))

            print("\n=== TEST B: THD+N vs level @ %.0fHz ===" % args.freq)
            setc("SOUR:FREQ %.2f HZ;*wai" % args.freq)
            for v in [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.4, 2.0, 2.8, 4.0, 5.5, 7.0]:
                setc("SOUR:VOLT %.3f V;*wai" % v, quiet=True)
                time.sleep(0.2)
                u.write("init:cont off;*wai")
                thdn = parse_num(u.query("sens:data?"))
                dbu = 20 * np.log10(v / 0.7746)
                runB.append((v, float(dbu), thdn, pct(thdn)))
                print("  %6.3f V (%+6.1f dBu) -> %7.2f dB" % (v, dbu, thdn))

            drain()
            u.write("sour:volt 0 V")
        finally:
            u.close()
            dcx.close()
            report(rep, runA, runB)


def report(rep, runA, runB):
    hdrA = ["freq_Hz", "thdn_dB", "thdn_pct"]
    hdrB = ["level_V", "level_dBu", "thdn_dB", "thdn_pct"]
    rep.csv("freq_sweep.csv", hdrA, runA)
    rep.csv("level_sweep.csv", hdrB, runB)
    if runA:
        worst = max((r for r in runA if not is_na(r[1])), key=lambda r: r[1], default=None)
        if worst:
            rep.headline = f"Worst THD+N {worst[1]:.1f} dB at {worst[0]:.0f} Hz"
        rep.heading("THD+N vs frequency")
        rep.plot("thdn_vs_freq", [("THD+N", [r[0] for r in runA], [r[1] for r in runA])],
                 xlabel="Frequency (Hz)", ylabel="THD+N (dB)", logx=True)
        rep.table(["Frequency (Hz)", "THD+N (dB)", "THD+N (%)"], runA, formats=[".1f", ".2f", ".4f"])
    if runB:
        rep.heading("THD+N vs level")
        rep.plot("thdn_vs_level", [("THD+N", [r[1] for r in runB], [r[2] for r in runB])],
                 xlabel="Generator level (dBu)", ylabel="THD+N (dB)")
        rep.table(["Level (V)", "Level (dBu)", "THD+N (dB)", "THD+N (%)"], runB,
                  formats=[".3f", "+.1f", ".2f", ".4f"])


if __name__ == "__main__":
    main()
