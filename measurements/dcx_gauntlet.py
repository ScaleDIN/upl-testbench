#!/usr/bin/env python3
"""
dcx_gauntlet.py - DCX2496 gain-accuracy, filter-type comparison, and limiter-behavior
tests in one run, using the UPL (B1 generator + analyzer). See CLAUDE.md, 2026-09-23
"Full characterization gauntlet" for the reference results this produced.

Usage:
  python measurements/dcx_gauntlet.py --dcx-port COM2 --upl-port COM7 [--label NAME]

Output: results/dcx_gauntlet/<label>_<timestamp>/ (label defaults to the output channel)
-- report.html (tables + graphs), gain_accuracy.csv, filter_types.csv, limiter.csv,
results.json (everything, as before), summary.txt.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np  # noqa: E402
from upl_capture import connect  # noqa: E402
from dcx2496 import DCX2496, FILTER_TYPES  # noqa: E402
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
    p.add_argument("--dcx-port", default="COM2")
    p.add_argument("--upl-port", default="COM7", help="UPL port: COMn (RS-232) or GPIB0::20::INSTR (GPIB, e.g. 82357B)")
    p.add_argument("--out-ch", default="out1")
    p.add_argument("--hp-freq", type=float, default=500.0, help="cutoff used for the filter-type comparison")
    p.add_argument("--filter-types", default="but12,but24,bes24,lr24,but48",
                   help="comma-separated, from: " + ",".join(FILTER_TYPES))
    p.add_argument("--limiter-thresh-db", type=float, default=-10.0)
    add_output_args(p)
    args = p.parse_args()
    ch = args.out_ch

    dcx = DCX2496(args.dcx_port)
    dcx.enable_remote()

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

    def reset_flat():
        dcx.set_eq_switch(ch, False)
        dcx.set_crossover(ch, hp_type="off", lp_type="off")
        dcx.set_limiter(ch, enable=False)
        dcx.set_gain(ch, 0.0)
        time.sleep(0.3)

    results = {}
    with Run("dcx_gauntlet", label=args.label or ch, outdir=args.outdir,
             title="DCX2496 gain, filter types, limiter") as rep:
        rep.info("DCX output", ch)
        rep.info("Filter comparison", f"HP {args.hp_freq:g} Hz, LP off, types {args.filter_types}")
        rep.info("Limiter threshold", f"{args.limiter_thresh_db:g} dB (DCX scale)")
        try:
            drain()
            reset_flat()
            for c in ["OUTP:TYPE BAL", "SOUR:FUNC SIN", "SOUR:LOWD ON",
                      "INP:TYPE BAL", "INP:SEL CH2I", "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'",
                      "SENS:VOLT:RANG:AUTO ON", "SENS1:FUNCtion 'RMS'"]:
                setc(c)
            drain()

            # A: gain accuracy
            print("=== A: DCX gain accuracy, 1kHz, 1.0V in ===")
            setc("SOUR:FREQ 1000 HZ;*wai")
            setc("SOUR:VOLT 1.0 V;*wai")
            runA = results["gain_accuracy"] = []
            for g in [-15, -10, -6, -3, 0, 3, 6, 10, 15]:
                dcx.set_gain(ch, g)
                time.sleep(0.3)
                u.write("init:cont off;*wai")
                lvl = parse_num(u.query("sens:data?"))
                meas_db = db(lvl)
                err = meas_db - g
                runA.append((g, lvl, meas_db, err))
                print("  set %+5.1f dB -> measured %.5f V (%+6.2f dB)   error %+5.2f dB" % (g, lvl, meas_db, err))
            dcx.set_gain(ch, 0.0)

            # B: filter type comparison
            types = args.filter_types.split(",")
            print("\n=== B: filter-type comparison, HP=%sHz, LP off, types=%s ===" % (args.hp_freq, types))
            freqs = np.geomspace(max(20, args.hp_freq / 5), min(20000, args.hp_freq * 10), 24)
            runB = {}
            results["filter_types"] = {"freqs": [float(f) for f in freqs], "curves": runB}
            for ft in types:
                print("  --- %s ---" % ft)
                dcx.set_crossover(ch, hp_freq=args.hp_freq, hp_type=ft, lp_type="off")
                time.sleep(0.3)
                rows = runB[ft] = []
                for f in freqs:
                    setc("SOUR:FREQ %.2f HZ;*wai" % f, quiet=True)
                    time.sleep(0.15)
                    u.write("init:cont off;*wai")
                    lvl = parse_num(u.query("sens:data?"))
                    rows.append((float(f), lvl))
                    print("    %8.1f Hz -> %.6f V" % (f, lvl))
            dcx.set_crossover(ch, hp_type="off", lp_type="off")

            # C: limiter behavior
            print("\n=== C: limiter behavior, 1kHz, threshold=%sdB ===" % args.limiter_thresh_db)
            setc("SOUR:FREQ 1000 HZ;*wai")
            dcx.set_limiter(ch, enable=True, thresh_db=args.limiter_thresh_db, release_ms=100)
            time.sleep(0.3)
            runC = results["limiter"] = []
            for v in np.geomspace(0.05, 7.0, 20):
                setc("SOUR:VOLT %.4f V;*wai" % v, quiet=True)
                time.sleep(0.3)
                u.write("init:cont off;*wai")
                lvl = parse_num(u.query("sens:data?"))
                runC.append((float(v), lvl))
                print("  in %.4f V -> out %.4f V   (gain %+6.2f dB)" % (v, lvl, db(lvl, v)))
            dcx.set_limiter(ch, enable=False)

            reset_flat()
            drain()
            u.write("sour:volt 0 V")
        finally:
            u.close()
            dcx.close()
            report(rep, results)


def report(rep, results):
    rep.json("results.json", results, "all three tests, as one JSON (the old output format)")
    runA = results.get("gain_accuracy")
    if runA:
        rep.csv("gain_accuracy.csv", ["set_dB", "level_V", "measured_dB", "error_dB"], runA)
        errs = [r[3] for r in runA if not is_na(r[3])]
        if errs:
            rep.headline = (f"Gain error {min(errs):+.2f} to {max(errs):+.2f} dB "
                            f"over {runA[0][0]:+g} to {runA[-1][0]:+g} dB")
        rep.heading("A. Gain accuracy (1 kHz, 1 V in)")
        rep.plot("gain_error", [("error", [r[0] for r in runA], [r[3] for r in runA])],
                 xlabel="DCX gain setting (dB)", ylabel="Measured − set (dB)", hlines=[(0, None)],
                 height=3.2)
        rep.table(["Set (dB)", "Level (V)", "Measured (dB)", "Error (dB)"], runA,
                  formats=["+g", ".5f", "+.2f", "+.2f"])
    fb = results.get("filter_types")
    if fb and fb["curves"]:
        curves = fb["curves"]
        names = list(curves)
        n = max(len(c) for c in curves.values())
        freqs = fb["freqs"][:n]
        rows = [[f] + [curves[k][i][1] if i < len(curves[k]) else "" for k in names]
                for i, f in enumerate(freqs)]
        rep.csv("filter_types.csv", ["freq_Hz"] + [f"level_V_{k}" for k in names], rows)
        rep.heading("B. Filter types (high-pass)")
        rep.note("Each curve is in dB relative to its own highest reading, so the shapes compare directly.")
        series = []
        for k in names:
            lv = [r[1] for r in curves[k]]
            top = max((v for v in lv if not is_na(v) and v > 0), default=None)
            series.append((k, [r[0] for r in curves[k]], [db(v, top) if top else float("nan") for v in lv]))
        rep.plot("filter_types", series, xlabel="Frequency (Hz)", ylabel="dB re passband", logx=True)
        rep.table(["Frequency (Hz)"] + [f"{k} (V)" for k in names], rows)
    runC = results.get("limiter")
    if runC:
        rows = [(v, o, db(o, v)) for v, o in runC]
        rep.csv("limiter.csv", ["in_V", "out_V", "gain_dB"], rows)
        rep.heading("C. Limiter (1 kHz)")
        rep.plot("limiter", [("output", [db(r[0]) for r in rows], [db(r[1]) for r in rows]),
                             ("unity (no limiting)", [db(r[0]) for r in rows], [db(r[0]) for r in rows],
                              {"linestyle": "--", "marker": None, "linewidth": 1.0})],
                 xlabel="Input (dBV)", ylabel="Output (dBV)")
        rep.table(["In (V)", "Out (V)", "Gain (dB)"], rows, formats=[".4f", ".4f", "+.2f"])


if __name__ == "__main__":
    main()
