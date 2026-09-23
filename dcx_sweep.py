#!/usr/bin/env python3
"""
dcx_sweep.py - closed-loop DCX2496 crossover/EQ characterization using the UPL as generator+analyzer.

Physical patch required: UPL generator output -> DCX2496 input A; DCX2496 output <N> -> UPL
analyzer input (both XLR balanced). Serial: DCX2496 over its RS232 port (dcx2496.py), UPL over
its RS232 remote-control port (upl_capture.py's UPL class).

This is the permanent version of the two ad-hoc scripts from the first live crossover test
(2026-09-23) -- see CLAUDE.md for that session's full narrative, including two real bugs found
along the way (leftover UPL digital-instrument state; a muted DCX output) that are worth reading
before assuming a flat/all-noise result means the link is broken.

Usage examples:
  # One highpass curve on output 1, 500Hz LR24, lowpass disabled, save + print
  python dcx_sweep.py --dcx-port COM2 --upl-port COM7 --out-ch out1 \
      --hp-freq 500 --hp-type lr24 --lp-type off -o sweep_500hz.csv

  # Sweep several HP cutoffs in one run, one CSV column per cutoff
  python dcx_sweep.py --dcx-port COM2 --upl-port COM7 --out-ch out1 \
      --hp-freq 100,300,1000,3000 --hp-type lr24 --lp-type off -o family.csv

  # Just re-measure whatever the DCX is currently configured to (no DCX writes at all)
  python dcx_sweep.py --dcx-port COM2 --upl-port COM7 --out-ch out1 --no-configure -o asis.csv

Before trusting a result: if every point comes back suspiciously identical, check the UPL's
INST?/INST2?/INP:TYPE? (should NOT be D48/D48/INT unless you intend a digital test). If every
point is noise-floor with no frequency lock, check the DCX output isn't muted.
"""

import argparse
import csv
import sys
import time

try:
    from upl_capture import UPL
except ImportError:
    sys.exit("upl_capture.py must be in the same folder.")
try:
    from dcx2496 import DCX2496, OUTPUT_CHANNELS, FILTER_TYPES
except ImportError:
    sys.exit("dcx2496.py must be in the same folder.")

import numpy as np


def parse_num(s):
    try:
        return float(s.strip().split()[0])
    except Exception:
        return float("nan")


class Sweeper:
    def __init__(self, dcx_port, upl_port, dcx_baud=38400, upl_baud=115200,
                 gen_level=1.0, settle=0.15, points=30, fmin=20.0, fmax=20000.0):
        self.dcx = DCX2496(dcx_port, baud=dcx_baud)
        self.dcx.enable_remote()
        self.u = UPL(upl_port, upl_baud, 12.0)
        self.gen_level = gen_level
        self.settle = settle
        self.freqs = np.geomspace(fmin, fmax, points)

    def close(self):
        self.u.write("sour:volt 0 V")
        self.u.close()
        self.dcx.close()

    def drain(self):
        for _ in range(20):
            if self.u.query("SYST:ERR?").startswith("0"):
                return

    def setc(self, cmd, quiet=False):
        self.u.write(cmd)
        e = self.u.query("SYST:ERR?")
        if not e.startswith("0") and not quiet:
            print("  ! rejected: %-30s [%s]" % (cmd, e))
        return e.startswith("0")

    def check_upl_state(self):
        """Sanity check for the 'flat/implausible result' failure mode from the first live test."""
        inst = self.u.query("INST?").strip()
        inst2 = self.u.query("INST2?").strip()
        intype = self.u.query("INP:TYPE?").strip()
        if inst == "D48" or inst2 == "D48" or intype not in ("BAL", "GEN2"):
            print("  WARNING: UPL is in unexpected state (INST=%s INST2=%s INP:TYPE=%s)."
                  " Consider *RST if results look flat/implausible." % (inst, inst2, intype))

    def configure_upl(self):
        self.drain()
        self.check_upl_state()
        for c in ["OUTP:TYPE BAL", "SOUR:FUNC SIN", "SOUR:LOWD ON",
                  "SOUR:VOLT %.4f V" % self.gen_level,
                  "INP:TYPE BAL", "INP:SEL CH2I",
                  "SENS:VOLT:RANG:AUTO ON", "SENS1:FUNCtion 'RMS'",
                  "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'"]:
            self.setc(c)
        self.drain()

    def run_sweep(self, label=""):
        rows = []
        for f in self.freqs:
            self.setc("SOUR:FREQ %.2f HZ;*wai" % f, quiet=True)
            time.sleep(self.settle)
            self.u.write("init:cont off;*wai")
            lvl = parse_num(self.u.query("sens:data?"))
            rows.append((f, lvl))
            print("  %s%8.1f Hz -> %.6f V" % (label, f, lvl))
        return rows

    def configure_dcx(self, out_ch, hp_freq=None, hp_type=None, lp_freq=None, lp_type=None,
                       gain_db=None):
        if gain_db is not None:
            self.dcx.set_gain(out_ch, gain_db)
        if any(v is not None for v in (hp_freq, hp_type, lp_freq, lp_type)):
            self.dcx.set_crossover(out_ch, hp_freq=hp_freq, hp_type=hp_type,
                                    lp_freq=lp_freq, lp_type=lp_type)
        time.sleep(0.3)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dcx-port", required=True)
    p.add_argument("--upl-port", required=True)
    p.add_argument("--dcx-baud", type=int, default=38400)
    p.add_argument("--upl-baud", type=int, default=115200)
    p.add_argument("--out-ch", default="out1", choices=list(OUTPUT_CHANNELS))
    p.add_argument("--gen-level", type=float, default=1.0, help="generator level, volts RMS")
    p.add_argument("--points", type=int, default=30)
    p.add_argument("--fmin", type=float, default=20.0)
    p.add_argument("--fmax", type=float, default=20000.0)
    p.add_argument("--settle", type=float, default=0.15)
    p.add_argument("--no-configure", action="store_true",
                    help="don't touch the DCX at all -- just sweep whatever it's currently set to")
    p.add_argument("--hp-freq", default=None, help="one value, or comma-separated list for a family of curves")
    p.add_argument("--hp-type", default=None, choices=FILTER_TYPES)
    p.add_argument("--lp-freq", type=float, default=None)
    p.add_argument("--lp-type", default=None, choices=FILTER_TYPES)
    p.add_argument("--gain-db", type=float, default=None)
    p.add_argument("-o", "--output", required=True, help="CSV output path")
    args = p.parse_args()

    sw = Sweeper(args.dcx_port, args.upl_port, args.dcx_baud, args.upl_baud,
                 args.gen_level, args.settle, args.points, args.fmin, args.fmax)
    try:
        sw.configure_upl()

        hp_list = [None]
        if args.hp_freq is not None:
            hp_list = [float(x) for x in args.hp_freq.split(",")]

        all_runs = {}
        for hpf in hp_list:
            label = ""
            if not args.no_configure:
                label = "[HP=%sHz] " % hpf if hpf is not None else ""
                print("=== configuring DCX %s: HP=%s LP=%s ===" % (args.out_ch, hpf, args.lp_freq))
                sw.configure_dcx(args.out_ch, hp_freq=hpf, hp_type=args.hp_type,
                                  lp_freq=args.lp_freq, lp_type=args.lp_type, gain_db=args.gain_db)
            rows = sw.run_sweep(label)
            all_runs[hpf if hpf is not None else "asis"] = rows

        with open(args.output, "w", newline="") as fp:
            w = csv.writer(fp)
            keys = list(all_runs.keys())
            w.writerow(["freq_hz"] + ["level_v_%s" % k for k in keys])
            for i, f in enumerate(sw.freqs):
                w.writerow([f] + [all_runs[k][i][1] for k in keys])
        print("\nWrote %s" % args.output)
    finally:
        sw.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
