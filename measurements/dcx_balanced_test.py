#!/usr/bin/env python3
"""
dcx_balanced_test.py - compare a DCX2496 output measured balanced (XLR direct into the
UPL) vs single-ended (via XLR-to-RCA-to-XLR adapters into the same UPL jack). Run it once
per physical wiring state with a different --mode label, then diff the two output files.
See CLAUDE.md, 2026-09-23 "Balanced vs single-ended comparison" for the reference results.

IMPORTANT: the UPL analyzer input is always the same physical XLR jack (INP:TYPE BAL is the
only input-type option) -- "single-ended" here means only pin2/hot is actually driven
upstream, via the adapter chain, not a different UPL setting. If a run shows a level near
the analyzer's noise floor (~1e-5V) with THD+N near 0dB, the signal isn't actually reaching
the analyzer -- check the physical connections before trusting the numbers.

Usage:
  python measurements/dcx_balanced_test.py balanced     --dcx-port COM2 --upl-port COM7
  python measurements/dcx_balanced_test.py single_ended --dcx-port COM2 --upl-port COM7
"""
import argparse
import json
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
    p.add_argument("mode", help="a label for this run, e.g. 'balanced' or 'single_ended'")
    p.add_argument("--dcx-port", default="COM2")
    p.add_argument("--upl-port", default="COM7")
    p.add_argument("--out-ch", default="out1")
    p.add_argument("-o", "--output", default=None, help="default: dcx_balanced_test_<mode>.json")
    args = p.parse_args()
    ch = args.out_ch

    dcx = DCX2496(args.dcx_port)
    dcx.enable_remote()
    dcx.set_eq_switch(ch, False)
    dcx.set_crossover(ch, hp_type="off", lp_type="off")
    dcx.set_limiter(ch, enable=False)
    dcx.set_gain(ch, 0.0)
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
    for c in ["OUTP:TYPE BAL", "SOUR:FUNC SIN", "SOUR:LOWD ON",
              "INP:TYPE BAL", "INP:SEL CH2I", "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'",
              "SENS:VOLT:RANG:AUTO ON"]:
        setc(c)
    drain()

    results = {"mode": args.mode}

    print("=== [%s] level @ 1kHz, 1.0V DCX in, INP:LOW default ===" % args.mode)
    setc("SENS1:FUNCtion 'RMS'")
    setc("SOUR:FREQ 1000 HZ;*wai")
    setc("SOUR:VOLT 1.0 V;*wai")
    time.sleep(0.3)
    u.write("init:cont off;*wai")
    lvl_default = parse_num(u.query("sens:data?"))
    print("  level:", lvl_default, "V  (%.2f dB rel 1V)" % (20 * np.log10(lvl_default / 1.0)))
    results["level_default"] = lvl_default

    print("=== [%s] THD+N @ 1kHz, 1.0V ===" % args.mode)
    setc("SENS1:FUNCtion 'THDN'")
    u.write("init:cont off;*wai")
    thdn = parse_num(u.query("sens:data?"))
    print("  THD+N:", thdn, "dB")
    results["thdn"] = thdn
    if lvl_default < 1e-4 or abs(thdn) < 5:
        print("  WARNING: level near noise floor and/or THD+N near 0dB -- signal probably isn't "
              "reaching the analyzer. Check the physical connections before trusting this run.")

    print("=== [%s] noise floor, generator muted ===" % args.mode)
    setc("SENS1:FUNCtion 'RMS'")
    setc("SOUR:VOLT 1e-20 V;*wai")
    noise = {}
    for lowset in ["FLOat", "GROund"]:
        ok = setc("INP:LOW %s" % lowset)
        time.sleep(0.3)
        u.write("init:cont off;*wai")
        n = parse_num(u.query("sens:data?"))
        print("  INP:LOW %-6s -> noise %.6e V  (%s)" %
              (lowset, n, "ok" if ok else "rejected -- INP:LOW may not apply in BAL type"))
        noise[lowset] = n
    results["noise"] = noise
    setc("INP:LOW FLOat")  # restore a sane default

    print("=== [%s] frequency response, 1.0V ===" % args.mode)
    setc("SOUR:VOLT 1.0 V;*wai")
    freqs = np.geomspace(20, 20000, 24)
    runFR = []
    for f in freqs:
        setc("SOUR:FREQ %.2f HZ;*wai" % f, quiet=True)
        time.sleep(0.15)
        u.write("init:cont off;*wai")
        lvl = parse_num(u.query("sens:data?"))
        runFR.append((f, lvl))
        print("  %8.1f Hz -> %.6f V" % (f, lvl))
    results["freq_response"] = runFR

    drain()
    u.write("sour:volt 0 V")
    u.close()
    dcx.close()

    out = args.output or ("dcx_balanced_test_%s.json" % args.mode)
    with open(out, "w") as fp:
        json.dump(results, fp)
    print("\nWrote %s" % out)


if __name__ == "__main__":
    main()
