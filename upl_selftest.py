#!/usr/bin/env python3
"""
upl_selftest.py - remote replica of R&S's factory SELFTEST_Program.TXT (UPL-native BASIC),
run from a PC over the RS232 remote-control link, reporting every underlying measured value
(the front-panel BASIC version only shows a PASS/FAIL indicator per line, not the numbers).

Command sequence and tolerances are copied from SELFTEST_Program.TXT (user-supplied, the
R&S factory self-test source, one directory up from this project) -- see CLAUDE.md for the
full cross-reference and the run recorded on 2026-09-22 (serial 100330/6, 121/121 pass).

Sections covered (full resolution, matching the original):
  1. Generator range control          (6 points: 30mV..20V)
  2. Low-distortion generator (B1)    (4 points: 150Hz..25kHz) -- skipped if B1 not installed
  3. Analyzer ranges                  (48 points: 16 levels x {1kHz, 40Hz, 15kHz})
  4. Inherent THD+N @ 1kHz/2V, A22    (spec <= -93 dB)
  5. THD+N -60dB linearity (2-tone)   (spec +-0.5 dB)
  6. Inherent THD+N @ 1kHz/2V, A100   (spec <= -84 dB)
  7. Inherent D2 (DFD) @10kHz/200Hz   (spec <= -110 dB)
  8. Inherent noise, A22              (spec <= 2 uV)
  9. Inherent noise, A100             (spec <= 8 uV)
  10. Digital audio level/freq (B29)  -- skipped if no digital option

IMPORTANT: this runs "*RST" at the start, which clears whatever setup is currently on screen
(same as the real selftest program). Reload your working setup afterwards if needed.

Usage:
  python upl_selftest.py --port COM2
  python upl_selftest.py --port COM2 --baud 19200 -o results/selftest_2026-09-22.txt

Remote-control baud: 115200 is confirmed working (set it on the UPL's OPTIONS panel, COM2 baud --
it's listed there even though the Vol.2 manual's SCPI baud-set table only printed up to 56000;
the front panel is correct, the manual's table was wrong/incomplete). Default here is 115200 --
make sure the UPL's OPTIONS panel COM2 baud matches, or pass --baud to override.
"""

import argparse
import sys
import time
import datetime

try:
    from upl_capture import UPL
except ImportError:
    sys.exit("upl_capture.py must be in the same folder (it provides the UPL serial class).")


def parse_num(s):
    try:
        return float(s.strip().split()[0])
    except Exception:
        return float("nan")


NA_SENTINEL = 9.93e37


def is_na(v):
    return v != v or abs(v) > 1e30  # NaN or the SCPI "not available" sentinel (~9.93e37)


class Selftest:
    def __init__(self, port, baud, timeout, settle):
        self.u = UPL(port, baud, timeout)
        self.settle = settle
        self.results = []
        self.log_lines = []

    def log(self, s=""):
        print(s)
        self.log_lines.append(s)

    def drain(self):
        for _ in range(20):
            if self.u.query("SYST:ERR?").startswith("0"):
                return

    def w(self, cmd):
        self.u.write(cmd)

    def q(self, cmd):
        return self.u.query(cmd).strip()

    def meas1(self):
        self.w("init:cont off;*wai")
        return parse_num(self.q("sens:data?"))

    def meas2(self):
        return parse_num(self.q("sens:data2?"))

    def rec(self, section, chan, setv, meas, tol, unit=""):
        dev = None
        ok = True
        if is_na(meas):
            ok = False
        elif setv not in (None, 0):
            dev = 100 * (meas - setv) / setv if unit != "dB" else (meas - setv)
            ok = abs(dev) <= tol
        self.results.append(dict(section=section, chan=chan, set=setv, meas=meas,
                                  dev=dev, tol=tol, unit=unit, ok=ok))
        return dev, ok

    def run(self):
        u, w, q, log = self.u, self.w, self.q, self.log
        settle = self.settle

        self.drain()
        log("=== *RST, options, serial number ===")
        w("*rst")
        q("*opc?")
        self.drain()
        opt = q("*opt?")
        log("  *OPT?: " + opt)
        opt_pad = "," + opt + ","
        B1 = ",B1(" in opt_pad or ",B1," in opt_pad
        Dig = ",B29" in opt_pad or ",B2(" in opt_pad or ",B2," in opt_pad

        w("DIAG:DEV SERN")
        w("DIAG:DEV:ADDR 0")
        ser0 = q("DIAG:DEV:DATA?")
        w("DIAG:DEV:ADDR 1")
        ser1 = q("DIAG:DEV:DATA?")
        log("  Serial number: " + ser0 + "/" + ser1)
        self.drain()

        log("=== basic settings ===")
        for c in ["SOUR:LOWD OFF", "OUTP:TYPE BAL", "SOUR:VOLT 1e-20 V", "INP:SEL CH2I", "INP:TYPE GEN2",
                  "SENS2:FUNC 'OFF'", "SENS3:FUNC 'OFF'"]:
            w(c)
        q("SYST:ERR?")
        self.drain()
        w("CAL:ZERO:AUTO ONCE;*wai")
        q("*opc?")
        w("INST2 A100")
        w("CAL:ZERO:AUTO ONCE;*wai")
        q("*opc?")
        w("INST2 A22")
        self.drain()
        log("  auto-zero cal done, back on A22")

        log("=== 1. Generator range control (3V range then 30V range) ===")
        w("SENS:VOLT:RANG:AUTO OFF")
        w("SENS:VOLT:RANG 3 V")
        for volt, tol in [(0.030, 2), (0.250, 1.8), (0.500, 1.6), (1.000, 1.6), (2.000, 1.6)]:
            w("sour:volt " + str(volt) + " V;*wai")
            m1, m2 = self.meas1(), self.meas2()
            d1, ok1 = self.rec("Generator range", "CH1", volt, m1, tol)
            d2, ok2 = self.rec("Generator range", "CH2", volt, m2, tol)
            log("  set %7.3f V -> CH1 %.5f V (%+.2f%%)  CH2 %.5f V (%+.2f%%)  tol %s%%%s" %
                (volt, m1, d1, m2, d2, tol, "" if ok1 and ok2 else "  <-- OUT OF TOL"))
        w("SENS:VOLT:RANG 30 V")
        w("SOUR:VOLT:LIM 20 V")
        volt, tol = 20.000, 1.6
        w("sour:volt " + str(volt) + " V;*wai")
        m1, m2 = self.meas1(), self.meas2()
        d1, ok1 = self.rec("Generator range", "CH1", volt, m1, tol)
        d2, ok2 = self.rec("Generator range", "CH2", volt, m2, tol)
        log("  set %7.3f V -> CH1 %.5f V (%+.2f%%)  CH2 %.5f V (%+.2f%%)  tol %s%%%s" %
            (volt, m1, d1, m2, d2, tol, "" if ok1 and ok2 else "  <-- OUT OF TOL"))
        w("sour:volt 0 V")
        self.drain()

        if B1:
            log("=== 2. Low distortion generator (B1): level & frequency accuracy ===")
            w("SENS3:FUNC 'FREQ'")
            w("SENS:VOLT:RANG 3 V")
            w("SOUR:LOWD ON")
            for volt, freq, tol, tfreq in [(1.0, 1000, 1.6, 0.8), (1.0, 150, 2.7, 0.8), (1.0, 5000, 2.7, 0.8)]:
                w("sour:freq " + str(freq) + "HZ;*wai")
                time.sleep(settle)
                w("sour:volt " + str(volt) + " V;*wai")
                w("init:cont off;*wai")
                m1 = parse_num(q("sens:data?"))
                m2 = parse_num(q("sens:data2?"))
                mf = parse_num(q("sens3:data?"))
                d1, ok1 = self.rec("Low-dist gen", str(freq) + "Hz", volt, m1, tol)
                fd = 100 * (mf - freq) / freq if not is_na(mf) else None
                log("  %6d Hz set %s V -> CH1 %.5f V (%+.2f%%)  freq meas %.2f Hz (%s)  tol %s%%/%s%%%s" %
                    (freq, volt, m1, d1, mf, ("%+.3f%%" % fd) if fd is not None else "N/A", tol, tfreq,
                     "" if ok1 else "  <-- OUT OF TOL"))
            w("INST2 A100")
            w("INP:SEL CH2I")
            w("INP:TYPE GEN2")
            w("SENS:VOLT:RANG:AUTO OFF")
            w("SENS:VOLT:RANG 3 V")
            w("SENS2:FUNC 'OFF'")
            w("SENS3:FUNC 'FREQ'")
            freq, volt, tol = 25000, 1.0, 2.7
            w("sour:freq " + str(freq) + "HZ;*wai")
            time.sleep(settle)
            w("init:cont off;*wai")
            m1 = parse_num(q("sens:data?"))
            mf = parse_num(q("sens3:data?"))
            d1, ok1 = self.rec("Low-dist gen", str(freq) + "Hz", volt, m1, tol)
            fd = 100 * (mf - freq) / freq if not is_na(mf) else None
            log("  %6d Hz set %s V -> CH1 %.5f V (%+.2f%%)  freq meas %.2f Hz (%s)  tol %s%%%s" %
                (freq, volt, m1, d1, mf, ("%+.3f%%" % fd) if fd is not None else "N/A", tol,
                 "" if ok1 else "  <-- OUT OF TOL"))
            w("INST2 A22")
            self.drain()
        else:
            log("=== 2. Low distortion generator: SKIPPED (B1 not reported by *OPT?) ===")

        log("=== 3. Analyzer ranges: full sweep, 1kHz / 40Hz / 15kHz, 16 points each ===")
        for c in ["SENS3:FUNC 'OFF'", "SOUR:LOWD OFF", "SOUR:VOLT:LIM 20 V", "OUTP:TYPE BAL", "SOUR:VOLT 1e-20 V",
                  "INP:SEL CH2I", "INP:TYPE GEN2", "SENS2:FUNC 'OFF'", "SENS3:FUNC 'OFF'",
                  "SENS:VOLT:RANG:AUTO OFF"]:
            w(c)
        q("SYST:ERR?")
        self.drain()

        levels = [0.018, 0.030, 0.060, 0.100, 0.180, 0.300, 0.600, 1.000, 1.800, 3.000, 6.000, 10.000, 18.000]
        freq_plan = [
            (1000, "1kHz", 1.5, [(30, 1.6), (60, 1.6), (100, 1.8)]),
            (40, "40Hz", 2.7, [(30, 2.7), (60, 2.8), (100, 3.0)]),
            (15000, "15kHz", 2.7, [(30, 2.7), (60, 2.8), (100, 3.0)]),
        ]

        last_volt = None
        for freq, label, tol, extra_ranges in freq_plan:
            log("  --- @ " + label + " ---")
            w("SOUR:FREQ " + str(freq) + " HZ;*wai")
            time.sleep(settle)  # let the generator settle after a frequency change before the first read
            for volt in levels:
                w("SENS:VOLT:RANG " + str(volt) + " V")
                w("sour:volt " + str(volt) + " V;*wai")
                m1, m2 = self.meas1(), self.meas2()
                d1, ok1 = self.rec("Analyzer range @" + label, "CH1", volt, m1, tol)
                d2, ok2 = self.rec("Analyzer range @" + label, "CH2", volt, m2, tol)
                log("    %7.3f V -> CH1 %.6f V (%+.2f%%)  CH2 %.6f V (%+.2f%%)  tol %s%%%s" %
                    (volt, m1, d1, m2, d2, tol, "" if ok1 and ok2 else "  <-- OUT OF TOL"))
                last_volt = volt
            for rng, rtol in extra_ranges:
                w("SENS:VOLT:RANG " + str(rng) + " V")
                m1, m2 = self.meas1(), self.meas2()
                d1, ok1 = self.rec("Analyzer range @" + label, "CH1", last_volt, m1, rtol)
                d2, ok2 = self.rec("Analyzer range @" + label, "CH2", last_volt, m2, rtol)
                log("    %3dV range -> CH1 %.6f V (%+.2f%% vs %sV)  CH2 %.6f V (%+.2f%%)  tol %s%%%s" %
                    (rng, m1, d1, last_volt, m2, d2, rtol, "" if ok1 and ok2 else "  <-- OUT OF TOL"))
            w("sour:volt 0 V;*wai")
        self.drain()

        log("=== 4. Inherent THD+N @ 1kHz, 2V (A22, tol <= -93dB) ===")
        for c in ["SOUR:FREQ 1 KHZ", "SENS:FUNC 'THDN'", "SOUR:VOLT 2V", "INP:SEL CH2I", "INP:TYPE GEN2",
                  "SENS2:FUNC 'OFF'", "SENS3:FUNC 'OFF'", "SENS:VOLT:RANG:AUTO OFF", "SENS:VOLT:RANG 3 V"]:
            w(c)
        q("SYST:ERR?")
        self.drain()
        w("init:cont off;*wai")
        w1 = parse_num(q("sens:data?"))
        w2 = parse_num(q("sens:data2?"))
        self.rec("Inherent THD+N A22", "CH1", None, w1, -93, "dB")
        self.rec("Inherent THD+N A22", "CH2", None, w2, -93, "dB")
        log("  CH1 %.2f dB   CH2 %.2f dB   (spec <= -93 dB)  %s" %
            (w1, w2, "PASS" if w1 <= -93 and w2 <= -93 else "FAIL"))

        log("=== 5. THD+N @ 1kHz -60dB (multitone linearity check, tol 0.5dB) ===")
        for c in ["SOUR:FUNC MULT", "SOUR:MULT:COUN 2", "SOUR:VOLT 2V", "SOUR:FREQ2 2000 HZ", "SOUR:VOLT2 2MV;*wai"]:
            w(c)
        w("init:cont off;*wai")
        w1 = parse_num(q("sens:data?"))
        w2 = parse_num(q("sens:data2?"))
        log("  CH1 %.2f dB (target -60, dev %+.2f dB)   CH2 %.2f dB (dev %+.2f dB)   tol 0.5dB" %
            (w1, w1 + 60, w2, w2 + 60))
        self.rec("THD+N -60dB linearity", "CH1", -60, w1, 0.5, "dB")
        w("SOUR:FUNC SIN")
        self.drain()

        log("=== 6. Inherent THD+N @ 1kHz in 100kHz analyzer (tol <= -84dB) ===")
        for c in ["INST2 A100", "INP:SEL CH2I", "INP:TYPE GEN2", "SENS:VOLT:RANG:AUTO OFF", "SENS:VOLT:RANG 3 V",
                  "SENS2:FUNC 'OFF'", "SENS3:FUNC 'OFF'", "SENS:FUNC 'THDN'"]:
            w(c)
        q("SYST:ERR?")
        self.drain()
        w("init:cont off;*wai")
        w1 = parse_num(q("sens:data?"))
        w2 = parse_num(q("sens:data2?"))
        self.rec("Inherent THD+N A100", "CH1", None, w1, -84, "dB")
        log("  CH1 %.2f dB   CH2 %.2f dB   (spec <= -84 dB)  %s" %
            (w1, w2, "PASS" if w1 <= -84 and w2 <= -84 else "FAIL"))
        w("INST2 A22")
        self.drain()

        log("=== 7. Inherent D2 (DFD) @ 10kHz/200Hz, 2V (tol <= -110dB) ===")
        for c in ["SOUR:FUNC DFD", "SOUR:FREQ:MEAN 10 KHZ", "SOUR:FREQ:DIFF 200 HZ", "SOUR:VOLT:TOT 2V",
                  "SENS:FUNC 'DFD';*wai"]:
            w(c)
        w("init:cont off;*wai")
        w1 = parse_num(q("sens:data?"))
        w2 = parse_num(q("sens:data2?"))
        self.rec("Inherent D2 DFD", "CH1", None, w1, -110, "dB")
        log("  CH1 %.2f dB   CH2 %.2f dB   (spec <= -110 dB)  %s" %
            (w1, w2, "PASS" if w1 <= -110 and w2 <= -110 else "FAIL"))
        w("SOUR:FUNC SIN")
        self.drain()

        log("=== 8. Inherent noise (22kHz analyzer, BAL/R300 input, tol <= 2uV) ===")
        for c in ["SOUR:VOLT 0 V", "SENS:FUNC 'RMS'", "INP:TYPE BAL", "INP:IMP R300", "SENS:VOLT:RANG 18 MV;*wai"]:
            w(c)
        w("init:cont off;*wai")
        w1 = 1e6 * parse_num(q("sens:data?"))
        w2 = 1e6 * parse_num(q("sens:data2?"))
        self.rec("Inherent noise A22", "CH1", None, w1, 2, "uV")
        log("  CH1 %.2f uV   CH2 %.2f uV   (spec <= 2 uV)  %s" %
            (w1, w2, "PASS" if w1 <= 2 and w2 <= 2 else "FAIL"))

        log("=== 9. Inherent noise (100kHz analyzer, tol <= 8uV) ===")
        w("INST2 A100")
        for c in ["SOUR:VOLT 0 V", "SENS:FUNC 'RMS'", "INP:TYPE BAL", "INP:IMP R300", "SENS:VOLT:RANG 18 MV;*wai"]:
            w(c)
        w("init:cont off;*wai")
        w1 = 1e6 * parse_num(q("sens:data?"))
        w2 = 1e6 * parse_num(q("sens:data2?"))
        self.rec("Inherent noise A100", "CH1", None, w1, 8, "uV")
        log("  CH1 %.2f uV   CH2 %.2f uV   (spec <= 8 uV)  %s" %
            (w1, w2, "PASS" if w1 <= 8 and w2 <= 8 else "FAIL"))
        w("INST2 A22")
        self.drain()

        if Dig:
            log("=== 10. Digital audio (B29) ===")
            for c in ["INST D48", "INST2 D48", "INP:SEL BOTH", "INP:TYPE INT", "OUTP:AUD 24", "INP:AUD 24", "SENS2:FUNC 'OFF'"]:
                w(c)
            q("SYST:ERR?")
            self.drain()
            w("init:cont off;*wai")
            w1 = parse_num(q("sens:data?"))
            w2 = parse_num(q("sens:data2?"))
            wf = parse_num(q("sens3:data?"))
            log("  Level CH1 %.6f FS (target 0.5, dev %+.3f%%)  CH2 %.6f FS  Freq %.3f Hz (target 1000)" %
                (w1, 100 * (w1 - 0.5) / 0.5, w2, wf))
            self.rec("Digital audio", "CH1 level", 0.5, w1, 0.1)
            self.rec("Digital audio", "freq", 1000, wf, 0.01)
        else:
            log("=== 10. Digital audio: SKIPPED (no digital option reported) ===")

        self.drain()
        w("sour:volt 0 V")

        fails = [r for r in self.results if not r["ok"]]
        log("")
        log("=== SUMMARY: %d readings, %d out of tolerance ===" % (len(self.results), len(fails)))
        for r in fails:
            log("  OUT OF TOL: %s" % r)
        overall = "PASS" if not fails else "FAIL"
        log("=== OVERALL: %s ===" % overall)
        return overall, fails


def main():
    p = argparse.ArgumentParser(description="Run the UPL factory selftest remotely and report actual values.")
    p.add_argument("--port", required=True, help="host serial port, e.g. COM2 or COM7")
    p.add_argument("--baud", type=int, default=115200, help="remote-control baud (115200 confirmed working; match the UPL's OPTIONS-panel COM2 setting)")
    p.add_argument("--timeout", type=float, default=12.0, help="reply timeout seconds")
    p.add_argument("--settle", type=float, default=0.4, help="extra settle time after a frequency change")
    p.add_argument("-o", "--output", help="also write the full report to this text file "
                                            "(default: upl_selftest_<timestamp>.txt)")
    args = p.parse_args()

    t = Selftest(args.port, args.baud, args.timeout, args.settle)
    overall, fails = t.run()
    t.u.close()

    out = args.output or ("upl_selftest_%s.txt" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(out, "w") as f:
        f.write("\n".join(t.log_lines) + "\n")
    print("\nFull report written to: %s" % out)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
