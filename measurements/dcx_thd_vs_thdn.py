#!/usr/bin/env python3
"""
dcx_thd_vs_thdn.py - separates DCX2496 THD+N into pure THD (harmonics only) vs noise
contribution, vs frequency. Reveals whether a "bad" THD+N number is really distortion
or just the DCX's noise floor -- see CLAUDE.md, 2026-09-23 for what this found.

Usage:
  python measurements/dcx_thd_vs_thdn.py --dcx-port COM2 --upl-port COM7 -o dcx_thd_vs_thdn.csv
"""
import argparse
import csv
import sys
import time

sys.path.insert(0, "..")
sys.path.insert(0, ".")
import numpy as np
from upl_capture import UPL
from dcx2496 import DCX2496


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
    p.add_argument("--level", type=float, default=1.0)
    p.add_argument("-o", "--output", default="dcx_thd_vs_thdn.csv")
    args = p.parse_args()

    dcx = DCX2496(args.dcx_port)
    dcx.enable_remote()
    dcx.set_eq_switch(args.out_ch, False)
    dcx.set_crossover(args.out_ch, hp_type="off", lp_type="off")
    dcx.set_gain(args.out_ch, 0.0)
    time.sleep(0.3)

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

    drain()
    for c in ["OUTP:TYPE BAL", "SOUR:FUNC SIN", "SOUR:LOWD ON", "SOUR:VOLT %.4f V" % args.level,
              "INP:TYPE BAL", "INP:SEL CH2I",
              "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'", "SENS:VOLT:RANG:AUTO ON"]:
        setc(c)
    drain()

    freqs = np.geomspace(20, 20000, 24)
    print("=== THD+N and THD (harmonics only), %s @ %.2fV RMS ===" % (args.out_ch, args.level))
    rows = []
    for f in freqs:
        setc("SOUR:FREQ %.2f HZ;*wai" % f, quiet=True)
        time.sleep(0.2)
        setc("SENS1:FUNCtion 'THDN'", quiet=True)
        u.write("init:cont off;*wai")
        thdn = parse_num(u.query("sens:data?"))
        setc("SENS1:FUNCtion 'THD'", quiet=True)
        u.write("init:cont off;*wai")
        thd = parse_num(u.query("sens:data?"))
        rows.append((f, thdn, thd, thd - thdn))
        print("  %8.1f Hz -> THD+N %7.2f dB   THD %7.2f dB   (noise contribution: %.1f dB)" %
              (f, thdn, thd, thd - thdn))

    drain()
    u.write("sour:volt 0 V")
    u.close()
    dcx.close()

    with open(args.output, "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["freq_hz", "thdn_db", "thd_db", "noise_contribution_db"])
        w.writerows(rows)
    print("\nWrote %s" % args.output)


if __name__ == "__main__":
    main()
