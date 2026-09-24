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
  10. Digital audio (B29)             (5 points: level L/R, freq, sample rate 48k/44.1k)
Every check the R&S program makes is counted: both channels wherever it checks both, and
the B1 generator's frequency (137 readings; runs before 2026-09-24 counted 121).
                                      -- skipped if no digital option

INSTRUMENT STATE. Like the real selftest this starts with *RST, which clears whatever is
on screen. Two ways it can end:
  --preserve   snapshot the complete setup first (MMEM:STOR:STAT 2, the FLAT_GEN.BAS idiom)
               and load it back at the end -- your front-panel setup survives. Writes a
               scratch file to the UPL's disk (--state-file), deleted afterwards.
  (default)    *RST again at the end, so the UPL is left in its analog power-on state and
               NOT in the digital D48/INT configuration of section 10 -- that leftover state
               silently broke the first DCX2496 sweep on 2026-09-23 (see CLAUDE.md).
Either way the generator is muted at the end, even if the run fails part-way.

HOW COMMANDS ARE SENT (lessons from CLAUDE.md, applied 2026-09-24):
  - one command per write; the R&S source's "<cmd>;*wai" is sent as <cmd> then *OPC?, so a
    slow first half can't make the PL2303 adapter double a byte in the rest of the line
  - SYST:ERR? after every setting command; a rejected command is printed where it happened
    and listed in the report (the original ignored them, so a rejection could skew a reading)
  - *CLS after *RST (*RST does not clear the error queue)
The measurement commands, their order and the tolerances are unchanged, so results stay
comparable with the 2026-09-22 run and with other units' R&S selftest reports. Before
2026-09-24 this script's pass/fail was laxer than R&S's: it counted only CH1 in sections 5-9,
never counted the B1 frequency or CH2, skipped the digital sample-rate checks, and didn't retry
the noise measurement as R&S does. All of that now matches the R&S program.

Usage:
  python upl_selftest.py --port COM2
  python upl_selftest.py --port COM2 --preserve              # keep the front-panel setup
  python upl_selftest.py --port COM2 --baud 19200 --label after_recal
  python upl_selftest.py --port GPIB0::20::INSTR          # over GPIB (--baud ignored)
  python upl_selftest.py --dry-run                        # no instrument: print the SCPI

Output: results/selftest/<label>_<timestamp>/ -- report.html (pass/fail tables per section),
report.txt (the classic text report), readings.csv, summary.txt. -o FILE also copies the
text report to FILE.

Remote-control baud: 115200 is confirmed working (set it on the UPL's OPTIONS panel, COM2 baud --
it's listed there even though the Vol.2 manual's SCPI baud-set table only printed up to 56000;
the front panel is correct, the manual's table was wrong/incomplete). Default here is 115200 --
make sure the UPL's OPTIONS panel COM2 baud matches, or pass --baud to override.

Live-verified 2026-09-24 (evening): --preserve (setup restored exactly, scratch file deleted),
the per-command error checks (none rejected), sections 1-9. The new sample-rate checks in
section 10 are dry-run only so far.
"""

import argparse
import sys
import time

try:
    from upl_capture import connect, DryRunUPL, preserve_state, STATE_TMP
    from report import Run, add_output_args
except ImportError:
    sys.exit("upl_capture.py and report.py must be in the same folder.")


def parse_num(s):
    try:
        return float(s.strip().split()[0])
    except Exception:
        return float("nan")


NA_SENTINEL = 9.93e37


def is_na(v):
    return v != v or abs(v) > 1e30  # NaN or the SCPI "not available" sentinel (~9.93e37)


def fp(d, unit="%"):
    """A deviation for the log line; 'n/a' when the reading was the no-value sentinel."""
    if d is None:
        return "n/a"
    return ("%+.3f%s" if abs(d) < 1 else "%+.2f%s") % (d, unit)


class DrySelftestUPL(DryRunUPL):
    """--dry-run stub that reports this unit's options and serial, so every section runs."""
    OPT = "B1(0.01),B29(2.16),B21,B22,B4,B5(1.62),B6,0,B10,0,B23,0"

    def _reply(self, cmd):
        c = cmd.strip().upper()
        if c.startswith("*OPT?"):
            return self.OPT
        if c.startswith("DIAG:DEV:DATA?"):
            return "100330" if self.diag_addr == 0 else "6"
        return super()._reply(cmd)


class Selftest:
    def __init__(self, u, settle):
        self.u = u
        self.settle = settle
        self.results = []
        self.log_lines = []
        self.rejected = []          # (command, error) for every command the UPL refused

    def log(self, s=""):
        print(s)
        self.log_lines.append(s)

    def drain(self, context="(queued)", record=True):
        """Empty the error queue, recording anything in it rather than throwing it away.
        record=False only logs (errors left over from before this run aren't its rejections)."""
        for _ in range(20):
            e = self.u.query("SYST:ERR?").strip()
            if e.startswith("0"):
                return
            if record:
                self.reject(context, e)
            else:
                self.log("  (stale error from before this run, ignored: %s)" % e)

    def reject(self, cmd, err):
        self.rejected.append((cmd, err))
        self.log("  ! rejected: %-34s [%s]" % (cmd, err))

    def cmd(self, c):
        """One setting command, the way CLAUDE.md says to send them: a trailing ';*wai'
        becomes a separate *OPC? (no compound line with a slow first half), then SYST:ERR?."""
        wait = c.lower().endswith(";*wai")
        base = c[:-5] if wait else c
        self.u.write(base)
        if wait:
            self.u.query("*OPC?")
        e = self.u.query("SYST:ERR?").strip()
        if not e.startswith("0"):
            self.reject(base, e)
            self.drain(base)

    def q(self, c):
        return self.u.query(c).strip()

    def trigger(self):
        """Single measurement: R&S's own trigger, then *OPC? so it has finished before reading."""
        self.u.write("INIT:CONT OFF;*WAI")
        self.u.query("*OPC?")

    def meas1(self):
        self.trigger()
        return parse_num(self.q("sens:data?"))

    def meas2(self):
        return parse_num(self.q("sens:data2?"))

    def rec(self, section, chan, setv, meas, tol, unit=""):
        dev = None
        ok = True
        if is_na(meas):
            ok = False
        elif setv is None:                  # a limit, not a target: THD+N <= -93 dB, noise <= 2 uV
            ok = meas <= tol
        elif setv != 0:
            dev = 100 * (meas - setv) / setv if unit != "dB" else (meas - setv)
            ok = abs(dev) <= tol
        self.results.append(dict(section=section, chan=chan, set=setv, meas=meas,
                                  dev=dev, tol=tol, unit=unit, ok=ok))
        return dev, ok

    def noise(self, limit):
        """Noise in uV, both channels. Like the R&S program (lines 6140-6180, 6410-6450): while
        either channel is over the limit, measure again, up to 3 more times -- a single noise
        spike isn't a fault. Every attempt over the limit is logged."""
        for rep in range(4):
            self.trigger()
            w1 = 1e6 * parse_num(self.q("sens:data?"))
            w2 = 1e6 * parse_num(self.q("sens:data2?"))
            if (w1 <= limit and w2 <= limit) or rep == 3:
                return w1, w2
            self.log("  (attempt %d over %g uV: CH1 %.2f CH2 %.2f -- measuring again)" % (rep + 1, limit, w1, w2))

    def reset(self):
        self.u.write("*RST")
        self.u.query("*OPC?")
        self.u.write("*CLS")               # *RST leaves the error queue as it was

    def finish_state(self, preserved):
        """End of run, success or not: mute the generator; without --preserve, *RST back to the
        analog power-on state so no later script inherits section 10's INST D48 / INP:TYPE INT."""
        try:
            self.u.write("SOUR:VOLT 0 V")
            if not preserved:
                self.reset()
                self.u.write("SOUR:VOLT 0 V")
            state = "INST %s, INST2 %s, INP:TYPE %s" % (self.q("INST?"), self.q("INST2?"), self.q("INP:TYPE?"))
            self.log("  end state: " + state + (" (before restoring the snapshot)" if preserved else ""))
            return state
        except Exception as e:           # never mask the real error
            self.log("  WARNING: could not reset the instrument at the end: %s" % e)
            return "unknown (%s)" % e

    def run(self):
        cmd, q, log = self.cmd, self.q, self.log
        settle = self.settle

        self.drain(record=False)
        log("=== *RST, options, serial number ===")
        self.reset()
        self.drain("(after *RST)")
        opt = q("*opt?")
        log("  *OPT?: " + opt)
        opt_pad = "," + opt + ","
        B1 = ",B1(" in opt_pad or ",B1," in opt_pad
        Dig = ",B29" in opt_pad or ",B2(" in opt_pad or ",B2," in opt_pad

        cmd("DIAG:DEV SERN")
        cmd("DIAG:DEV:ADDR 0")
        ser0 = q("DIAG:DEV:DATA?")
        cmd("DIAG:DEV:ADDR 1")
        ser1 = q("DIAG:DEV:DATA?")
        log("  Serial number: " + ser0 + "/" + ser1)
        self.serial = ser0 + "/" + ser1
        self.options = opt
        self.drain()

        log("=== basic settings ===")
        for c in ["SOUR:LOWD OFF", "OUTP:TYPE BAL", "SOUR:VOLT 1e-20 V", "INP:SEL CH2I", "INP:TYPE GEN2",
                  "SENS2:FUNC 'OFF'", "SENS3:FUNC 'OFF'"]:
            cmd(c)
        cmd("CAL:ZERO:AUTO ONCE;*wai")
        cmd("INST2 A100")
        cmd("CAL:ZERO:AUTO ONCE;*wai")
        cmd("INST2 A22")
        log("  auto-zero cal done, back on A22")

        log("=== 1. Generator range control (3V range then 30V range) ===")
        cmd("SENS:VOLT:RANG:AUTO OFF")
        cmd("SENS:VOLT:RANG 3 V")
        for volt, tol in [(0.030, 2), (0.250, 1.8), (0.500, 1.6), (1.000, 1.6), (2.000, 1.6)]:
            cmd("sour:volt " + str(volt) + " V;*wai")
            m1, m2 = self.meas1(), self.meas2()
            d1, ok1 = self.rec("Generator range", "CH1", volt, m1, tol)
            d2, ok2 = self.rec("Generator range", "CH2", volt, m2, tol)
            log("  set %7.3f V -> CH1 %.5f V (%s)  CH2 %.5f V (%s)  tol %s%%%s" %
                (volt, m1, fp(d1), m2, fp(d2), tol, "" if ok1 and ok2 else "  <-- OUT OF TOL"))
        cmd("SENS:VOLT:RANG 30 V")
        cmd("SOUR:VOLT:LIM 20 V")
        volt, tol = 20.000, 1.6
        cmd("sour:volt " + str(volt) + " V;*wai")
        m1, m2 = self.meas1(), self.meas2()
        d1, ok1 = self.rec("Generator range", "CH1", volt, m1, tol)
        d2, ok2 = self.rec("Generator range", "CH2", volt, m2, tol)
        log("  set %7.3f V -> CH1 %.5f V (%s)  CH2 %.5f V (%s)  tol %s%%%s" %
            (volt, m1, fp(d1), m2, fp(d2), tol, "" if ok1 and ok2 else "  <-- OUT OF TOL"))
        cmd("sour:volt 0 V")

        if B1:
            log("=== 2. Low distortion generator (B1): level & frequency accuracy ===")
            cmd("SENS3:FUNC 'FREQ'")
            cmd("SENS:VOLT:RANG 3 V")
            cmd("SOUR:LOWD ON")
            for volt, freq, tol, tfreq in [(1.0, 1000, 1.6, 0.8), (1.0, 150, 2.7, 0.8), (1.0, 5000, 2.7, 0.8)]:
                cmd("sour:freq " + str(freq) + "HZ;*wai")
                time.sleep(settle)
                cmd("sour:volt " + str(volt) + " V;*wai")
                self.trigger()
                m1 = parse_num(q("sens:data?"))
                m2 = parse_num(q("sens:data2?"))
                mf = parse_num(q("sens3:data?"))
                d1, ok1 = self.rec("Low-dist gen", str(freq) + "Hz", volt, m1, tol)
                d2, ok2 = self.rec("Low-dist gen", str(freq) + "Hz CH2", volt, m2, tol)
                fd, okf = self.rec("Low-dist gen", str(freq) + "Hz freq", freq, mf, tfreq)
                log("  %6d Hz set %s V -> CH1 %.5f V (%s)  CH2 %.5f V (%s)  freq %.2f Hz (%s)  tol %s%%/%s%%%s" %
                    (freq, volt, m1, fp(d1), m2, fp(d2), mf, fp(fd), tol, tfreq,
                     "" if ok1 and ok2 and okf else "  <-- OUT OF TOL"))
            for c in ["INST2 A100", "INP:SEL CH2I", "INP:TYPE GEN2", "SENS:VOLT:RANG:AUTO OFF",
                      "SENS:VOLT:RANG 3 V", "SENS2:FUNC 'OFF'", "SENS3:FUNC 'FREQ'"]:
                cmd(c)
            freq, volt, tol, tfreq = 25000, 1.0, 2.7, 0.8
            cmd("sour:freq " + str(freq) + "HZ;*wai")
            time.sleep(settle)
            self.trigger()
            m1 = parse_num(q("sens:data?"))
            m2 = parse_num(q("sens:data2?"))
            mf = parse_num(q("sens3:data?"))
            d1, ok1 = self.rec("Low-dist gen", str(freq) + "Hz", volt, m1, tol)
            d2, ok2 = self.rec("Low-dist gen", str(freq) + "Hz CH2", volt, m2, tol)
            fd, okf = self.rec("Low-dist gen", str(freq) + "Hz freq", freq, mf, tfreq)
            log("  %6d Hz set %s V -> CH1 %.5f V (%s)  CH2 %.5f V (%s)  freq %.2f Hz (%s)  tol %s%%/%s%%%s" %
                (freq, volt, m1, fp(d1), m2, fp(d2), mf, fp(fd), tol, tfreq,
                 "" if ok1 and ok2 and okf else "  <-- OUT OF TOL"))
            cmd("INST2 A22")
        else:
            log("=== 2. Low distortion generator: SKIPPED (B1 not reported by *OPT?) ===")

        log("=== 3. Analyzer ranges: full sweep, 1kHz / 40Hz / 15kHz, 16 points each ===")
        for c in ["SENS3:FUNC 'OFF'", "SOUR:LOWD OFF", "SOUR:VOLT:LIM 20 V", "OUTP:TYPE BAL", "SOUR:VOLT 1e-20 V",
                  "INP:SEL CH2I", "INP:TYPE GEN2", "SENS2:FUNC 'OFF'", "SENS3:FUNC 'OFF'",
                  "SENS:VOLT:RANG:AUTO OFF"]:
            cmd(c)

        levels = [0.018, 0.030, 0.060, 0.100, 0.180, 0.300, 0.600, 1.000, 1.800, 3.000, 6.000, 10.000, 18.000]
        freq_plan = [
            (1000, "1kHz", 1.5, [(30, 1.6), (60, 1.6), (100, 1.8)]),
            (40, "40Hz", 2.7, [(30, 2.7), (60, 2.8), (100, 3.0)]),
            (15000, "15kHz", 2.7, [(30, 2.7), (60, 2.8), (100, 3.0)]),
        ]

        last_volt = None
        for freq, label, tol, extra_ranges in freq_plan:
            log("  --- @ " + label + " ---")
            cmd("SOUR:FREQ " + str(freq) + " HZ;*wai")
            time.sleep(settle)  # let the generator settle after a frequency change before the first read
            for volt in levels:
                cmd("SENS:VOLT:RANG " + str(volt) + " V")
                cmd("sour:volt " + str(volt) + " V;*wai")
                m1, m2 = self.meas1(), self.meas2()
                d1, ok1 = self.rec("Analyzer range @" + label, "CH1", volt, m1, tol)
                d2, ok2 = self.rec("Analyzer range @" + label, "CH2", volt, m2, tol)
                log("    %7.3f V -> CH1 %.6f V (%s)  CH2 %.6f V (%s)  tol %s%%%s" %
                    (volt, m1, fp(d1), m2, fp(d2), tol, "" if ok1 and ok2 else "  <-- OUT OF TOL"))
                last_volt = volt
            for rng, rtol in extra_ranges:
                cmd("SENS:VOLT:RANG " + str(rng) + " V")
                m1, m2 = self.meas1(), self.meas2()
                d1, ok1 = self.rec("Analyzer range @" + label, "CH1", last_volt, m1, rtol)
                d2, ok2 = self.rec("Analyzer range @" + label, "CH2", last_volt, m2, rtol)
                log("    %3dV range -> CH1 %.6f V (%s vs %sV)  CH2 %.6f V (%s)  tol %s%%%s" %
                    (rng, m1, fp(d1), last_volt, m2, fp(d2), rtol, "" if ok1 and ok2 else "  <-- OUT OF TOL"))
            cmd("sour:volt 0 V;*wai")

        log("=== 4. Inherent THD+N @ 1kHz, 2V (A22, tol <= -93dB) ===")
        for c in ["SOUR:FREQ 1 KHZ", "SENS:FUNC 'THDN'", "SOUR:VOLT 2V", "INP:SEL CH2I", "INP:TYPE GEN2",
                  "SENS2:FUNC 'OFF'", "SENS3:FUNC 'OFF'", "SENS:VOLT:RANG:AUTO OFF", "SENS:VOLT:RANG 3 V"]:
            cmd(c)
        self.trigger()
        w1 = parse_num(q("sens:data?"))
        w2 = parse_num(q("sens:data2?"))
        _, ok1 = self.rec("Inherent THD+N A22", "CH1", None, w1, -93, "dB")
        _, ok2 = self.rec("Inherent THD+N A22", "CH2", None, w2, -93, "dB")
        log("  CH1 %.2f dB   CH2 %.2f dB   (spec <= -93 dB)  %s" % (w1, w2, "PASS" if ok1 and ok2 else "FAIL"))

        log("=== 5. THD+N @ 1kHz -60dB (multitone linearity check, tol 0.5dB) ===")
        for c in ["SOUR:FUNC MULT", "SOUR:MULT:COUN 2", "SOUR:VOLT 2V", "SOUR:FREQ2 2000 HZ", "SOUR:VOLT2 2MV;*wai"]:
            cmd(c)
        self.trigger()
        w1 = parse_num(q("sens:data?"))
        w2 = parse_num(q("sens:data2?"))
        log("  CH1 %.2f dB (target -60, dev %+.2f dB)   CH2 %.2f dB (dev %+.2f dB)   tol 0.5dB" %
            (w1, w1 + 60, w2, w2 + 60))
        self.rec("THD+N -60dB linearity", "CH1", -60, w1, 0.5, "dB")
        self.rec("THD+N -60dB linearity", "CH2", -60, w2, 0.5, "dB")
        cmd("SOUR:FUNC SIN")

        log("=== 6. Inherent THD+N @ 1kHz in 100kHz analyzer (tol <= -84dB) ===")
        for c in ["INST2 A100", "INP:SEL CH2I", "INP:TYPE GEN2", "SENS:VOLT:RANG:AUTO OFF", "SENS:VOLT:RANG 3 V",
                  "SENS2:FUNC 'OFF'", "SENS3:FUNC 'OFF'", "SENS:FUNC 'THDN'"]:
            cmd(c)
        self.trigger()
        w1 = parse_num(q("sens:data?"))
        w2 = parse_num(q("sens:data2?"))
        _, ok1 = self.rec("Inherent THD+N A100", "CH1", None, w1, -84, "dB")
        _, ok2 = self.rec("Inherent THD+N A100", "CH2", None, w2, -84, "dB")
        log("  CH1 %.2f dB   CH2 %.2f dB   (spec <= -84 dB)  %s" % (w1, w2, "PASS" if ok1 and ok2 else "FAIL"))
        cmd("INST2 A22")

        log("=== 7. Inherent D2 (DFD) @ 10kHz/200Hz, 2V (tol <= -110dB) ===")
        for c in ["SOUR:FUNC DFD", "SOUR:FREQ:MEAN 10 KHZ", "SOUR:FREQ:DIFF 200 HZ", "SOUR:VOLT:TOT 2V",
                  "SENS:FUNC 'DFD';*wai"]:
            cmd(c)
        self.trigger()
        w1 = parse_num(q("sens:data?"))
        w2 = parse_num(q("sens:data2?"))
        _, ok1 = self.rec("Inherent D2 DFD", "CH1", None, w1, -110, "dB")
        _, ok2 = self.rec("Inherent D2 DFD", "CH2", None, w2, -110, "dB")
        log("  CH1 %.2f dB   CH2 %.2f dB   (spec <= -110 dB)  %s" % (w1, w2, "PASS" if ok1 and ok2 else "FAIL"))
        cmd("SOUR:FUNC SIN")

        log("=== 8. Inherent noise (22kHz analyzer, BAL/R300 input, tol <= 2uV) ===")
        for c in ["SOUR:VOLT 0 V", "SENS:FUNC 'RMS'", "INP:TYPE BAL", "INP:IMP R300", "SENS:VOLT:RANG 18 MV;*wai"]:
            cmd(c)
        w1, w2 = self.noise(2)
        _, ok1 = self.rec("Inherent noise A22", "CH1", None, w1, 2, "uV")
        _, ok2 = self.rec("Inherent noise A22", "CH2", None, w2, 2, "uV")
        log("  CH1 %.2f uV   CH2 %.2f uV   (spec <= 2 uV)  %s" % (w1, w2, "PASS" if ok1 and ok2 else "FAIL"))

        log("=== 9. Inherent noise (100kHz analyzer, tol <= 8uV) ===")
        cmd("INST2 A100")
        for c in ["SOUR:VOLT 0 V", "SENS:FUNC 'RMS'", "INP:TYPE BAL", "INP:IMP R300", "SENS:VOLT:RANG 18 MV;*wai"]:
            cmd(c)
        w1, w2 = self.noise(8)
        _, ok1 = self.rec("Inherent noise A100", "CH1", None, w1, 8, "uV")
        _, ok2 = self.rec("Inherent noise A100", "CH2", None, w2, 8, "uV")
        log("  CH1 %.2f uV   CH2 %.2f uV   (spec <= 8 uV)  %s" % (w1, w2, "PASS" if ok1 and ok2 else "FAIL"))
        cmd("INST2 A22")

        if Dig:
            log("=== 10. Digital audio (B29) ===")
            for c in ["INST D48", "INST2 D48", "INP:SEL BOTH", "INP:TYPE INT", "OUTP:AUD 24", "INP:AUD 24",
                      "SENS2:FUNC 'OFF'"]:
                cmd(c)
            self.trigger()
            w1 = parse_num(q("sens:data?"))
            w2 = parse_num(q("sens:data2?"))
            wf = parse_num(q("sens3:data?"))
            d1, _ = self.rec("Digital audio", "CH1 level", 0.5, w1, 0.1)
            d2, _ = self.rec("Digital audio", "CH2 level", 0.5, w2, 0.1)
            df, _ = self.rec("Digital audio", "freq", 1000, wf, 0.01)
            log("  Level CH1 %.6f FS (%s)  CH2 %.6f FS (%s)  Freq %.3f Hz (%s)  tol 0.1%%/0.01%%" %
                (w1, fp(d1), w2, fp(d2), wf, fp(df)))
            # the input sample rate, as the R&S program checks it next (lines 7420-7680):
            # measured at the default 48 kHz, then with the generator switched to 44.1 kHz
            cmd("SENS3:FUNC 'SFRE'")
            for fs, setup in ((48000, []), (44100, ["INP:SAMP:FREQ:MODE AUTO", "OUTP:SAMP:MODE F44"])):
                for c in setup:
                    cmd(c)
                self.trigger()
                ws = parse_num(q("sens3:data?"))
                ds, oks = self.rec("Digital audio", "sample rate %d" % fs, fs, ws, 0.01)
                log("  Sample rate %.1f Hz (target %d, %s)  tol 0.01%%%s" %
                    (ws, fs, fp(ds), "" if oks else "  <-- OUT OF TOL"))
        else:
            log("=== 10. Digital audio: SKIPPED (no digital option reported) ===")

        self.drain()
        cmd("sour:volt 0 V")

        fails = [r for r in self.results if not r["ok"]]
        log("")
        log("=== SUMMARY: %d readings, %d out of tolerance ===" % (len(self.results), len(fails)))
        for r in fails:
            log("  OUT OF TOL: %s" % r)
        if self.rejected:
            log("=== %d command(s) rejected by the UPL -- check them before trusting the readings ==="
                % len(self.rejected))
            for c, e in self.rejected:
                log("  %-34s [%s]" % (c, e))
        overall = "PASS" if not fails else "FAIL"
        log("=== OVERALL: %s ===" % overall)
        return overall, fails


def main():
    p = argparse.ArgumentParser(description="Run the UPL factory selftest remotely and report actual values.")
    p.add_argument("--port", help="COMn (RS-232, e.g. COM2) or GPIB0::20::INSTR (GPIB, e.g. 82357B)")
    p.add_argument("--baud", type=int, default=115200, help="remote-control baud (115200 confirmed working; match the UPL's OPTIONS-panel COM2 setting)")
    p.add_argument("--timeout", type=float, default=12.0, help="reply timeout seconds")
    p.add_argument("--settle", type=float, default=0.4, help="extra settle time after a frequency change")
    p.add_argument("--preserve", action="store_true",
                   help="snapshot the complete UPL setup first and load it back at the end "
                        "(MMEM:STOR/LOAD:STAT 2; writes a scratch file on the UPL, deleted after). "
                        "Without it the UPL is *RST to its analog power-on state at the end.")
    p.add_argument("--state-file", default=STATE_TMP, help=f"scratch path on the UPL for --preserve (default {STATE_TMP})")
    p.add_argument("--dry-run", action="store_true", help="no instrument: print the SCPI, canned replies")
    p.add_argument("-o", "--output", help="also copy the text report to this file")
    add_output_args(p, default_label="selftest")
    args = p.parse_args()
    if not args.port and not args.dry_run:
        p.error("--port is required (or use --dry-run)")

    u = DrySelftestUPL(echo=True) if args.dry_run else connect(args.port, args.baud, args.timeout)
    t = Selftest(u, 0.0 if args.dry_run else args.settle)
    overall = "INCOMPLETE"
    label = ("dryrun_" if args.dry_run else "") + args.label
    with Run("selftest", label=label, outdir=args.outdir,
             title="UPL selftest (R&S factory sequence)") as rep:
        rep.info("UPL", u.query("*IDN?").strip())
        try:
            with preserve_state(u, args.state_file, enabled=args.preserve) as ps:
                try:
                    overall, fails = t.run()
                finally:
                    end = t.finish_state(preserved=ps.enabled)
            if ps.enabled:
                t.log("  front-panel setup restored from " + args.state_file)
                end = "front-panel setup restored (snapshot %s)" % args.state_file
            rep.info("Instrument state after the run", end)
        finally:
            u.close()
            report(rep, t, overall)
    for out in filter(None, [args.output]):
        with open(out, "w") as f:
            f.write("\n".join(t.log_lines) + "\n")
        print("Text report also written to: %s" % out)
    return 0 if overall == "PASS" else 1


def report(rep, t, overall):
    """report.txt (the classic text report), readings.csv, and tables per section."""
    with open(rep.path("report.txt"), "w") as f:
        f.write("\n".join(t.log_lines) + "\n")
    rep.add_file("report.txt", "the text report, as the selftest has always written it")
    if getattr(t, "serial", None):
        rep.info("Serial number", t.serial)
        rep.info("Options (*OPT?)", t.options)
    rows = [(r["section"], r["chan"], r["set"], r["meas"], r["dev"], r["tol"], r["unit"], r["ok"])
            for r in t.results]
    rep.csv("readings.csv", ["section", "channel", "set", "measured", "deviation", "tolerance",
                             "unit", "ok"], rows)
    fails = [r for r in t.results if not r["ok"]]
    rep.headline = f"{overall}: {len(t.results) - len(fails)}/{len(t.results)} readings within tolerance"
    if t.rejected:
        rep.headline += f"; {len(t.rejected)} command(s) rejected"
        rep.heading("Commands the UPL rejected")
        rep.note("A rejected setting means the reading after it may not have been taken the way "
                 "R&S intended. Check these before trusting the results.", warn=True)
        rep.table(["Command", "Error"], t.rejected)
    if fails:
        rep.heading("Out of tolerance")
        rep.table(["Section", "Channel", "Set", "Measured", "Deviation", "Tolerance"],
                  [(r["section"], r["chan"], r["set"], r["meas"], _dev(r), _tol(r)) for r in fails],
                  status=["fail"] * len(fails))
    sections = {}
    for r in t.results:
        sections.setdefault(r["section"], []).append(r)
    for name, rs in sections.items():
        rep.heading(name)
        rep.table(["Channel", "Set", "Measured", "Deviation", "Tolerance"],
                  [(r["chan"], r["set"], r["meas"], _dev(r), _tol(r)) for r in rs],
                  status=["ok" if r["ok"] else "fail" for r in rs])


def _dev(r):
    if r["dev"] is None:
        return ""
    return "%+.3f %s" % (r["dev"], "dB" if r["unit"] == "dB" else "%")


def _tol(r):
    if r["tol"] is None:
        return ""
    unit = {"dB": "dB", "uV": "µV"}.get(r["unit"], "%")
    if r["set"] is None:
        return "≤ %g %s" % (r["tol"], unit)
    return "±%g %s" % (r["tol"], unit)


if __name__ == "__main__":
    sys.exit(main())
