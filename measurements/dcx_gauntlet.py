#!/usr/bin/env python3
"""
dcx_gauntlet.py - DCX2496 gain-accuracy, filter-type comparison, and limiter-behavior
tests in one run, using the UPL (B1 generator + analyzer). See CLAUDE.md, 2026-09-23
"Full characterization gauntlet" for the reference results this produced.

Usage:
  python measurements/dcx_gauntlet.py --dcx-port COM2 --upl-port COM7 -o dcx_gauntlet.json
"""
import argparse
import json
import sys
import time

sys.path.insert(0, "..")
sys.path.insert(0, ".")
import numpy as np
from upl_capture import UPL
from dcx2496 import DCX2496, FILTER_TYPES


def parse_num(s):
    try:
        return float(s.strip().split()[0])
    except Exception:
        return float("nan")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dcx-port", default="COM2")
    p.add_argument("--upl-port", default="COM7")
    p.add_argument("--out-ch", default="out1")
    p.add_argument("--hp-freq", type=float, default=500.0, help="cutoff used for the filter-type comparison")
    p.add_argument("--filter-types", default="but12,but24,bes24,lr24,but48",
                   help="comma-separated, from: " + ",".join(FILTER_TYPES))
    p.add_argument("--limiter-thresh-db", type=float, default=-10.0)
    p.add_argument("-o", "--output", default="dcx_gauntlet.json")
    args = p.parse_args()
    ch = args.out_ch

    dcx = DCX2496(args.dcx_port)
    dcx.enable_remote()

    u = UPL(args.upl_port, 115200, 12.0)

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

    drain()
    reset_flat()
    for c in ["OUTP:TYPE BAL", "SOUR:FUNC SIN", "SOUR:LOWD ON",
              "INP:TYPE BAL", "INP:SEL CH2I", "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'",
              "SENS:VOLT:RANG:AUTO ON", "SENS1:FUNCtion 'RMS'"]:
        setc(c)
    drain()

    results = {}

    # A: gain accuracy
    print("=== A: DCX gain accuracy, 1kHz, 1.0V in ===")
    setc("SOUR:FREQ 1000 HZ;*wai")
    setc("SOUR:VOLT 1.0 V;*wai")
    gains = [-15, -10, -6, -3, 0, 3, 6, 10, 15]
    runA = []
    for g in gains:
        dcx.set_gain(ch, g)
        time.sleep(0.3)
        u.write("init:cont off;*wai")
        lvl = parse_num(u.query("sens:data?"))
        meas_db = 20 * np.log10(lvl / 1.0)
        err = meas_db - g
        runA.append((g, lvl, meas_db, err))
        print("  set %+5.1f dB -> measured %.5f V (%+6.2f dB)   error %+5.2f dB" % (g, lvl, meas_db, err))
    dcx.set_gain(ch, 0.0)
    results["gain_accuracy"] = runA

    # B: filter type comparison
    types = args.filter_types.split(",")
    print("\n=== B: filter-type comparison, HP=%sHz, LP off, types=%s ===" % (args.hp_freq, types))
    freqs = np.geomspace(max(20, args.hp_freq / 5), min(20000, args.hp_freq * 10), 24)
    runB = {}
    for ft in types:
        print("  --- %s ---" % ft)
        dcx.set_crossover(ch, hp_freq=args.hp_freq, hp_type=ft, lp_type="off")
        time.sleep(0.3)
        rows = []
        for f in freqs:
            setc("SOUR:FREQ %.2f HZ;*wai" % f, quiet=True)
            time.sleep(0.15)
            u.write("init:cont off;*wai")
            lvl = parse_num(u.query("sens:data?"))
            rows.append((f, lvl))
            print("    %8.1f Hz -> %.6f V" % (f, lvl))
        runB[ft] = rows
    dcx.set_crossover(ch, hp_type="off", lp_type="off")
    results["filter_types"] = {"freqs": list(freqs), "curves": runB}

    # C: limiter behavior
    print("\n=== C: limiter behavior, 1kHz, threshold=%sdB ===" % args.limiter_thresh_db)
    setc("SOUR:FREQ 1000 HZ;*wai")
    dcx.set_limiter(ch, enable=True, thresh_db=args.limiter_thresh_db, release_ms=100)
    time.sleep(0.3)
    levels = np.geomspace(0.05, 7.0, 20)
    runC = []
    for v in levels:
        setc("SOUR:VOLT %.4f V;*wai" % v, quiet=True)
        time.sleep(0.3)
        u.write("init:cont off;*wai")
        lvl = parse_num(u.query("sens:data?"))
        runC.append((v, lvl))
        print("  in %.4f V -> out %.4f V   (gain %+6.2f dB)" %
              (v, lvl, 20 * np.log10(lvl / v) if lvl > 0 else float("nan")))
    dcx.set_limiter(ch, enable=False)
    results["limiter"] = runC

    reset_flat()
    drain()
    u.write("sour:volt 0 V")
    u.close()
    dcx.close()

    with open(args.output, "w") as fp:
        json.dump(results, fp)
    print("\nWrote %s" % args.output)


if __name__ == "__main__":
    main()
