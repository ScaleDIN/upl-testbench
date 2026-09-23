#!/usr/bin/env python3
"""
dcx_thdn.py - DCX2496 THD+N vs frequency and vs level, through the UPL (B1 generator +
analyzer), flat passthrough on the chosen output channel (EQ off, crossover off, unity gain).

Usage:
  python scratchpad/dcx_thdn.py --dcx-port COM2 --upl-port COM7 -o dcx_thdn.csv
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
    p.add_argument("--level", type=float, default=1.0, help="generator level, V RMS, for the frequency sweep")
    p.add_argument("--freq", type=float, default=1000.0, help="fixed frequency for the level sweep")
    p.add_argument("-o", "--output", default="dcx_thdn.csv")
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
    print("=== base config: B1 low-dist gen, external balanced path, THD+N ===")
    for c in ["OUTP:TYPE BAL", "SOUR:FUNC SIN", "SOUR:LOWD ON",
              "INP:TYPE BAL", "INP:SEL CH2I",
              "SENS1:FUNCtion 'THDN'", "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'",
              "SENS:VOLT:RANG:AUTO ON"]:
        setc(c)
    drain()

    print("\n=== TEST A: THD+N vs frequency @ %.2fV ===" % args.level)
    setc("SOUR:VOLT %.3f V;*wai" % args.level)
    freqs = np.geomspace(20, 20000, 24)
    runA = []
    for f in freqs:
        setc("SOUR:FREQ %.2f HZ;*wai" % f, quiet=True)
        time.sleep(0.2)
        u.write("init:cont off;*wai")
        thdn = parse_num(u.query("sens:data?"))
        runA.append((f, thdn))
        print("  %8.1f Hz -> %7.2f dB" % (f, thdn))

    print("\n=== TEST B: THD+N vs level @ %.0fHz ===" % args.freq)
    setc("SOUR:FREQ %.2f HZ;*wai" % args.freq)
    levels = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.4, 2.0, 2.8, 4.0, 5.5, 7.0]
    runB = []
    for v in levels:
        setc("SOUR:VOLT %.3f V;*wai" % v, quiet=True)
        time.sleep(0.2)
        u.write("init:cont off;*wai")
        thdn = parse_num(u.query("sens:data?"))
        dbu = 20 * np.log10(v / 0.7746)
        runB.append((v, dbu, thdn))
        print("  %6.3f V (%+6.1f dBu) -> %7.2f dB" % (v, dbu, thdn))

    drain()
    u.write("sour:volt 0 V")
    u.close()
    dcx.close()

    with open(args.output, "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["--- freq sweep ---"])
        w.writerow(["freq_hz", "thdn_db"])
        w.writerows(runA)
        w.writerow([])
        w.writerow(["--- level sweep ---"])
        w.writerow(["level_v", "level_dbu", "thdn_db"])
        w.writerows(runB)
    print("\nWrote %s" % args.output)


if __name__ == "__main__":
    main()
