#!/usr/bin/env python3
"""
dac_test.py - characterize a DAC with the UPL, whatever its digital input.

Two signal sources, one set of measurements (--source):

  upl (default)  UPL digital generator (B29; B2 at 44.1/48 kHz only)  ->  DAC S/PDIF/AES
                 input. *OPT? is checked first: without either option the run stops
                 and points to --source pc.
                 Bit-exact, sample rate set by the UPL, and the interface itself
                 can be degraded on purpose (jitter via B22, cable simulator,
                 reduced signal voltage, word length, off-nominal sample rate).
  pc             this PC  --USB-->  DAC, or --USB--> USB-to-S/PDIF interface --> DAC's
                 coax/optical input: what a UPL without a digital audio option uses.
                 Tones synthesized here and played bit-exact through WASAPI exclusive
                 mode (Windows; --device N must be a 'Windows WASAPI' entry). jitter,
                 interface and polarity need the UPL generator and are skipped.

  In both cases:  DAC analog out (L, R)  ->  UPL analog analyzer (both channels).

For a player that can only play files itself (the NW-A306's own playback), use
tools/testsignals.py + measurements/upacd_test.py --external instead.

Tests (subcommands), in the order worth running them:
  setlevel   guided, for a DUT with a manual volume knob: plays 0 dBFS and shows
             volts and THD live while you turn it, toward --target V or to the
             loudest setting before clipping. --set-level runs it before any test
  check      lock at each sample rate, full-scale output level, L/R balance, DC offset
  fr         frequency response, both channels, broadband RMS *and* selective RMS,
             repeated -- separates "the DAC's response is odd" from "the measurement
             is being polluted" (images, hum, noise) and from "it's not repeatable"
  thdn       THD+N and THD vs level and vs frequency; dynamic range (AES17); idle noise
  fft        spectrum of a tone: harmonic signature, hum, and (--images) the
             reconstruction-filter images above fs/2, wideband analyzer
  imd        SMPTE 60 Hz + 7 kHz 4:1, and CCIF 19 + 20 kHz (DFD)
  xtalk      crosstalk L->R and R->L, selective
  zout       output impedance (200 kOhm vs 600 Ohm load)
  polarity   absolute polarity per channel (UPL's POLARITY function)
  jitter     jitter transfer: sinusoidal jitter injected with the aux generator,
             sidebands around an fs/4 tone measured, rejection vs jitter frequency
  interface  minimum input voltage, sample-rate lock range, 16/20/24-bit input
  stability  channel-asymmetric HF noise, level steadiness, 20 kHz/0 dBFS THD+N,
             output impedance x3 (relay contacts), optional live --monitor
 ASR-style (Audio Science Review's standard DAC set, as far as this UPL allows):
  jtest      Dunn J-test (fs/4 tone + 1-LSB square at fs/192), 24- and 16-bit, via an
             ARB time-table file uploaded to the UPL (MMEM:DATA, MD5-checked)
  multitone  17-tone multisine (UPL maximum; ASR uses 32), products between tones
  linearity  level error 0 to -130 dBFS, selective
  imdlevel   SMPTE and CCIF IMD vs level, -60 to 0 dBFS
  filter     white noise, wideband FFT: the reconstruction filter's shape
  impulse    impulse and step response: a one-sample impulse every 10 ms, captured with
             the UPL's WAVEFORM function on the 100 kHz analyzer (307.2 kHz sampling),
             averaged on the PC. Filter type (linear/minimum phase, NOS), ringing,
             polarity, and magnitude/phase response by FFT. Not part of `all`
 DUT control (--dut, optional):
  volsweep   THD+N/THD/level vs the DUT's own volume setting (not part of `all`)
  all        everything above, sensible defaults

Comparing with ASR: set the DAC to 2 V (unbalanced) / 4 V (balanced) at 0 dBFS if it
has a volume control (--set-level --target 2); ASR's SINAD = -(THD+N at 0 dBFS), printed by `thdn`. This
UPL's own THD+N floor is roughly -103 to -106 dB (loopback), well above an
APx555's, so SINAD figures beyond ~100 dB are the UPL's floor, not the DAC's.

Usage:
  python measurements/dac_test.py --dry-run all                      # offline, prints SCPI
  python measurements/dac_test.py --port COM7 check
  python measurements/dac_test.py --port COM7 --fs 44100,96000 fr
  python measurements/dac_test.py --port GPIB0::20::INSTR --label mydac all
  python measurements/dac_test.py --port COM7 --source pc --device N --fs 48000 \
      --settle 0.6 --label m51_usb all
  # NAD M51: log its state, run at 0 dB, restore after (omit --volume in fixed-output mode)
  python measurements/dac_test.py --port COM7 --source pc --device N --fs 96000 \
      --dut m51 --dut-port COM2 --volume 0 --label m51_usb all
  python measurements/dac_test.py --port COM7 --source pc --device N --fs 48000 \
      --dut m51 volsweep

Output: results/dac/<label>_<timestamp>/ (or --outdir) -- report.html with
tables and graphs, one CSV per test, and summary.txt (everything printed).

FIRST LIVE RUN 2026-09-24 (--source upl, NAD M51 over optical, 44.1-96 kHz): every
test ran; the bugs it found are fixed and commented in place (INP:SEL, A-weighting
order, trace feed after POL, CCIF at 44.1k, A100 selective floor). Still unverified
live: --source pc, and the items below not exercised by that run. Originally from
Vol.2, never sent to this unit before then:
  - the mixed setup, digital generator + analog analyzer (INST D48 + INST2 A22)
  - CONF:DAI HRM for 88.2/96 kHz. Vol.2 3.10.8.5 warns it also reduces
    analog-analyzer performance, so it's used only for those rates and set
    back to BRM at the end
  - SOUR2:FUNC JITT / SOUR2:VOLT <n> UI, OUTP:SIGN:LEV, OUTP:SAMP:MODE VAL
  - SENS:VOLT:APER:MODE GENT, SENS:FREQ:MODE GENT with 'RMSS', 'POL', 'MDIS'
  - --source pc: SENS:FREQ:MODE FIX + SENS:FREQ for selective RMS (Vol.2 p.3.114),
    THD/THD+N/DFD/MDIS finding their frequencies from the signal (their AUTO
    default), and the USB/WASAPI path itself. Allow extra --settle: the tone
    only changes after the audio buffer and the DAC's own latency.
Every config command is followed by SYST:ERR? and a rejection is printed, so the
first live run will show exactly what this firmware accepts. Run `check` first.

Conventions carried over from the rest of the project (see CLAUDE.md):
one command per write and *OPC? after slow ones (the PL2303 byte-doubling
problem); 9.93e37 and -240 dB are "no value" sentinels; *RST does not clear
the error queue, so *CLS.
"""
import argparse
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from upl_capture import connect, DryRunUPL, read_fft, preserve_state, parse_values, go_local  # noqa: E402
from report import Run, add_output_args, is_na, SERIES  # noqa: E402

SENTINEL = 9e36

SPEC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dut_specs")
SPEC_KEYS = ("fullscale", "dc", "fr20k", "zout", "thdn", "snr", "dr", "imd", "xtalk", "linearity")


def load_spec(name):
    """--dut-spec: a JSON file of a DUT's published figures, printed under the
    matching result so the test itself stays DUT-agnostic. `name` is a path, or
    a bare name looked up as measurements/dut_specs/<name>.json. Every key is
    optional; see dut_specs/README.md for the format."""
    import json
    path = name if (os.sep in name or "/" in name or name.endswith(".json")) \
        else os.path.join(SPEC_DIR, name + ".json")
    with open(path, encoding="utf-8") as fp:
        spec = json.load(fp)
    unknown = set(spec) - set(SPEC_KEYS) - {"name", "notes"}
    if unknown:
        print(f"WARNING: {path}: unknown keys ignored: {sorted(unknown)}", file=sys.stderr)
    return spec


FS_MODES = {44100: "F44", 48000: "F48", 88200: "F88", 96000: "F96"}
BRM_MAX = 55000          # base rate mode clock limit; above it B29 needs high rate mode


# ---------------------------------------------------------------- helpers

def db(x, ref=1.0):
    if x is None or ref is None or x <= 0 or ref <= 0:
        return None
    return 20.0 * math.log10(x / ref)


def lin(dbfs):
    return 10.0 ** (dbfs / 20.0)


def fmt(x, spec="%.2f", none="  n/a"):
    return none if x is None else spec % x


def parse(reply):
    """'-106.44 DB' -> (-106.44, 'DB'). Sentinels -> (None, unit)."""
    s = reply.strip()
    if not s:
        return None, ""
    parts = s.split()
    try:
        v = float(parts[0].rstrip(","))
    except ValueError:
        return None, s
    unit = parts[1].upper() if len(parts) > 1 else ""
    if abs(v) > SENTINEL or v <= -239.0:
        return None, unit
    return v, unit


def ratio_db(v, unit):
    """THD / THD+N reply in dB whatever unit the UPL chose to display it in."""
    if v is None:
        return None
    if unit == "%":
        return db(v / 100.0)
    return v


def sinc_db(f, fs):
    x = math.pi * f / fs
    return 20.0 * math.log10(abs(math.sin(x) / x)) if x else 0.0


def geomspace(a, b, n):
    if n == 1:
        return [a]
    return [a * (b / a) ** (i / (n - 1)) for i in range(n)]


class Log:
    def __init__(self, path):
        self.fp = open(path, "a", encoding="utf-8") if path else None

    def __call__(self, *msg):
        line = " ".join(str(m) for m in msg)
        print(line)
        if self.fp:
            self.fp.write(line + "\n")
            self.fp.flush()


# ---------------------------------------------------------------- the report
# Each test's rows go to <name>.csv unchanged; report_test() adds the readable
# tables and graphs to report.html. L is always blue, R always orange.

L_COL, R_COL = SERIES[0], SERIES[1]
TITLES = {
    "check": "Lock, full-scale level, balance, DC", "stability": "Stability",
    "fr": "Frequency response", "thdn": "THD+N and THD", "fft": "Spectrum of a tone",
    "images": "Images above fs/2 (wideband spectrum)", "imd": "Intermodulation distortion",
    "xtalk": "Crosstalk", "zout": "Output impedance", "polarity": "Polarity",
    "jitter": "Jitter transfer", "interface": "Interface robustness", "jtest": "J-test",
    "multitone": "Multitone", "linearity": "Linearity", "imdlevel": "IMD vs level",
    "filter": "Reconstruction filter (white noise)", "volsweep": "DUT volume sweep",
    "setlevel": "Output level set by hand", "impulse": "Impulse and step response",
}


def _f(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return float("nan") if is_na(v) else v


def _dbv(v):
    v = _f(v)
    return 20 * math.log10(v) if v > 0 else float("nan")


def _groups(recs, *keys):
    """Records grouped by the values of `keys`, in first-seen order."""
    out = {}
    for r in recs:
        out.setdefault(tuple(r[k] for k in keys), []).append(r)
    return out


def _lr(recs, x, l, r, lab="", style=None):
    """An L (blue) and an R (orange) series from the same records."""
    style = style or {}
    xs = [_f(q[x]) for q in recs]
    return [(f"{lab}L", xs, [_f(q[l]) for q in recs], {"color": L_COL, **style}),
            (f"{lab}R", xs, [_f(q[r]) for q in recs], {"color": R_COL, **style})]


def report_test(rep, name, header, rows):
    """Readable tables and graphs for one test's rows (the CSV has them all)."""
    rep.heading(TITLES.get(name, name))
    if not rows:
        rep.note("No results.", warn=True)
        return
    recs = [dict(zip(header, r)) for r in rows]
    dash = {"linestyle": "--"}
    if name == "fr":
        for (fs, an), g in _groups(recs, "fs", "analyzer").items():
            first = [q for q in g if str(q["pass"]) == "1"]
            series = []
            for mode, lab, style in (("RMSS", "selective ", {}),
                                     ("RMS", "broadband ", {"linestyle": "--", "linewidth": 1.0})):
                m = [q for q in first if q["mode"] == mode]
                if m:
                    series += _lr(m, "freq_Hz", "L_dB_re997", "R_dB_re997", lab, style)
            rep.plot(f"fr_{fs}_{an}", series, title=f"Frequency response, {fs} Hz, {an}",
                     xlabel="Frequency (Hz)", ylabel="dB re 997 Hz", logx=True)
            rep.plot(f"fr_balance_{fs}_{an}",
                     [(f"pass {p}, {'selective' if m == 'RMSS' else 'broadband'}",
                       [_f(q["freq_Hz"]) for q in gg], [_f(q["LminusR_dB"]) for q in gg])
                      for (p, m), gg in _groups(g, "pass", "mode").items()],
                     title=f"L − R, {fs} Hz, {an} (repeat passes should lie on top of each other)",
                     xlabel="Frequency (Hz)", ylabel="L − R (dB)", logx=True, height=3.2)
    elif name == "thdn":
        for (fs, an), g in _groups(recs, "fs", "analyzer").items():
            for sweep, xl in (("level", "Level (dBFS)"), ("freq", "Frequency (Hz)")):
                s = [q for q in g if q["sweep"] == sweep]
                series = []
                for func, lab, style in (("THDN", "THD+N ", {}), ("THD", "THD ", dash)):
                    ss = [q for q in s if q["func"] == func]
                    if ss:
                        series += _lr(ss, "x", "L", "R", lab, style)
                if series:
                    rep.plot(f"thdn_{sweep}_{fs}_{an}", series,
                             title=f"THD+N and THD vs {'level' if sweep == 'level' else 'frequency'}, {fs} Hz, {an}",
                             xlabel=xl, ylabel="dB", logx=(sweep == "freq"))
            other = [q for q in g if q["sweep"] not in ("level", "freq")]
            if other:
                rep.table(["fs", "analyzer", "measurement", "x", "L", "R"],
                          [(q["fs"], q["analyzer"], f"{q['sweep']} {q['func']}", q["x"], q["L"], q["R"])
                           for q in other], title=f"Dynamic range and idle noise, {fs} Hz, {an}")
    elif name in ("fft", "images", "filter", "multitone", "jtest"):
        keys = {"jtest": ("fs", "bits"), "filter": ("fs",), "multitone": ("fs",)}.get(name, ("fs", "analyzer"))
        for k, g in _groups(recs, *keys).items():
            tag = ", ".join(f"{x} bit" if key == "bits" else f"{x} Hz" if key == "fs" else str(x)
                            for key, x in zip(keys, k))
            rep.plot(f"{name}_{'_'.join(str(x) for x in k)}",
                     [(tag, [_f(q["freq_Hz"]) for q in g], [_dbv(q["level_V"]) for q in g])],
                     title=f"{TITLES[name]}, {tag}", xlabel="Frequency (Hz)", ylabel="Level (dBV)",
                     logx=name != "jtest", markers=False)
    elif name == "xtalk":
        for (fs,), g in _groups(recs, "fs").items():
            xs = [_f(q["freq_Hz"]) for q in g]
            rep.plot(f"xtalk_{fs}", [("L → R", xs, [_f(q["LtoR_dB"]) for q in g], {"color": L_COL}),
                                     ("R → L", xs, [_f(q["RtoL_dB"]) for q in g], {"color": R_COL})],
                     title=f"Crosstalk, {fs} Hz", xlabel="Frequency (Hz)", ylabel="dB", logx=True)
        rep.table(header, rows)
    elif name == "linearity":
        for (fs,), g in _groups(recs, "fs").items():
            rep.plot(f"linearity_{fs}", _lr(g, "set_dBFS", "L_err_dB", "R_err_dB"),
                     title=f"Linearity error, {fs} Hz", xlabel="Set level (dBFS)",
                     ylabel="Error (dB)", hlines=[(0, None)])
        rep.table(header, rows)
    elif name == "imdlevel":
        for (fs, test), g in _groups(recs, "fs", "test").items():
            rep.plot(f"imdlevel_{fs}_{test}", _lr(g, "level_dBFS", "L_dB", "R_dB"),
                     title=f"{test} IMD vs level, {fs} Hz", xlabel="Level (dBFS)", ylabel="IMD (dB)")
        rep.table(header, rows)
    elif name == "jitter":
        for (fs, cab), g in _groups(recs, "fs", "cable_sim").items():
            xs = [_f(q["fj_Hz"]) for q in g]
            rep.plot(f"jitter_{fs}_{cab}",
                     [("measured sideband", xs, [_f(q["sideband_dBc"]) for q in g]),
                      ("no rejection (predicted)", xs, [_f(q["predicted_dBc"]) for q in g], dash),
                      ("noise floor", xs, [_f(q["floor_dBc"]) for q in g], {"linestyle": ":"})],
                     title=f"Jitter sidebands, {fs} Hz{', cable simulator' if str(cab) == 'True' else ''}",
                     xlabel="Jitter frequency (Hz)", ylabel="dBc", logx=True)
        rep.table(header, rows)
    elif name == "volsweep":
        for (fs,), g in _groups(recs, "fs").items():
            rep.plot(f"volsweep_{fs}", _lr(g, "volume_dB", "THDN_L_dB", "THDN_R_dB", "THD+N ")
                     + _lr(g, "volume_dB", "THD_L_dB", "THD_R_dB", "THD ", dash),
                     title=f"THD+N and THD vs DUT volume, {fs} Hz", xlabel="Volume (dB)", ylabel="dB")
        rep.table(header, rows)
    elif name == "impulse":
        report_impulse(rep, recs)
    elif name == "stability":
        lv = [q for q in recs if str(q["item"]).startswith("level_")]
        if lv:
            n = list(range(1, len(lv) + 1))
            rep.plot("stability_levels",
                     [("L", n, [_dbv(q["L"]) for q in lv], {"color": L_COL}),
                      ("R", n, [_dbv(q["R"]) for q in lv], {"color": R_COL})],
                     title="Repeated 997 Hz level readings (should be flat)",
                     xlabel="Reading", ylabel="Level (dBV)", height=3.2)
        rep.table(header, [r for r, q in zip(rows, recs) if not str(q["item"]).startswith("level_")])
    elif len(rows) > 60:
        rep.note(f"{len(rows)} rows: see {name}.csv.")
    else:
        rep.table(header, rows)


# ---------------------------------------------------------------- the rig

class Rig:
    """Thin layer over upl_capture's UPL: error-checked config writes, function
    switching, trigger-and-read, and the analyzer setup. Signals come from
    self.src (UPLSource or PCSource, below)."""

    def __init__(self, u, log, args, source="upl"):
        self.u, self.log, self.args = u, log, args
        self.src = (PCSource if source == "pc" else UPLSource)(self)
        self.func_cur = None
        self.fixed_sel = False
        self.state = None           # (fs, analyzer) currently configured
        self.rejected = []
        # frequency sweeps on the UPL's own sweep engine (UPL generator only)
        self.native = source == "upl" and not getattr(args, "stepped", False)

    # --- low level
    def q(self, cmd):
        try:
            return self.u.query(cmd)
        except Exception as e:      # unknown query names time out on this firmware
            self.log(f"  ! no reply to {cmd!r} ({type(e).__name__}); draining")
            self.u.drain(0.5)
            return ""

    def setc(self, cmd, slow=False, quiet=False):
        """Write, optionally sync, then SYST:ERR?. Returns True if accepted."""
        self.u.write(cmd)
        if slow:
            self.q("*OPC?")
        err = self.q("SYST:ERR?")
        ok = err.startswith("0") or err == ""
        if not ok:
            self.rejected.append((cmd, err))
            if not quiet:
                self.log(f"  ! rejected: {cmd:<40s} [{err}]")
            for _ in range(10):     # drain anything else queued
                if self.q("SYST:ERR?").startswith("0"):
                    break
        return ok

    def w(self, cmd):
        self.u.write(cmd)

    def trig(self):
        self.u.write("INIT:CONT OFF;*WAI")
        self.q("*OPC?")

    def unlatch(self):
        """Undo the THD+N floor latch: THD+N of a clipping 0 dBFS tone makes the A22
        analyzer step its notch gain down (floor ~-110 -> ~-103 dB) and *RST, INST2,
        CAL:ZERO, range or rate changes don't restore it. A native 31-point RMS sweep
        does, both channels, every time (4/4 live 2026-09-25; a 3-point sweep only
        cleared CH1). Then re-checks the floor at 997 Hz / -1 dBFS."""
        if not self.native:
            self.log("   (THD+N floor may now be latched ~7 dB high until the UPL is power-cycled)")
            return
        self.func("RMS")
        self.sweep(geomspace(10.0, 20000.0, 31), -10.0)
        self.func("THDN")
        self.tone(997, -1.0)
        time.sleep(self.args.settle)
        self.trig()
        (v1, u1), (v2, u2) = self.read12()
        l, r = ratio_db(v1, u1), ratio_db(v2, u2)
        bad = any(x is not None and x > -106 for x in (l, r))
        self.log(f"   THD+N floor reset (31-pt RMS sweep): -1 dBFS reads L {fmt(l, '%.1f')} R "
                 f"{fmt(r, '%.1f')} dB" + ("   <- STILL LATCHED? power-cycle the UPL" if bad else ""))

    def sweep(self, freqs, dbfs):
        """Measure the current function at each of `freqs` (log-spaced, as from
        geomspace) at `dbfs`. Returns [(f_played, (v1, u1), (v2, u2)), ...].

        Native (UPL generator): one sweep on the UPL's own engine -- the nsweep
        sequence, SWE1 + DISP:TRAC:FEED, one command per line with *OPC? (the PL2303
        doubles bytes otherwise). Checked live 2026-09-24 against the stepped loop on
        the M51: FR within 0.02 dB, 31 points in 3 s instead of ~30 s.
        Trace units are not the SENS:DATA? ones: RMS in V, THD/THD+N in % (even with
        SENS:UNIT DB), so ratios come back tagged "%" and ratio_db() converts them.
        Stepped otherwise (--stepped, or the PC source)."""
        a = self.args
        if not self.native or len(freqs) < 2:
            out = []
            for f in freqs:
                fa = self.tone(f, dbfs)
                time.sleep(a.settle)
                self.trig()
                out.append((fa,) + tuple(self.read12()))
            return out
        self.tone(freqs[0], dbfs)
        for c in ("FORM ASC", "DISP:TRAC:OPER CURV", "DISP:TRAC:FEED 'SENS:DATA'",
                  "DISP:TRAC2:FEED 'SENS:DATA2'", "DISP:TRAC:X:SPAC LOG"):
            self.setc(c)
        self.u.set_timeout(max(a.timeout, 120))
        try:
            for c in ("SOUR:SWE:MODE AUTO", "SOUR:FREQ:MODE SWE1",
                      f"SOUR:FREQ:STAR {freqs[0]:.4f} HZ", f"SOUR:FREQ:STOP {freqs[-1]:.4f} HZ",
                      "SOUR:SWE:FREQ:SPAC LOG", f"SOUR:SWE:FREQ:POIN {len(freqs)}"):
                self.setc(c, slow=True)
            self.setc("DISP:CONF AP")
            self.u.set_timeout(max(a.timeout, 60 + 5 * len(freqs)))
            self.trig()
            self.u.set_timeout(a.timeout)
            y1 = parse_values(self.q("TRAC? TRAC1"), "TRAC? TRAC1")
            y2 = parse_values(self.q("TRAC? TRAC2"), "TRAC? TRAC2")
            x = parse_values(self.q("TRAC? LIST1"), "TRAC? LIST1")
        finally:
            self.u.set_timeout(a.timeout)
            self.setc("SOUR:FREQ:MODE FIX", slow=True)     # else plain SOUR:FREQ misbehaves
        unit = "%" if self.func_cur in ("THD", "THDN") else "V"

        def val(v):
            return None if (v <= 0 or v > SENTINEL) else v
        out = []
        for f in freqs:
            i = min(range(len(x)), key=lambda k: abs(math.log(x[k] / f)))
            out.append((x[i], (val(y1[i]), unit), (val(y2[i]), unit)))
        return out

    def func(self, name):
        if name != self.func_cur:
            self.setc(f"SENS1:FUNC '{name}'", slow=True)
            self.func_cur = name
            self.fixed_sel = False                # a new function drops the selective set-up

    def read12(self):
        v1, u1 = parse(self.q("SENS:DATA?"))
        v2, u2 = parse(self.q("SENS:DATA2?"))
        return (v1, u1), (v2, u2)

    def measure(self, name):
        self.func(name)
        self.trig()
        return self.read12()

    def freq(self):
        return parse(self.q("SENS3:DATA?"))[0]

    # --- setup
    def configure(self, fs, analyzer="A22"):
        if self.state == (fs, analyzer):
            return
        a = self.args
        self.log(f"\n-- configure: fs={fs} Hz, analyzer={analyzer}, {a.bits}-bit, source={self.src.name}")
        self.w("*CLS")
        self.src.configure(fs, analyzer)
        # analyzer -- nothing survives an INST2 change, so all of it every time
        self.setc("INP:TYPE BAL")
        self.setc("INP:SEL CH2Is1")          # analog analyzer: BOTH is digital-only (-222)
        self.setc(f"INP:LOW {'GRO' if a.ground else 'FLO'}")
        self.setc("INP:IMP R200K")
        self.setc("SENS:VOLT:RANG:AUTO ON")
        self.setc("SENS2:FUNC 'OFF'")
        self.setc("SENS3:FUNC 'FREQ'")
        # plain RMS first: with THD, selective RMS or POL still selected, SENS:FILT OFF
        # is rejected -200 (filters not applicable) -- harmless, but it cluttered every log
        self.func_cur = None
        self.func("RMS")
        self.setc("SENS:FILT OFF")
        self.fixed_sel = False
        self.state = (fs, analyzer)
        self.log(f"   INST? {self.q('INST?')!r}  INST2? {self.q('INST2?')!r}")
        time.sleep(a.relock)                      # let the DAC lock to the new rate

    def tone(self, f, dbfs, ch="both"):
        """Sine at f Hz, dbfs, on both channels or only "L"/"R". Returns the
        frequency actually played (the PC source snaps it to its loop length)."""
        f = self.src.tone(f, dbfs, ch)
        if self.fixed_sel:                        # selective filter can't track a PC
            self.setc(f"SENS:FREQ {f:.4f} HZ", quiet=True)
        return f

    def selective(self, band):
        """RMSS whose bandpass follows the test tone: GENTrack for the UPL's own
        generator, FIXed + SENS:FREQ per tone for an external (PC) source."""
        self.func("RMSS")
        if self.src.tracks:
            self.setc("SENS:FREQ:MODE GENT")
        else:
            self.setc("SENS:FREQ:MODE FIX")
            self.fixed_sel = True
        self.setc(f"SENS:BAND:MODE {band}")

    def aperture_follow(self):
        """Measurement time matched to the tone: GENT if the UPL generates, else AUTO."""
        if not (self.src.tracks and self.setc("SENS:VOLT:APER:MODE GENT")):
            self.setc("SENS:VOLT:APER:MODE AUTO")

    def locked(self, f, v, vmin=1e-3):
        fm = self.freq()
        ok = fm is not None and abs(fm - f) / f < 0.01 and v is not None and v > vmin
        return ok, fm

    def run_fft(self, size="S8K", avg=1):
        self.func("FFT")
        self.setc(f"CALC:TRAN:FREQ:FFT {size}")
        self.setc("CALC:TRAN:FREQ:WIND BLACkman_harris")
        self.setc("CALC:TRAN:FREQ:ZOOM 1")
        self.setc(f"CALC:TRAN:FREQ:AVER {avg}", quiet=True)
        self.setc("FORM ASC")
        # Selecting FFT does not restore the trace feed: after SENS1:FUNC 'POL'
        # it stays 'OFF' and TRAC:POIN? reads 0 (live, 2026-09-24).
        self.setc("DISP:TRAC:FEED 'SENS:DATA'")
        self.trig()
        f, y = read_fft(self.u)
        # TRAC? is in the display unit: volts if all positive, else dBV-ish
        if y and min(y) < 0:
            y = [10 ** (v / 20.0) for v in y]
        return f, y

    def upload(self, path, data):
        """PC -> UPL file: MMEM:DATA '<path>',#<n><len><bytes> (Vol.2 3.10.13), then
        verify with the UPL's own MD5 (MMEM:CHECK?, verified 2026-09-24)."""
        import hashlib
        ln = str(len(data))
        head = f"MMEM:DATA '{path}',#{len(ln)}{ln}".encode("latin1")
        if hasattr(self.u, "ser"):
            self.u.ser.write(head + data + b"\n")
            self.u.ser.flush()
        elif hasattr(self.u, "inst"):
            self.u.inst.write_raw(head + data + b"\n")
        else:                                       # dry run
            self.u.write(f"MMEM:DATA '{path}',#{len(ln)}{ln}<{len(data)} bytes>")
        self.q("*OPC?")
        theirs = self.q(f"MMEM:CHECK? '{path}'").strip().strip("'\"").lower()
        ours = hashlib.md5(data).hexdigest()
        ok = theirs == ours
        self.log(f"   uploaded {path} ({len(data)} bytes): MD5 {'OK' if ok else 'MISMATCH ' + theirs}")
        return ok

    def spec(self, key, fs=None):
        """Print the DUT's published figure for this measurement, if --dut-spec is set.
        A dict value is {"base": dB, "high": dB} -- base rate (<= 48 kHz) vs 88.2/96."""
        d = self.args.spec
        if not d or key not in d:
            return
        v = d[key]
        if isinstance(v, dict):
            v = f"{v['high' if fs and fs > BRM_MAX else 'base']:+.2f} dB at 20 kHz"
        self.log(f"   spec: {v}")

    def cleanup(self):
        self.src.cleanup()
        self.func("RMS")                             # SENS:FILT OFF is -200 under RMSS/THD/POL
        for c in ("INP:IMP R200K", "SENS:FILT OFF"):
            self.setc(c, quiet=True)


# ---------------------------------------------------------------- signal sources
#
# Every test asks the rig's source for its signals; the analysis never knows which
# one is playing. A source provides configure(fs, analyzer), tone(f, dbfs, ch),
# silence(), twin("SMPTE"|"CCIF", dbfs), jtest(bits), noise(dbfs),
# multitone(tones, dbfs), sine() and cleanup(), plus `tracks` (can the analyzer
# GENTrack it?) and `unsupported` ({test: why it can't run it}); check_options() adds
# to the UPL source's from *OPT?.

def ccif_mean(fs):
    """CCIF mean frequency: 19.5 kHz (19 + 20 kHz), or 19 kHz (18.5 + 19.5) where the
    UPL's digital generator can't reach 20 kHz -- at 44.1k it rejected MEAN 19300
    and above with DIFF 1000 (live 2026-09-24)."""
    return 19500.0 if fs >= 48000 else 19000.0


def ccif_name(fs):
    m = ccif_mean(fs) / 1000
    return f"{m - 0.5:g}+{m + 0.5:g}"


class UPLSource:
    """The UPL's digital generator (B29, or B2 at 44.1/48 kHz) into the DAC's S/PDIF/AES input."""
    name = "upl"
    tracks = True
    CH_SEL = {"both": "CH2Is1", "L": "CH1", "R": "CH2"}

    def __init__(self, rig):
        self.rig = rig
        self.ch = "both"
        self.twin_cur = None
        self.unsupported = {}

    def configure(self, fs, analyzer):
        r, a = self.rig, self.rig.args
        r.setc(f"CONF:DAI {'HRM' if fs > BRM_MAX else 'BRM'}", slow=True)
        r.setc("INST D48", slow=True)
        r.setc(f"INST2 {analyzer}", slow=True)
        r.setc("SOUR:DIG:FEED ADAT")
        r.setc(f"OUTP:SAMP:MODE {FS_MODES[fs]}", slow=True)
        r.setc(f"OUTP:AUD {a.bits}")
        r.setc("OUTP:DIG:CSIM OFF")
        r.setc("SOUR2:FUNC OFF", slow=True)
        r.setc("OUTP:SEL CH2Is1")              # both channels, in phase
        r.setc("SOUR:FUNC SIN", slow=True)
        self.ch, self.twin_cur = "both", None
        self.fs = fs

    def tone(self, f, dbfs, ch="both"):
        r = self.rig
        if ch != self.ch:
            r.setc(f"OUTP:SEL {self.CH_SEL[ch]}")
            self.ch = ch
        r.setc(f"SOUR:FREQ {f:.4f} HZ", quiet=True)
        r.setc(f"SOUR:VOLT {lin(dbfs):.6g} FS", quiet=True)
        return f

    def silence(self):
        self.rig.setc("SOUR:VOLT 0 FS", quiet=True)

    def twin(self, kind, dbfs):
        r = self.rig
        if kind != self.twin_cur:
            # SMPTE: SOUR:FREQ = upper (7 kHz), SOUR:FREQ2 = lower (60 Hz), ratio LF:UF 4
            # (Vol.2 3.10.1.5.5). CCIF 19 + 20 kHz as DFD mean/diff.
            setup = (("SOUR:FUNC MDIS", "SOUR:FREQ 7000 HZ", "SOUR:FREQ2 60 HZ", "SOUR:VOLT:RAT 4")
                     if kind == "SMPTE" else
                     # DIFF before MEAN; at 44.1k the upper tone must stay below ~19.8 kHz
                     # (MEAN 19500 -> -222 live), so 18.5 + 19.5 kHz there
                     ("SOUR:FUNC DFD", "SOUR:FREQ:DIFF 1000 HZ",
                      f"SOUR:FREQ:MEAN {ccif_mean(self.fs):.0f} HZ"))
            for c in setup:
                r.setc(c, slow=c.startswith("SOUR:FUNC"))
            self.twin_cur = kind
        r.setc(f"SOUR:VOLT:TOT {lin(dbfs):.6g} FS", quiet=True)

    def jtest(self, bits):
        r = self.rig
        samples, peak = jtest_samples(bits)
        body = "# J-test, 192 samples, fs/4 tone + 1 LSB square at fs/192, %d-bit\nTIMETAB_FILE\n" % bits
        body += "\n".join("%.12f" % s for s in samples) + "\n"
        path = f"C:\\UPL\\USER\\JTEST{bits}.TTF"
        r.upload(path, body.encode("ascii"))
        r.setc(f"OUTP:AUD {bits}")
        r.setc("SOUR:FUNC ARB", slow=True)
        r.setc(f"MMEM:LOAD:LIST ARB,'{path}'", slow=True)
        r.setc(f"SOUR:VOLT:TOT {peak:.12f} FS")
        self.twin_cur = None

    def impulse(self, period, dbfs):
        """One sample at dbfs, then period-1 zeros, looped: an ARB time-table file
        (the ARB normalizes the file's largest value to SOUR:VOLT:TOT, so 1.0 = the
        set peak). Like the J-test, sample-exact playback is from Vol.1 2.5.4.10
        ("samples are output at the selected sampling rate"), not yet seen live."""
        r = self.rig
        body = "# impulse: 1 sample, then %d zeros\nTIMETAB_FILE\n1.0\n" % (period - 1)
        body += "0\n" * (period - 1)
        path = f"C:\\UPL\\USER\\IMP{period}.TTF"
        r.upload(path, body.encode("ascii"))
        r.setc(f"OUTP:AUD {r.args.bits}")
        r.setc("SOUR:FUNC ARB", slow=True)
        r.setc(f"MMEM:LOAD:LIST ARB,'{path}'", slow=True)
        r.setc(f"SOUR:VOLT:TOT {lin(dbfs):.6g} FS")
        self.twin_cur = None

    def noise(self, dbfs):
        r = self.rig
        r.setc("SOUR:FUNC RAND", slow=True)
        r.setc("SOUR:RAND:DOM TIME")
        r.setc(f"SOUR:VOLT:TOT {lin(dbfs):.6g} FS")
        self.twin_cur = None

    def multitone(self, tones, dbfs):
        r = self.rig
        r.setc("SOUR:FUNC MULT", slow=True)
        r.setc("SOUR:MULT:MODE EQU")
        r.setc(f"SOUR:MULT:COUN {len(tones)}")
        r.setc("SOUR:RAND:SPAC:MODE ATR")      # tones snapped to FFT bins
        r.setc("SOUR:VOLT:CRES:MODE MIN", slow=True)
        for i, f in enumerate(tones, 1):
            r.setc(f"SOUR:FREQ{i} {f:.2f} HZ", quiet=True)
        amp = 0.05
        for _ in range(3):                     # scale per-tone level to the total peak
            r.setc(f"SOUR:VOLT1 {amp:.6g} FS", quiet=True)
            tot = parse(r.q("SOUR:VOLT:TOT?"))[0]
            if not tot or tot <= 0:
                break
            amp = min(amp * lin(dbfs) / tot, 1.0 / len(tones))
        self.twin_cur = None
        return tones

    def sine(self):
        r = self.rig
        r.setc(f"OUTP:AUD {r.args.bits}")
        r.setc("SOUR:FUNC SIN", slow=True)
        self.twin_cur = None

    def cleanup(self):
        self.rig.log("\n-- cleanup: generator muted, jitter/cable sim off, base rate mode")
        for c in ("SOUR:VOLT 0 FS", "SOUR2:FUNC OFF", "OUTP:DIG:CSIM OFF",
                  "OUTP:SEL CH2Is1", "CONF:DAI BRM"):
            self.rig.setc(c, quiet=True)


class PCSource:
    """This PC plays the test signal into a USB (or any) DAC through WASAPI
    exclusive mode, so Windows neither resamples nor mixes. Every signal is a
    loop of exactly quantized integer samples with PortAudio's dither off, so it
    reaches the DAC bit-exact, as the UPL's generator does -- apart from anything
    the DAC itself does to USB audio. Tone frequencies are snapped so a whole
    number of cycles fits the loop: 1 Hz steps (0.1 Hz below 100 Hz).

    The UPL's own generator stays in its *RST (analog) state, unused and
    unconnected. The analyzer can't GENTrack a PC, so selective RMS uses a FIXed
    frequency set per tone, and the aperture uses AUTO."""
    name = "pc"
    tracks = False
    unsupported = {t: "needs the UPL's digital generator (--source upl)"
                   for t in ("jitter", "interface", "polarity")}

    def __init__(self, rig):
        import threading
        self.rig = rig
        self.a = rig.args
        self.fs = None
        self.stream = None
        self.buf = None
        self.pos = 0
        self.ref_cur = None                          # twin tone the UPL generator mirrors
        self.lock = threading.Lock()

    # --- audio plumbing
    def configure(self, fs, analyzer):
        r = self.rig
        r.setc(f"INST2 {analyzer}", slow=True)
        if fs == self.fs:
            return
        self.close()
        self.fs = fs
        self.buf = np.zeros((fs, 2), dtype=np.int32)
        self.pos = 0
        if self.a.dry_run:
            r.log(f"   (dry run: would open device {self.a.device} at {fs} Hz, "
                  f"{'shared' if self.a.shared else 'WASAPI exclusive'})")
            return
        import sounddevice as sd
        api = sd.query_hostapis(sd.query_devices(self.a.device)["hostapi"])["name"]
        if not self.a.shared and "WASAPI" not in api:
            raise SystemExit(f"--device {self.a.device} is a {api} device; exclusive mode needs a "
                             f"'Windows WASAPI' one (python measurements/upacd_test.py devices)")
        extra = None if self.a.shared else sd.WasapiSettings(exclusive=True)
        self.stream = sd.OutputStream(samplerate=fs, device=self.a.device, channels=2,
                                      dtype="int32", callback=self._cb, dither_off=True,
                                      extra_settings=extra)
        self.stream.start()
        r.log(f"   PC output: device {self.a.device}, {fs} Hz, {self.a.bits}-bit words, "
              f"{'shared (resampled!)' if self.a.shared else 'WASAPI exclusive'}, "
              f"latency {self.stream.latency * 1000:.0f} ms")

    def _cb(self, out, frames, time_info, status):
        with self.lock:
            buf, n = self.buf, len(self.buf)
            i = 0
            while i < frames:
                k = min(frames - i, n - self.pos)
                out[i:i + k] = buf[self.pos:self.pos + k]
                i += k
                self.pos = (self.pos + k) % n

    def play(self, x, desc):
        """x: floats, 1.0 = full-scale peak, shape (n,) or (n, 2); looped."""
        if x.ndim == 1:
            x = np.column_stack([x, x])
        top = 2 ** (self.a.bits - 1) - 1
        self.set_codes(np.clip(np.round(x * top), -top - 1, top).astype(np.int64), desc)

    def set_codes(self, codes, desc, bits=None):
        """Integer codes at `bits` (default --bits), MSB-aligned into the int32 stream."""
        bits = bits or self.a.bits
        shifted = (np.asarray(codes, dtype=np.int64) << (32 - bits)).astype(np.int32)
        with self.lock:
            self.buf, self.pos = shifted, 0
        if self.a.dry_run:
            self.rig.log(f"   [pc] {desc}")

    def close(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def _t(self, seconds):
        return np.arange(int(round(seconds * self.fs))) / self.fs

    # --- signals
    def tone(self, f, dbfs, ch="both"):
        per = 10.0 if f < 100 else 1.0              # loop length, s
        f = round(f * per) / per
        x = lin(dbfs) * np.sin(2 * math.pi * f * self._t(per))
        z = np.zeros_like(x)
        self.play(np.column_stack([x if ch != "R" else z, x if ch != "L" else z]),
                  f"tone {f:g} Hz {dbfs:+.1f} dBFS {ch}")
        return f

    def silence(self):
        self.set_codes(np.zeros((self.fs, 2), dtype=np.int64), "digital silence")

    def twin(self, kind, dbfs):
        t, pk = self._t(1.0), lin(dbfs)
        if kind == "SMPTE":                          # 60 Hz + 7 kHz, 4:1
            x = pk * (0.8 * np.sin(2 * math.pi * 60 * t) + 0.2 * np.sin(2 * math.pi * 7000 * t))
        else:                                        # CCIF 19 + 20 kHz, 1:1
            x = pk * 0.5 * (np.sin(2 * math.pi * 19000 * t) + np.sin(2 * math.pi * 20000 * t))
        self.play(x, f"{kind} twin tone {dbfs:+.1f} dBFS")
        if kind != self.ref_cur:
            # The DFD/MDIS analyzers take their frequencies from the UPL
            # generator's settings (found with m51_imd.py), so set the matching
            # function there too -- muted: its output isn't connected anyway.
            r = self.rig
            setup = (("SOUR:FUNC MDIS", "SOUR:FREQ 7000 HZ", "SOUR:FREQ2 60 HZ", "SOUR:VOLT:RAT 4")
                     if kind == "SMPTE" else
                     ("SOUR:FUNC DFD", "SOUR:FREQ:MEAN 19500 HZ", "SOUR:FREQ:DIFF 1000 HZ"))
            for c in setup:
                r.setc(c, slow=c.startswith("SOUR:FUNC"))
            r.setc("SOUR:VOLT:TOT 1e-20 V", quiet=True)
            self.ref_cur = kind

    def jtest(self, bits):
        """The samples of jtest_samples(), as exact codes: tone at +/-0.5 FS (45 deg,
        so -3 dBFS peak) plus 1 LSB for the first 96 of every 192 samples."""
        half = 2 ** (bits - 2)
        tone = np.array([half, half, -half, -half] * 48, dtype=np.int64)
        tone[:96] += 1
        self.set_codes(np.column_stack([tone, tone]), f"J-test {bits}-bit", bits=bits)

    def impulse(self, period, dbfs):
        top = 2 ** (self.a.bits - 1) - 1
        codes = np.zeros((period, 2), dtype=np.int64)
        codes[0] = round(lin(dbfs) * top)
        self.set_codes(codes, f"impulse {dbfs:+.1f} dBFS every {period} samples")

    def noise(self, dbfs):
        x = np.random.default_rng(1).standard_normal((2 * self.fs, 2))
        self.play(lin(dbfs) * x / np.abs(x).max(), f"white noise, peak {dbfs:+.1f} dBFS")

    def multitone(self, tones, dbfs):
        """Integer-Hz tones in a 1 s loop, Schroeder phases for a low crest factor.
        Unlike the UPL's ATRack spacing they aren't on FFT bins, so the
        Blackman-Harris window's skirts set the floor between tones."""
        tones = sorted({max(1, round(f)) for f in tones})
        t, n = self._t(1.0), len(tones)
        x = sum(np.sin(2 * math.pi * f * t - math.pi * k * (k - 1) / n) for k, f in enumerate(tones))
        self.play(lin(dbfs) * x / np.abs(x).max(), f"{n}-tone multisine, peak {dbfs:+.1f} dBFS")
        return tones

    def sine(self):
        if self.ref_cur:                             # undo twin()'s analyzer reference
            self.rig.setc("SOUR:FUNC SIN", slow=True)
            self.ref_cur = None

    def cleanup(self):
        self.rig.log("\n-- cleanup: PC output stopped")
        self.close()


# ---------------------------------------------------------------- DUT control (optional)
#
# Most DACs need none: set them up by hand and the suite treats them as a black
# box. --dut adds only what the analysis can't see: the DUT's own state logged
# in the report, --volume set for the run (and restored), and `volsweep`.

class M51Dut:
    """NAD M51 over RS-232 (nad_m51.py). In fixed-output mode leave out --volume
    and it's just logged; the M51 is then a plain DAC to the suite."""
    name = "m51"

    def __init__(self, port):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from nad_m51 import M51
        self.m = M51(port)
        self.orig_volume = None

    def describe(self):
        return f"NAD M51: source={self.m.get_source()!r}, volume={self.m.get_volume_db():g} dB"

    def set_volume(self, db):
        if self.orig_volume is None:
            self.orig_volume = self.m.get_volume_db()
        self.m.set_volume_db(db)

    def restore(self):
        if self.orig_volume is not None:
            self.m.set_volume_db(self.orig_volume)
            return f"volume restored to {self.orig_volume:g} dB"
        return None

    def close(self):
        self.m.close()


class DryDut:
    """--dry-run stand-in: remembers the volume, talks to nothing."""
    def __init__(self, name):
        self.name, self.vol, self.orig_volume = name, 0.0, None

    def describe(self):
        return f"{self.name} (dry run): volume={self.vol:g} dB"

    def set_volume(self, db):
        if self.orig_volume is None:
            self.orig_volume = self.vol
        self.vol = db

    def restore(self):
        if self.orig_volume is not None:
            self.vol = self.orig_volume
            return f"volume restored to {self.orig_volume:g} dB"
        return None

    def close(self):
        pass


DUTS = {"m51": M51Dut}


# ---------------------------------------------------------------- spectrum analysis

def peak_near(freqs, lin_y, f, tol):
    best = None
    for fx, y in zip(freqs, lin_y):
        if abs(fx - f) <= tol and (best is None or y > best):
            best = y
    return best


def analyze_spectrum(freqs, y, f0, fs, log, tag):
    if len(freqs) < 2:
        log("   (spectrum empty)")
        return {}
    res = freqs[1] - freqs[0]
    tol = max(3 * res, 1e-3 * f0)
    fund = peak_near(freqs, y, f0, max(tol, 0.01 * f0))
    fmax = freqs[-1]
    out = {"fund_V": fund}
    log(f"   {tag}: fundamental {fmt(fund, '%.4g')} V at {f0:.0f} Hz, "
        f"span {freqs[0]:.0f}-{fmax:.0f} Hz, res {res:.2f} Hz")
    if not fund:
        return out
    hs = []
    for k in range(2, 10):
        if k * f0 < fmax:
            h = db(peak_near(freqs, y, k * f0, tol), fund)
            out[f"H{k}_dBc"] = h
            hs.append(f"H{k} {fmt(h, '%.1f')}")
    if hs:
        log("     harmonics (dBc): " + ", ".join(hs))
    mains = []
    for m in (50, 60, 100, 120, 150, 180):
        if m < fmax:
            v = db(peak_near(freqs, y, m, max(2 * res, 2.0)), fund)
            out[f"mains{m}_dBc"] = v
            mains.append(f"{m}Hz {fmt(v, '%.1f')}")
    log("     hum (dBc):       " + ", ".join(mains))
    imgs = []
    for k in (1, 2, 3):
        for s in (-1, 1):
            fi = k * fs + s * f0
            if 0 < fi < fmax:
                v = db(peak_near(freqs, y, fi, tol), fund)
                out[f"img_{fi:.0f}_dBc"] = v
                imgs.append(f"{fi/1000:.1f}k {fmt(v, '%.1f')}")
    if imgs:
        log("     images (dBc):    " + ", ".join(imgs))
    floor = sorted(y)[len(y) // 2]
    out["median_floor_dBc"] = db(floor, fund)
    log(f"     median bin (dBc): {fmt(out['median_floor_dBc'], '%.1f')}")
    return out


# ---------------------------------------------------------------- tests

def t_check(rig, a, fs, ctx):
    log = rig.log
    rig.configure(fs)
    rig.tone(997, -1.0)
    time.sleep(a.settle)
    (v1, _), (v2, _) = rig.measure("RMS")
    ok, fm = rig.locked(997, max(v1 or 0, v2 or 0))
    (d1, _), (d2, _) = rig.measure("DC")
    fs1, fs2 = (v / lin(-1.0) if v else None for v in (v1, v2))
    bal = db(v1, v2) if v1 and v2 else None
    log(f"   lock: {'YES' if ok else 'NO -- check cable, input select, sample rate support'}"
        f"   measured freq {fmt(fm, '%.2f')} Hz")
    log(f"   0 dBFS output: L {fmt(fs1, '%.4f')} V  R {fmt(fs2, '%.4f')} V   "
        f"L-R {fmt(bal, '%+.3f')} dB")
    log(f"   DC offset:     L {fmt(d1, '%+.4f')} V  R {fmt(d2, '%+.4f')} V")
    rig.spec("fullscale")
    rig.spec("dc")
    ctx.setdefault("fullscale", {})[fs] = (fs1, fs2)
    return [(fs, ok, fm, fs1, fs2, bal, d1, d2)]


A100_SEL_MIN = 60.0     # Hz, lowest selective-RMS frequency on the 100 kHz analyzer


def t_fr(rig, a, fs, ctx):
    log = rig.log
    stop = a.stop if a.stop else (0.45 * fs if a.wide else min(20000.0, 0.45 * fs))
    analyzer = "A100" if (a.wide or stop > 21000) else "A22"
    rig.configure(fs, analyzer)
    rig.aperture_follow()
    freqs = geomspace(a.start, stop, a.points)
    rows, data = [], {}
    for p in range(a.repeat):
        for mode in ("RMS", "RMSS"):
            if mode == "RMSS":
                rig.selective("PTOC")             # 1/3-octave bandpass that follows the tone
            else:
                rig.func(mode)
            rig.tone(997, a.level)
            time.sleep(a.settle)
            rig.trig()
            (r1, _), (r2, _) = rig.read12()
            # A100 can't install the tracking bandpass this low: 111 "RMS Select
            # bandpass is not installable!" at <= 53 Hz, fine at 69 Hz (live)
            skip = [f for f in freqs if mode == "RMSS" and analyzer == "A100" and f < A100_SEL_MIN]
            meas = {f: m for f, m in zip([f for f in freqs if f not in skip],
                                         rig.sweep([f for f in freqs if f not in skip], a.level))}
            for f in freqs:
                if f in skip:
                    data[(p, mode, f)] = (None, None, None)
                    rows.append((fs, analyzer, p + 1, mode, round(f, 2), None, None, "", "", ""))
                    continue
                fa, (v1, _), (v2, _) = meas[f]
                d1, d2 = db(v1, r1), db(v2, r2)
                lr = db(v1, v2) if v1 and v2 else None
                data[(p, mode, f)] = (d1, d2, lr)
                rows.append((fs, analyzer, p + 1, mode, round(fa, 2), v1, v2,
                             fmt(d1, "%.3f", ""), fmt(d2, "%.3f", ""), fmt(lr, "%.3f", "")))
            log(f"   pass {p+1} {mode:<4s} done  (ref 997 Hz: L {fmt(r1, '%.4f')} V, R {fmt(r2, '%.4f')} V)")

    # ---- diagnosis
    def worst(key_fn):
        best = (0.0, None)
        for f in freqs:
            v = key_fn(f)
            if v is not None and abs(v) > abs(best[0]):
                best = (v, f)
        return best

    log(f"   --- FR diagnosis, fs={fs} ({analyzer}, {a.level:+.0f} dBFS, {a.start:.0f}-{stop:.0f} Hz)")
    lr, flr = worst(lambda f: data[(0, "RMSS", f)][2])
    log(f"   L-R mismatch (selective):   worst {lr:+.2f} dB at {fmt(flr, '%.0f')} Hz")
    for ch, name in ((0, "L"), (1, "R")):
        d, fd = worst(lambda f: (data[(0, "RMS", f)][ch] - data[(0, "RMSS", f)][ch])
                      if None not in (data[(0, "RMS", f)][ch], data[(0, "RMSS", f)][ch]) else None)
        log(f"   {name}: broadband - selective: worst {d:+.2f} dB at {fmt(fd, '%.0f')} Hz"
            + ("   <- non-signal energy (images/hum/noise) inflating RMS" if abs(d) > 0.3 else ""))
    if a.repeat > 1:
        spread = 0.0
        for f in freqs:
            for ch in (0, 1):
                vals = [data[(p, "RMSS", f)][ch] for p in range(a.repeat)]
                vals = [v for v in vals if v is not None]
                if len(vals) > 1:
                    spread = max(spread, max(vals) - min(vals))
        log(f"   repeatability (selective): max spread {spread:.3f} dB over {a.repeat} passes"
            + ("   <- NOT repeatable: loose connection, lock drop-outs, oscillation?" if spread > 0.2 else ""))
    for ch, name in ((0, "L"), (1, "R")):
        top = data[(0, "RMSS", freqs[-1])][ch]
        low = data[(0, "RMSS", freqs[0])][ch]
        s = sinc_db(freqs[-1], fs)
        hint = ""
        if top is not None and abs(top - s) < 1.0 and s < -1.0:
            hint = "   <- matches sinc droop: non-oversampling (NOS) DAC"
        log(f"   {name}: {freqs[0]:.0f} Hz {fmt(low, '%+.2f')} dB, {freqs[-1]:.0f} Hz {fmt(top, '%+.2f')} dB "
            f"(NOS sinc would be {s:+.2f}){hint}")
    rig.spec("fr20k", fs)
    return rows


def t_thdn(rig, a, fs, ctx):
    log = rig.log
    rows = []
    for analyzer in a.analyzers:
        rig.configure(fs, analyzer)
        if analyzer == "A22":
            rig.unlatch()                         # an earlier 0 dBFS THD+N may have latched it
        # vs frequency @ --freq-level -- BEFORE the level sweep: THD+N of a clipping
        # 0 dBFS tone overdrives the analyzer's notch path and it steps its notch gain
        # down, raising its own THD+N floor from ~-110 to ~-103 dB until the UPL is
        # power-cycled or a native RMS sweep runs (Rig.unlatch; *RST, INST2, CAL:ZERO,
        # low levels don't restore it; live 2026-09-24/25 on the M51, whose 0 dBFS clips).
        for fn in ("THDN", "THD"):
            rig.func(fn)
            for fa, (v1, u1), (v2, u2) in rig.sweep(geomspace(20, min(20000, 0.45 * fs), 16),
                                                    a.freq_level):
                rows.append((fs, analyzer, "freq", round(fa, 1), fn, ratio_db(v1, u1), ratio_db(v2, u2)))
        # vs level @ 997 Hz; THD (unaffected by the notch gain) first, THD+N's 0 dBFS last
        for fn in ("THD", "THDN"):
            rig.func(fn)
            for L in a.levels:
                rig.tone(997, L)
                time.sleep(a.settle)
                rig.trig()
                (v1, u1), (v2, u2) = rig.read12()
                rows.append((fs, analyzer, "level", L, fn, ratio_db(v1, u1), ratio_db(v2, u2)))
        if analyzer == "A22" and max(a.levels) >= 0:
            rig.unlatch()                         # the 0 dBFS THD+N point just latched it
        best = [r for r in rows if r[1] == analyzer and r[2] == "level" and r[4] == "THDN"]
        for ch, name in ((5, "L"), (6, "R")):
            vals = [(r[ch], r[3]) for r in best if r[ch] is not None]
            if vals:
                m = min(vals)
                at_m1 = next((r[ch] for r in best if r[3] == -1.0), None)
                at_0 = next((r[ch] for r in best if r[3] == 0), None)
                log(f"   {analyzer} {name}: THD+N @ -1 dBFS {fmt(at_m1, '%.1f')} dB; "
                    f"best {m[0]:.1f} dB at {m[1]:+.0f} dBFS; SINAD (ASR, 0 dBFS) "
                    f"{fmt(None if at_0 is None else -at_0, '%.1f')} dB"
                    + ("  <- at/near the UPL's own floor" if at_0 is not None and at_0 < -100 else ""))
    # dynamic range (AES17): THD+N at -60 dBFS, A-weighted, + 60 dB
    rig.configure(fs, "A22")
    rig.func("THDN")                             # function first: the previous one (THD) takes
    rig.setc("SENS:FILT1:AWE ON")                # no weighting filter -> -200 (live 2026-09-24)
    rig.tone(997, -60.0)
    time.sleep(a.settle)
    rig.trig()
    (v1, u1), (v2, u2) = rig.read12()
    dr = [None if ratio_db(v, u) is None else 60.0 - ratio_db(v, u) for v, u in ((v1, u1), (v2, u2))]
    # idle noise, digital silence, A-weighted
    rig.src.silence()
    time.sleep(max(a.settle, 1.0))
    rig.func("RMS")
    rig.setc("SENS:FILT1:AWE ON")                # again: the function change dropped it -- idle
    (n1, _), (n2, _) = rig.measure("RMS")        # noise came out unweighted, S/N < DR (live)
    rig.setc("SENS:FILT OFF")
    fsv = ctx.get("fullscale", {}).get(fs, (None, None))
    snr = [db(f, n) if f and n else None for f, n in zip(fsv, (n1, n2))]
    log(f"   dynamic range (AES17, A-wtd):  L {fmt(dr[0], '%.1f')} dB  R {fmt(dr[1], '%.1f')} dB")
    log(f"   idle noise (digital zero, A):  L {fmt(n1, '%.3g')} V  R {fmt(n2, '%.3g')} V"
        + (f"   -> S/N L {fmt(snr[0], '%.1f')} R {fmt(snr[1], '%.1f')} dB" if any(snr) else
           "   (run `check` first for S/N)"))
    log("   (if S/N >> dynamic range, the DAC mutes on digital zero -- trust dynamic range)")
    rig.spec("thdn")
    rig.spec("snr")
    rig.spec("dr")
    rows.append((fs, "A22", "dynrange", -60, "THDN_Awt", dr[0], dr[1]))
    rows.append((fs, "A22", "idle", "zero", "RMS_Awt_V", n1, n2))
    return rows


def t_fft(rig, a, fs, ctx, images=False):
    log = rig.log
    f0 = a.freq if not images else (a.image_freq or 19000.0)
    analyzer = "A100" if images else a.analyzer
    rig.configure(fs, analyzer)
    rig.tone(f0, a.level)
    time.sleep(a.settle)
    freqs, y = rig.run_fft(avg=a.fft_avg)
    analyze_spectrum(freqs, y, f0, fs, log, f"{'images' if images else 'FFT'} {analyzer}")
    return [(fs, analyzer, round(f, 3), v) for f, v in zip(freqs, y)]


def t_imd(rig, a, fs, ctx):
    log = rig.log
    rig.configure(fs)
    rows = []
    rig.src.twin("SMPTE", a.level)
    time.sleep(a.settle)
    (v1, u1), (v2, u2) = rig.measure("MDIS")
    log(f"   SMPTE 60 Hz + 7 kHz 4:1 ({a.level:+.0f} dBFS): L {fmt(ratio_db(v1, u1), '%.1f')} dB  "
        f"R {fmt(ratio_db(v2, u2), '%.1f')} dB")
    rows.append((fs, "SMPTE_60_7k", ratio_db(v1, u1), ratio_db(v2, u2)))
    rig.spec("imd")
    rig.src.twin("CCIF", a.level)
    time.sleep(a.settle)
    (v1, u1), (v2, u2) = rig.measure("DFD")
    log(f"   CCIF {ccif_name(fs)} kHz DFD ({a.level:+.0f} dBFS):  L {fmt(ratio_db(v1, u1), '%.1f')} dB  "
        f"R {fmt(ratio_db(v2, u2), '%.1f')} dB")
    rows.append((fs, f"CCIF_{ccif_name(fs).replace('+', '_')}k", ratio_db(v1, u1), ratio_db(v2, u2)))
    if a.imd_fft:
        freqs, y = rig.run_fft(avg=a.fft_avg)
        fund = peak_near(freqs, y, 19000, 20)
        for fx in (1000, 2000, 3000, 18000, 21000, fs - 19000, fs - 20000):
            if freqs and fx < freqs[-1]:
                log(f"     CCIF product/alias at {fx:.0f} Hz: "
                    f"{fmt(db(peak_near(freqs, y, fx, 15), fund), '%.1f')} dBc")
    rig.src.sine()
    return rows


def t_xtalk(rig, a, fs, ctx):
    log = rig.log
    rig.configure(fs)
    rig.selective("PTOC")
    rows = []
    for f in (100.0, 1000.0, 10000.0, min(16000.0, 0.4 * fs)):
        res = []
        for ch in ("L", "R"):
            f = rig.tone(f, -1.0, ch)
            time.sleep(a.settle)
            rig.trig()
            (v1, _), (v2, _) = rig.read12()
            res.append(db(v2, v1) if ch == "L" else db(v1, v2))
        rows.append((fs, f, res[0], res[1]))
        log(f"   {f:7.0f} Hz: L->R {fmt(res[0], '%.1f')} dB   R->L {fmt(res[1], '%.1f')} dB")
    rig.tone(997, -1.0)                           # back to both channels
    rig.spec("xtalk")
    return rows


def t_stability(rig, a, fs, ctx):
    """Is the output steady, and are both channels behaving alike? Aimed at the
    two usual causes of "erratic, and different per channel": a marginally
    oscillating stage (e.g. a fast op-amp swapped into an I/V converter) and
    dirty relay contacts carrying almost no current into a high-Z analyzer.
    The UPL can't see a MHz oscillation directly -- this looks for its side
    effects; an oscilloscope on the op-amp outputs is the definitive check."""
    log = rig.log
    rows = []
    # 1) idle noise at digital zero: 22 kHz vs 100 kHz analyzer, unweighted
    idle = {}
    for analyzer in ("A22", "A100"):
        rig.configure(fs, analyzer)
        rig.src.silence()
        time.sleep(max(a.settle, 1.0))
        (n1, _), (n2, _) = rig.measure("RMS")
        idle[analyzer] = (n1, n2)
        rows.append((fs, f"idle_{analyzer}_V", n1, n2))
    for ch, name in ((0, "L"), (1, "R")):
        n22, n100 = idle["A22"][ch], idle["A100"][ch]
        log(f"   {name}: idle noise {fmt(n22, '%.3g')} V (22k)  {fmt(n100, '%.3g')} V (100k)  "
            f"wide/narrow {fmt(db(n100, n22), '%+.1f')} dB")
    wl = [db(idle["A100"][c], idle["A22"][c]) for c in (0, 1)]
    if None not in wl and abs(wl[0] - wl[1]) > 3:
        log("   <- channels differ in ultrasonic noise by > 3 dB: suspect HF instability in the noisier one")
    # 2) level stability, 997 Hz -1 dBFS, repeated readings
    rig.configure(fs, "A22")
    rig.tone(997, -1.0)
    time.sleep(a.relock)
    series = []
    for i in range(a.readings):
        (v1, _), (v2, _) = rig.measure("RMS")
        series.append((v1, v2))
        rows.append((fs, f"level_{i}", v1, v2))
    for ch, name in ((0, "L"), (1, "R")):
        d = [db(v[ch], series[0][ch]) for v in series if v[ch] and series[0][ch]]
        if d:
            log(f"   {name}: {len(d)} readings at 997 Hz, spread {max(d) - min(d):.3f} dB"
                + ("   <- unsteady" if max(d) - min(d) > 0.05 else ""))
    # 3) 20 kHz at 0 dBFS on the wide analyzer -- where an I/V stage is hardest pushed
    rig.configure(fs, "A100")
    rig.tone(min(20000.0, 0.45 * fs), 0.0)
    time.sleep(a.settle)
    (t1, u1), (t2, u2) = rig.measure("THDN")
    log(f"   20 kHz 0 dBFS THD+N (100k): L {fmt(ratio_db(t1, u1), '%.1f')} dB  "
        f"R {fmt(ratio_db(t2, u2), '%.1f')} dB")
    rows.append((fs, "thdn_20k_0dBFS_A100", ratio_db(t1, u1), ratio_db(t2, u2)))
    # 4) output impedance, three times: a relay contact shows as high and/or wandering
    rig.configure(fs, "A22")
    rig.tone(997, -1.0)
    zs = []
    for rep_ in range(3):
        v = {}
        for imp in ("R200K", "R600"):
            rig.setc(f"INP:IMP {imp}")
            time.sleep(a.settle + 0.5)
            (x1, _), (x2, _) = rig.measure("RMS")
            v[imp] = (x1, x2)
        z = [600.0 * (h / l - 1.0) if h and l else None for h, l in zip(v["R200K"], v["R600"])]
        zs.append(z)
        rows.append((fs, f"zout_{rep_}", z[0], z[1]))
    rig.setc("INP:IMP R200K")
    for ch, name in ((0, "L"), (1, "R")):
        zz = [z[ch] for z in zs if z[ch] is not None]
        if zz:
            log(f"   {name}: Zout {', '.join('%.0f' % z for z in zz)} Ohm")
    rig.spec("zout")
    # 5) optional live monitor: tap relays, flex cables, watch
    if a.monitor > 0:
        log(f"   monitoring for {a.monitor:.0f} s -- tap the relays, flex cables, warm things up now")
        t0 = time.time()
        (r1, _), (r2, _) = rig.measure("RMS")
        while time.time() - t0 < a.monitor:
            (v1, _), (v2, _) = rig.measure("RMS")
            d1, d2 = db(v1, r1), db(v2, r2)
            flag = "  <--" if any(d is not None and abs(d) > 0.05 for d in (d1, d2)) else ""
            log(f"     t={time.time() - t0:5.1f}s  L {fmt(d1, '%+.3f')} dB  R {fmt(d2, '%+.3f')} dB{flag}")
            rows.append((fs, f"monitor_{time.time() - t0:.1f}", v1, v2))
    return rows


def t_zout(rig, a, fs, ctx):
    log = rig.log
    rig.configure(fs)
    rig.tone(997, -1.0)
    vals = {}
    for imp in ("R200K", "R600"):
        rig.setc(f"INP:IMP {imp}")
        time.sleep(a.settle + 0.5)
        (v1, _), (v2, _) = rig.measure("RMS")
        vals[imp] = (v1, v2)
    rig.setc("INP:IMP R200K")
    rows = []
    for ch, name in ((0, "L"), (1, "R")):
        vh, vl = vals["R200K"][ch], vals["R600"][ch]
        z = 600.0 * (vh / vl - 1.0) if vh and vl else None
        log(f"   {name}: {fmt(vh, '%.4f')} V open, {fmt(vl, '%.4f')} V into 600 Ohm -> "
            f"Zout ~ {fmt(z, '%.0f')} Ohm")
        rows.append((fs, name, vh, vl, z))
    rig.spec("zout")
    return rows


def t_polarity(rig, a, fs, ctx):
    log = rig.log
    rig.configure(fs)
    rig.setc("SOUR:FUNC POL", slow=True)
    rig.setc(f"SOUR:VOLT {lin(-6.0):.6g} FS", quiet=True)
    time.sleep(a.settle)
    rig.func("POL")

    def pol(reply):
        # '1 FS' = panel "+1 POL" (not inverted), '-1 FS' = "-1 POL" (inverted); the
        # unit is meaningless. Confirmed live 2026-09-25 by flipping the M51's polarity.
        v, _ = parse(reply)
        return None if v is None else ("normal (+1)" if v > 0 else "INVERTED (-1)")
    for _ in range(3):                            # first read can be the sentinel mid-burst
        rig.trig()
        r1, r2 = rig.q("SENS:DATA?"), rig.q("SENS:DATA2?")
        if pol(r1) and pol(r2):
            break
    log(f"   polarity: L {pol(r1) or 'no result'}  R {pol(r2) or 'no result'}   (raw {r1!r}, {r2!r})")
    rig.setc("SOUR:FUNC SIN", slow=True)
    return [(fs, r1, r2)]


def t_jitter(rig, a, fs, ctx):
    """Jitter transfer. Sinusoidal jitter of peak amplitude J seconds on the
    S/PDIF clock, if passed straight through to the DAC clock, puts sidebands at
    f0 +/- fj of 20*log10(pi*f0*J) dBc. 1 UI = 1/(128*fs) (biphase-mark, 64 bits
    per stereo frame, 2 UI per bit). Rejection = predicted - measured."""
    log = rig.log
    rig.configure(fs)
    if fs > BRM_MAX:
        log("   (jitter test at high rate is unverified; continuing)")
    f0 = fs / 4.0
    rig.tone(f0, -3.0)
    J = a.ui / (128.0 * fs)
    predicted = db(math.pi * f0 * J)
    rows = []
    for cable in ((False, True) if a.cable else (False,)):
        rig.setc(f"OUTP:DIG:CSIM {'SIML' if cable else 'OFF'}")
        rig.setc("SOUR2:FUNC OFF", slow=True)
        time.sleep(a.relock)
        freqs, y = rig.run_fft(avg=a.fft_avg)
        if not freqs:
            continue
        res = freqs[1] - freqs[0]
        fund = peak_near(freqs, y, f0, 4 * res)
        base = {fj: max(db(peak_near(freqs, y, f0 - fj, 3 * res), fund) or -200,
                        db(peak_near(freqs, y, f0 + fj, 3 * res), fund) or -200) for fj in a.jfreqs}
        rig.setc("SOUR2:FUNC JITT", slow=True)
        log(f"   {'LONG CABLE SIM, ' if cable else ''}tone {f0:.0f} Hz, jitter {a.ui*1000:.0f} mUI peak "
            f"= {J*1e9:.2f} ns; unrejected sidebands would be {predicted:.1f} dBc")
        for fj in a.jfreqs:
            if fj >= f0:
                continue
            rig.setc(f"SOUR2:FREQ {fj} HZ")
            rig.setc(f"SOUR2:VOLT {a.ui} UI")
            time.sleep(a.relock)
            freqs, y = rig.run_fft(avg=a.fft_avg)
            fund = peak_near(freqs, y, f0, 4 * res)
            sb = max(db(peak_near(freqs, y, f0 - fj, 3 * res), fund) or -200,
                     db(peak_near(freqs, y, f0 + fj, 3 * res), fund) or -200)
            above = sb - base[fj]
            rej = predicted - sb if above > 6 else None
            log(f"   fj {fj:6.0f} Hz: sideband {sb:7.1f} dBc (no-jitter floor {base[fj]:7.1f})  "
                + (f"rejection {rej:5.1f} dB" if rej is not None else "buried in floor -> rejection "
                   f">= {predicted - base[fj]:.0f} dB"))
            rows.append((fs, cable, a.ui, fj, sb, base[fj], predicted, rej))
        rig.setc("SOUR2:FUNC OFF", slow=True)
    rig.setc("OUTP:DIG:CSIM OFF")
    log("   (a DAC that re-clocks well shows rejection rising with fj; a plain PLL passes low fj through)")
    return rows


def jtest_samples(bits):
    """One period (192 samples) of the Dunn J-test: an fs/4 tone whose samples are
    exactly +/-0.5 FS (-3 dBFS peak, 45 deg phase) plus a 1-LSB square wave at
    fs/192. Every sample is exactly representable at `bits`, and the file's
    largest magnitude is 0.5 + 1 LSB, so with SOUR:VOLT:TOT set to that value the
    ARB generator's peak normalization is a scale of exactly 1."""
    lsb = 2.0 ** -(bits - 1)
    tone = (0.5, 0.5, -0.5, -0.5)
    return [tone[n % 4] + (lsb if n < 96 else 0.0) for n in range(192)], 0.5 + lsb


def t_jtest(rig, a, fs, ctx):
    """The J-test as ASR/Stereophile show it. Data-correlated jitter from the LSB
    square wave shows up as sidebands at f0 +/- odd multiples of fs/192 (250 Hz
    at 48 kHz); a DAC that rejects interface jitter shows a clean skirt."""
    log = rig.log
    rows = []
    f0, fsq = fs / 4.0, fs / 192.0
    for bits in a.jbits:
        rig.configure(fs)
        rig.src.jtest(bits)
        time.sleep(a.relock)
        freqs, y = rig.run_fft(avg=a.fft_avg)
        if not freqs:
            continue
        res = freqs[1] - freqs[0]
        fund = peak_near(freqs, y, f0, 4 * res)
        sb = []
        k = 1
        while k * fsq < min(f0, 20000 - f0):
            for s in (-1, 1):
                v = db(peak_near(freqs, y, f0 + s * k * fsq, 2 * res), fund)
                if v is not None:
                    sb.append((v, f0 + s * k * fsq))
            k += 2
        other = [db(v, fund) for f, v in zip(freqs, y)
                 # +/-16 bins: an off-bin tone (11025 Hz at 44.1k) has a Blackman-Harris
                 # skirt at -92 dBc out to ~60 Hz (live); still inside fs/192 = 230 Hz
                 if abs(f - f0) > 16 * res and abs(f - f0) < 3000
                 and all(abs(f - x) > 3 * res for _, x in sb)]
        worst = max(sb) if sb else (None, None)
        log(f"   {bits}-bit J-test, tone {f0:.0f} Hz: worst jitter sideband "
            f"{fmt(worst[0], '%.1f')} dBc at {fmt(worst[1], '%.0f')} Hz; "
            f"worst other spur within 3 kHz {fmt(max([o for o in other if o is not None], default=None), '%.1f')} dBc")
        rows += [(fs, bits, round(f, 3), v) for f, v in zip(freqs, y)]
    rig.src.sine()
    if rig.src.name == "upl":
        log("   (bit-exactness of the ARB playback is unverified: loop the UPL digital out into its own"
            " digital in once and check the fs/192 lines are there at the 1-LSB level)")
    return rows


A100_FS = 307200.0          # ANLG 110 kHz sampling rate (Vol.1 Table 2-27)
WAV_DEPTH = 7488            # WAVEFORM memory depth, samples (Vol.1 2.6.5.14)
RANGES = (0.018, 0.03, 0.06, 0.1, 0.18, 0.3, 0.6, 1, 1.8, 3, 6, 10, 18, 30, 60, 100)


def read_wave(rig, sel):
    """A WAVEFORM trace, paged like the FFT (TRAC? returns at most 1024 values;
    DISP:TRAC:IND selects the block). Unlike read_fft, an empty or non-numeric
    block ends it: 6144 samples (20 ms at 307.2 kHz) is exactly 6 full blocks."""
    t, y = [], []
    try:
        for blk in range(8):
            rig.w(f"DISP:TRAC:IND {blk}")
            try:
                yy = parse_values(rig.q(f"TRAC? {sel}"), sel)
                xx = parse_values(rig.q("TRAC? LIST1"), "LIST1")
            except ValueError:
                break
            n = min(len(xx), len(yy))
            t += xx[:n]
            y += yy[:n]
            if n < 1024:
                break
    finally:
        rig.w("DISP:TRAC:IND 0")
    return t, y


def imp_window(y, dt, period_s):
    """The impulse fully inside a capture: +/- period/2 around the largest |sample|
    that has that much room on both sides, re-centred to a fraction of a sample
    (parabolic fit of |y| at the peak, then an FFT phase shift). A capture spans
    two periods, so one such impulse is always there wherever the trigger fired."""
    y = np.asarray(y, dtype=float)
    half = int(round(period_s / 2 / dt))
    if len(y) < 2 * half + 3:
        return None
    seg = np.abs(y[half:len(y) - half])
    i = int(np.argmax(seg)) + half
    w = y[i - half:i + half].copy()
    a_, b_, c_ = abs(y[i - 1]), abs(y[i]), abs(y[i + 1])
    den = a_ - 2 * b_ + c_
    frac = 0.5 * (a_ - c_) / den if den else 0.0
    k = np.fft.rfftfreq(len(w))
    return np.fft.irfft(np.fft.rfft(w) * np.exp(2j * np.pi * k * frac), len(w))


def imp_analyze(h, dt, fs):
    """Figures from an averaged impulse h (peak at index len/2) sampled every dt."""
    n = len(h)
    c = n // 2
    t = (np.arange(n) - c) * dt
    pk = h[c]
    out = {"peak_V": pk, "polarity": "normal" if pk > 0 else "INVERTED"}
    hn = h / abs(pk)
    floor = np.sqrt(np.mean(hn[-n // 8:] ** 2))               # tail = noise (+ AC-coupling tilt)
    thr = max(1e-3, 4 * floor)                                # -60 dB or 4x the floor
    edge = 1.5 / fs                                           # past the main lobe's first zeros
    pre, post = np.abs(hn[t < -edge]), np.abs(hn[t > edge])
    out["floor_dB"] = db(floor)
    out["pre_dB"] = db(pre.max()) if len(pre) else None
    out["post_dB"] = db(post.max()) if len(post) else None
    above = np.nonzero(np.abs(hn) > thr)[0]
    out["ring_thr_dB"] = db(thr)
    out["ring_start_us"] = t[above[0]] * 1e6 if len(above) else None
    out["ring_end_us"] = t[above[-1]] * 1e6 if len(above) else None
    # how far it reaches before the peak vs after: ~1 linear phase, ~0 minimum phase.
    # (pre_dB alone can't tell: a minimum-phase main lobe rises over several samples.)
    s0, s1 = out["ring_start_us"], out["ring_end_us"]
    sym = -s0 / s1 if s0 is not None and s1 and s1 > 0 else None
    out["symmetry"] = sym
    p, q = out["pre_dB"] or -200, out["post_dB"] or -200
    if p < -40 and q < -40:
        kind = "no ringing to speak of (NOS, or a slow roll-off filter)"
    elif sym is not None and sym > 0.7:
        kind = "linear phase (rings as long before the peak as after)"
    elif sym is not None and sym < 0.25:
        kind = "minimum phase (rings after the peak only)"
    else:
        kind = "intermediate phase (shorter ringing before the peak than after)"
    out["type"] = kind
    tail = hn[t > edge]                                       # ringing frequency
    if len(tail) > 16:
        spec = np.abs(np.fft.rfft(tail * np.hanning(len(tail)), 8 * len(tail)))
        f = np.fft.rfftfreq(8 * len(tail), dt)
        m = f > 1000
        out["ring_Hz"] = float(f[m][np.argmax(spec[m])]) if m.any() else None
    step = np.cumsum(h) * np.sign(pk)
    final = np.mean(step[int(0.55 * n):int(0.6 * n)])         # 0.05-0.1 period after the edge
    step = step / final if final else step
    out["step"] = step
    out["overshoot_pct"] = (step.max() - 1) * 100
    out["preshoot_pct"] = -min(step[:c].min(), 0) * 100
    i10, i90 = np.argmax(step >= 0.1), np.argmax(step >= 0.9)
    out["rise_us"] = (i90 - i10) * dt * 1e6
    H = np.fft.rfft(np.fft.ifftshift(h))                      # t = 0 at index 0: no linear phase
    f = np.fft.rfftfreq(n, dt)
    ref = abs(H[np.argmin(np.abs(f - 1000))])
    out["f"], out["mag_dB"] = f, 20 * np.log10(np.maximum(np.abs(H), 1e-30) / ref)
    out["phase_deg"] = np.degrees(np.unwrap(np.angle(H * np.sign(pk))))
    i20 = np.argmin(np.abs(f - 20000))
    out["fr20k_dB"] = float(out["mag_dB"][i20])
    return t, out


def t_impulse(rig, a, fs, ctx):
    """Impulse and step response. The source plays one sample every --period; the
    UPL's WAVEFORM function (100 kHz analyzer, 307.2 kHz sampling, 7488 samples)
    records two periods per trigger, the PC keeps the impulse that fits with half a
    period either side, aligns to a fraction of a sample and averages --avg captures.
    A capture spans two periods, so where the trigger fires doesn't matter, and the
    pre-ringing of a linear-phase filter is kept (the WAVEFORM has no pre-trigger).

    Limits: A100 measures CH1 then CH2 (Vol.1 2.6.5.14), so L/R timing isn't
    comparable, and the level trigger means no absolute latency. The analyzer's own
    response is flat to ~110 kHz, well past any DAC's filter. From Vol.1/Vol.2
    only, first live run will tell: SENS:WAV:DUR, TRIG:LEV/SLOP, the WAV trace
    paging with DISP:TRAC:IND, TRAC? LIST1 as time, and fixed ranges being peak."""
    log = rig.log
    period = int(round(fs * a.period))
    per_s = period / fs
    dur = 2 * per_s
    if dur * A100_FS > WAV_DEPTH:
        per_s = WAV_DEPTH / A100_FS / 2.05
        period = int(per_s * fs)
        per_s = period / fs
        dur = 2 * per_s
        log(f"   --period too long for the {WAV_DEPTH}-sample memory: using {per_s * 1000:.2f} ms")
    rig.configure(fs, "A100")
    full = ctx.get("fullscale", {}).get(fs)
    if not full or not all(full):
        rig.src.sine()
        rig.tone(997, -6.0)
        time.sleep(a.settle)
        (v1, _), (v2, _) = rig.measure("RMS")
        full = tuple(2 * v if v else None for v in (v1, v2))
    if not all(full) or max(full) < 1e-3:
        log(f"   no output at -6 dBFS (L {fmt(full[0], '%.4f')} R {fmt(full[1], '%.4f')} V): "
            "DAC not locked, muted, or not connected; skipped")
        return []
    expect = max(full) * math.sqrt(2) * lin(a.imp_level)      # impulse peak <= sample value, about
    rng = next((r for r in RANGES if r >= 1.3 * expect), RANGES[-1])
    trig = a.trig_frac * expect * (1 if a.slope == "rise" else -1)
    log(f"   0 dBFS = {max(full):.3f} V rms -> expected impulse peak ~{expect:.3f} V; "
        f"range {rng:g} V, trigger {trig * 1000:+.1f} mV {a.slope}")
    rig.src.impulse(period, a.imp_level)
    time.sleep(max(a.settle, 0.5))
    rig.func("WAV")
    rig.setc("SENS:FUNC:MMOD STAN")
    rig.setc("SENS:SMO:APER N1", quiet=True)                  # no display interpolation
    rig.setc(f"SENS:WAV:DUR {dur:.6f} S")
    rig.setc("SENS:VOLT:RANG:AUTO OFF")                       # autorange would size it to the rms
    rig.setc(f"SENS:VOLT:RANG {rng:g} V")
    rig.setc(f"TRIG:LEV {trig:.6g} V")
    rig.setc(f"TRIG:SLOP {'RIS' if a.slope == 'rise' else 'FALL'}")
    for c in ("SENS:UNIT1 V", "SENS:UNIT2 V"):
        rig.setc(c, quiet=True)
    for c in ("FORM ASC", "DISP:TRAC:FEED 'SENS:DATA'", "DISP:TRAC2:FEED 'SENS:DATA2'"):
        rig.setc(c)
    wins = {"L": [], "R": []}
    dt = 1 / A100_FS
    try:
        for k in range(a.avg):
            rig.u.set_timeout(a.trig_timeout)
            rig.w("INIT:CONT OFF;*WAI")
            if rig.q("*OPC?").strip() != "1":
                raise RuntimeError(
                    f"no trigger within {a.trig_timeout:g} s. The UPL is still waiting for one and "
                    "won't answer: press STOP on its front panel (or power-cycle), then check the "
                    "DAC is locked and unmuted. An inverting DAC with no positive excursion needs "
                    "--slope fall; a quiet one a lower --trig-frac.")
            rig.u.set_timeout(a.timeout)
            for ch, sel in (("L", "TRAC1"), ("R", "TRAC2")):
                tx, y = read_wave(rig, sel)
                if k == 0 and ch == "L" and len(tx) > 2:
                    d = float(np.median(np.diff(tx)))
                    if 1e-4 <= d < 0.1:                       # ms, not s
                        d *= 1e-3
                    if 1e-7 < d < 1e-4:
                        dt = d
                    log(f"   capture: {len(y)} samples, dt {dt * 1e6:.3f} us"
                        f"{'' if abs(dt * A100_FS - 1) < 0.01 else '  (expected 3.255 us!)'}")
                w = imp_window(y, dt, per_s)
                if w is not None:
                    wins[ch].append(w)
    finally:
        rig.u.set_timeout(a.timeout)
        rig.setc("SENS:VOLT:RANG:AUTO ON", quiet=True)
        rig.func("RMS")
        rig.src.sine()
    rows, res = [], {}
    for ch in ("L", "R"):
        ws = wins[ch]
        if not ws:
            log(f"   {ch}: no complete impulse in the captures (too short: is DISP:TRAC:IND paging "
                "the waveform?)")
            continue
        n = min(len(w) for w in ws)
        h = np.mean([w[:n] for w in ws], axis=0)
        res[ch] = imp_analyze(h, dt, fs) + (h,)
    if not res:
        return []
    for ch, (t, o, h) in res.items():
        log(f"   {ch}: {o['type']}; peak {o['peak_V']:+.4f} V ({o['polarity']}), "
            f"{len(wins[ch])} captures averaged")
        log(f"      ringing: pre {fmt(o['pre_dB'], '%.1f')} / post {fmt(o['post_dB'], '%.1f')} dB re peak, "
            f"symmetry {fmt(o['symmetry'], '%.2f')}, at ~{fmt(o.get('ring_Hz'), '%.0f')} Hz; "
            f"above {o['ring_thr_dB']:.0f} dB from {fmt(o['ring_start_us'], '%.0f')} to "
            f"{fmt(o['ring_end_us'], '%.0f')} us (floor {o['floor_dB']:.0f} dB)")
        log(f"      step: rise 10-90 % {o['rise_us']:.1f} us, overshoot {o['overshoot_pct']:.1f} %, "
            f"pre-shoot {o['preshoot_pct']:.1f} %; response at 20 kHz {o['fr20k_dB']:+.2f} dB re 1 kHz")
    rig.spec("fr20k", fs)
    if len(res) == 2:
        dl = res["L"][1]["fr20k_dB"] - res["R"][1]["fr20k_dB"]
        el = [res[c][1]["ring_end_us"] for c in ("L", "R")]
        log(f"   L - R at 20 kHz {dl:+.2f} dB; ringing ends L {fmt(el[0], '%.0f')} / R {fmt(el[1], '%.0f')} us"
            + ("   <- channels differ: compare the impulse plots" if abs(dl) > 0.3 or
               (all(el) and abs(el[0] - el[1]) > 0.25 * max(el)) else ""))
    chs = [c for c in ("L", "R") if c in res]

    def get(c, arr, i):
        return float(res[c][arr][i]) if c in res else None
    t = res[chs[0]][0]
    m = min(len(res[c][0]) for c in chs)
    for i in range(m):
        rows.append((fs, "impulse", round(t[i] * 1e6, 3),
                     *(float(res[c][2][i]) if c in res else None for c in ("L", "R"))))
        rows.append((fs, "step", round(t[i] * 1e6, 3),
                     *(float(res[c][1]["step"][i]) if c in res else None for c in ("L", "R"))))
    f = res[chs[0]][1]["f"]
    for i in range(1, len(f)):
        if f[i] > min(0.5 * fs, 110000):
            break
        rows.append((fs, "mag_dB", round(float(f[i]), 2),
                     *(float(res[c][1]["mag_dB"][i]) if c in res else None for c in ("L", "R"))))
        rows.append((fs, "phase_deg", round(float(f[i]), 2),       # stopband phase is just noise
                     *(float(res[c][1]["phase_deg"][i])
                       if c in res and res[c][1]["mag_dB"][i] > -20 else None for c in ("L", "R"))))
    for key in ("type", "polarity", "peak_V", "pre_dB", "post_dB", "symmetry", "ring_Hz",
                "ring_start_us", "ring_end_us", "floor_dB", "rise_us", "overshoot_pct",
                "preshoot_pct", "fr20k_dB"):
        rows.append((fs, "summary", key, *(res[c][1].get(key) if c in res else None for c in ("L", "R"))))
    rows.append((fs, "summary", "captures", *(len(wins[c]) for c in ("L", "R"))))
    return rows


def report_impulse(rep, recs):
    for (fs,), g in _groups(recs, "fs").items():
        fs_i = int(float(fs))
        kinds = _groups(g, "kind")
        imp = kinds.get(("impulse",), [])
        if imp:
            pk = max(abs(_f(q[c])) for q in imp for c in ("L", "R") if not math.isnan(_f(q[c])))
            span = 25e6 / fs_i                                  # +/- 25 DAC samples, in us
            near = [q for q in imp if abs(_f(q["x"])) <= span]
            norm = [dict(q, L=_f(q["L"]) / pk, R=_f(q["R"]) / pk) for q in near]
            rep.plot(f"impulse_{fs}", _lr(norm, "x", "L", "R"),
                     title=f"Impulse response, {fs} Hz (±25 samples; the larger channel's peak = 1)",
                     xlabel="Time (µs)", ylabel="Relative to peak", markers=False,
                     hlines=[(0, None)])
            env = [dict(q, L=db(abs(_f(q["L"])), pk), R=db(abs(_f(q["R"])), pk)) for q in imp]
            rep.plot(f"impulse_env_{fs}", _lr(env, "x", "L", "R", style={"linewidth": 0.8}),
                     title=f"Impulse, {fs} Hz, dB re peak: how long it rings, and the noise floor",
                     xlabel="Time (µs)", ylabel="dB re peak", markers=False, ylim=(-120, 5))
        st = [q for q in kinds.get(("step",), []) if abs(_f(q["x"])) <= 25e6 / fs_i]
        if st:
            rep.plot(f"step_{fs}", _lr(st, "x", "L", "R"),
                     title=f"Step response, {fs} Hz (integrated impulse, settled value = 1)",
                     xlabel="Time (µs)", ylabel="Relative", markers=False, hlines=[(1, None), (0, None)])
        mg = kinds.get(("mag_dB",), [])
        if mg:
            rep.plot(f"imp_fr_{fs}", _lr(mg, "x", "L", "R"),
                     title=f"Frequency response from the impulse, {fs} Hz",
                     xlabel="Frequency (Hz)", ylabel="dB re 1 kHz", logx=True, markers=False,
                     ylim=(max(-60, min(min(_f(q["L"]), _f(q["R"])) for q in mg) - 3),
                           max(3, max(max(_f(q["L"]), _f(q["R"])) for q in mg) + 2)))
        ph = kinds.get(("phase_deg",), [])
        if ph:
            rep.plot(f"imp_phase_{fs}", _lr(ph, "x", "L", "R"),
                     title=f"Phase re the impulse peak, {fs} Hz (0 = linear phase; shown down to -20 dB)",
                     xlabel="Frequency (Hz)", ylabel="Degrees", logx=True, markers=False, height=3.2)
        sm = kinds.get(("summary",), [])
        if sm:
            rep.table(["measurement", "L", "R"], [(q["x"], q["L"], q["R"]) for q in sm],
                      title=f"Summary, {fs} Hz")


def t_multitone(rig, a, fs, ctx):
    """17-tone multisine (the UPL's maximum; ASR uses 32), log-spaced 20 Hz-20 kHz,
    tones snapped to FFT bins (spacing ATRack) so no window leakage. Everything
    between the tones is distortion + noise."""
    log = rig.log
    rig.configure(fs)
    rig.func("FFT")
    rig.setc("CALC:TRAN:FREQ:FFT S8K")
    tones = rig.src.multitone(geomspace(20.0, min(20000.0, 0.45 * fs), 17), a.mt_level)
    time.sleep(a.settle)
    freqs, y = rig.run_fft(avg=a.fft_avg)
    rows = [(fs, round(f, 3), v) for f, v in zip(freqs, y)]
    if len(freqs) > 2:
        res = freqs[1] - freqs[0]
        found = []
        for f in tones:
            near = [(v, fx) for fx, v in zip(freqs, y) if abs(fx - f) <= 3 * res]
            if near:
                found.append(max(near))
        ref = max(v for v, _ in found) if found else None
        between = [(v, fx) for fx, v in zip(freqs, y) if 20 <= fx <= 20000
                   and all(abs(fx - t) > 4 * res for _, t in found)]
        if ref and between:
            wv, wf = max(between)
            med = sorted(v for v, _ in between)[len(between) // 2]
            log(f"   multitone ({a.mt_level:+.0f} dBFS peak): tones span "
                f"{fmt(db(min(v for v, _ in found), ref), '%.2f')} dB; worst product between tones "
                f"{fmt(db(wv, ref), '%.1f')} dBc at {wf:.0f} Hz; median floor {fmt(db(med, ref), '%.1f')} dBc")
    rig.src.sine()
    return rows


def t_linearity(rig, a, fs, ctx):
    """Level error vs set level, 0 to -130 dBFS, selective (1 % bandpass tracking
    997 Hz) so noise doesn't lift the low end. 24-bit words, no dither needed."""
    log = rig.log
    rig.configure(fs)
    rig.selective("PPCT1")
    rows, ref = [], [None, None]
    for L in range(0, -131, -10):
        rig.tone(997, float(L))
        time.sleep(a.settle + (1.0 if L < -80 else 0.0))
        rig.trig()
        (v1, _), (v2, _) = rig.read12()
        if L == 0:
            ref = [v1, v2]
        e = [None if (db(v, r) is None) else db(v, r) - L for v, r in zip((v1, v2), ref)]
        rows.append((fs, L, v1, v2, e[0], e[1]))
        log(f"   {L:5d} dBFS: error L {fmt(e[0], '%+.2f')} dB  R {fmt(e[1], '%+.2f')} dB")
    for ch, name in ((4, "L"), (5, "R")):
        ok = [r[1] for r in rows if r[ch] is not None and abs(r[ch]) <= 0.1]
        log(f"   {name}: within 0.1 dB down to {min(ok) if ok else 'n/a'} dBFS")
    rig.spec("linearity")
    return rows


def t_imd_level(rig, a, fs, ctx):
    """SMPTE and CCIF IMD vs level, -60 to 0 dBFS -- ASR's "IMD vs output level"."""
    log = rig.log
    rig.configure(fs)
    rows = []
    levels = [-60, -50, -40, -30, -20, -12, -9, -6, -3, -1, 0]
    for name, fn in (("SMPTE", "MDIS"), ("CCIF", "DFD")):
        rig.src.twin(name, levels[0])
        rig.func(fn)
        res = []
        for L in levels:
            rig.src.twin(name, L)
            time.sleep(a.settle)
            rig.trig()
            (v1, u1), (v2, u2) = rig.read12()
            d = (ratio_db(v1, u1), ratio_db(v2, u2))
            rows.append((fs, name, L, d[0], d[1]))
            res.append((L, d))
        best = min(((d[0], L) for L, d in res if d[0] is not None), default=(None, None))
        log(f"   {name}: best {fmt(best[0], '%.1f')} dB at {fmt(best[1], '%+.0f')} dBFS; "
            f"at 0 dBFS {fmt(res[-1][1][0], '%.1f')} dB (L)")
        rig.func_cur = None
    rig.src.sine()
    return rows


def t_filter(rig, a, fs, ctx):
    """ASR's filter plot: white noise from the digital generator, wideband FFT on
    the 100 kHz analyzer. Shows passband ripple, where the filter starts, and how
    much of the image band gets through."""
    log = rig.log
    rig.configure(fs, "A100")
    rig.src.noise(-6.0)
    time.sleep(a.settle)
    freqs, y = rig.run_fft(avg=max(a.fft_avg, 16))
    rows = [(fs, round(f, 3), v) for f, v in zip(freqs, y)]

    def band(lo, hi):
        v = [x for f, x in zip(freqs, y) if lo <= f <= hi]
        return (sum(x * x for x in v) / len(v)) ** 0.5 if v else None

    ref = band(500, 5000)
    if ref:
        pts = [(0.40, 0.42), (0.45, 0.46), (0.49, 0.50), (0.50, 0.51), (0.55, 0.60), (0.60, 0.75)]
        log("   noise response re 0.5-5 kHz: " + ", ".join(
            f"{lo:.2f}-{hi:.2f}fs {fmt(db(band(lo * fs, hi * fs), ref), '%.1f')} dB"
            for lo, hi in pts if hi * fs < (freqs[-1] if freqs else 0)))
        log("   (a brick-wall filter is ~-100 dB by 0.55 fs; NOS/filterless DACs stay near 0 dB)")
    rig.src.sine()
    return rows


def t_interface(rig, a, fs, ctx):
    log = rig.log
    rig.configure(fs)
    rows = []

    def lock_level():
        rig.tone(997, -1.0)
        time.sleep(a.relock)
        (v1, _), (v2, _) = rig.measure("RMS")
        ok, fm = rig.locked(997, max(v1 or 0, v2 or 0))
        return ok, v1

    ok, ref = lock_level()
    # 1) minimum input voltage. Unbalanced (BNC) Vpp; balanced is always 4x.
    nominal = parse(rig.q("OUTP:SIGN:LEV?"))[0] or 0.5
    log(f"   min input voltage (unbalanced Vpp; nominal {nominal:g}):")
    for vpp in (0.5, 0.35, 0.25, 0.18, 0.12, 0.08, 0.05, 0.035, 0.025, 0.018):
        rig.setc(f"OUTP:SIGN:LEV {vpp} V")
        ok, v = lock_level()
        good = ok and ref and v and abs(db(v, ref)) < 1.0
        rows.append((fs, "vpp", vpp, good, v))
        log(f"     {vpp*1000:5.0f} mVpp: {'locked' if good else 'LOST'}")
    rig.setc(f"OUTP:SIGN:LEV {nominal} V")
    # 2) sample-rate lock range (base rate only: VALue mode 27-55 kHz)
    if fs <= BRM_MAX:
        log(f"   sample-rate lock range around {fs} Hz:")
        for ppm in (-50000, -10000, -1000, -100, 100, 1000, 10000, 50000):
            f = fs * (1 + ppm * 1e-6)
            rig.setc("OUTP:SAMP:MODE VAL", slow=True)
            rig.setc(f"OUTP:SAMP:FREQ {f:.1f} HZ", slow=True)
            ok, v = lock_level()
            rows.append((fs, "ppm", ppm, ok, v))
            log(f"     {ppm:+7d} ppm ({f:8.1f} Hz): {'locked' if ok else 'LOST'}")
        rig.setc(f"OUTP:SAMP:MODE {FS_MODES[fs]}", slow=True)
        time.sleep(a.relock)
    # 3) word length: does the DAC use bits beyond 16?
    log("   word length (THD+N at -60 dBFS, 997 Hz, A-weighted -- lower with more bits if they're used):")
    rig.func("THDN")                             # before the filter, see t_thdn
    rig.setc("SENS:FILT1:AWE ON")
    for bits in (16, 20, 24):
        rig.setc(f"OUTP:AUD {bits}")
        rig.tone(997, -60.0)
        time.sleep(a.settle)
        (v1, u1), (v2, u2) = rig.measure("THDN")
        rows.append((fs, "bits", bits, ratio_db(v1, u1), ratio_db(v2, u2)))
        log(f"     {bits}-bit: L {fmt(ratio_db(v1, u1), '%.1f')} dB  R {fmt(ratio_db(v2, u2), '%.1f')} dB")
    rig.setc(f"OUTP:AUD {a.bits}")
    rig.setc("SENS:FILT OFF")
    return rows


def t_volsweep(rig, a, fs, ctx):
    """THD+N, THD and level vs the DUT's own volume setting (was m51_gain_sweep.py):
    finds the setting to leave a DAC at when something downstream does the
    level control. Needs --dut; the DUT's volume is restored afterwards."""
    log = rig.log
    rig.configure(fs)
    rig.tone(997, a.level)
    rows = []
    for v in a.volumes:
        rig.dut.set_volume(v)
        time.sleep(a.settle + 0.3)
        (l1, _), (l2, _) = rig.measure("RMS")
        (n1, nu1), (n2, nu2) = rig.measure("THDN")
        (h1, hu1), (h2, hu2) = rig.measure("THD")
        r = (fs, v, l1, l2, ratio_db(n1, nu1), ratio_db(n2, nu2), ratio_db(h1, hu1), ratio_db(h2, hu2))
        rows.append(r)
        log(f"   volume {v:+6.1f} dB: L {fmt(l1, '%.4f')} V  R {fmt(l2, '%.4f')} V  "
            f"THD+N L {fmt(r[4], '%.1f')} R {fmt(r[5], '%.1f')} dB  THD L {fmt(r[6], '%.1f')} dB")
    best = min(((r[4], r[1]) for r in rows if r[4] is not None), default=None)
    if best:
        log(f"   best THD+N (L): {best[0]:.1f} dB at volume {best[1]:+.1f} dB "
            f"({a.level:+.0f} dBFS tone)")
    msg = rig.dut.restore()
    if msg:
        log(f"   {msg}")
    rig.dut.orig_volume = None                   # --volume (if any) is re-applied by main
    if a.volume is not None:
        rig.dut.set_volume(a.volume)
    return rows


CLIP_JUMP_DB = 10.0     # setlevel: THD this far above the best seen = clipping


def t_setlevel(rig, a, fs, ctx):
    """Guided level setting for a DUT with a manual volume control: plays 997 Hz at
    0 dBFS and shows L/R volts and THD about once a second while the user turns
    the knob, until Enter. With --target it says which way to turn; without one it
    flags clipping, so the loudest clean setting can be found. THD, not THD+N: THD+N
    of a clipping 0 dBFS tone latches the analyzer's THD+N floor (see Rig.unlatch).
    Then asks what the device's volume reads, for the report."""
    import threading
    log = rig.log
    rig.configure(fs)
    log("   Plays 997 Hz at 0 dBFS until you press Enter: NOTHING but the UPL on the outputs")
    log("   (no headphones, no amplifier).")
    if a.target:
        log(f"   Turn the volume until both channels read {a.target:g} V (within 0.1 dB).")
    else:
        log("   Turn the volume up until THD jumps (clipping), then back down until it's gone:")
        log("   that's the loudest clean setting. Or give --target V for a fixed output level.")
    if not a.dry_run:
        input("   Press Enter to start the tone... ")
    rig.tone(997, 0.0)
    time.sleep(a.settle)
    done = threading.Event()
    if not a.dry_run:
        threading.Thread(target=lambda: (input(), done.set()), daemon=True).start()
        log("   Adjust now; press Enter when done.")
    best, last, n, t0 = None, None, 0, time.time()
    while not done.is_set() and time.time() - t0 < a.max_time and not (a.dry_run and n >= 3):
        n += 1
        (v1, _), (v2, _) = rig.measure("RMS")
        (h1, hu1), (h2, hu2) = rig.measure("THD")
        t1, t2 = ratio_db(h1, hu1), ratio_db(h2, hu2)
        worst = max((t for t in (t1, t2) if t is not None), default=None)
        if worst is not None:
            best = worst if best is None else min(best, worst)
        line = f"   L {fmt(v1, '%.4f')} V  R {fmt(v2, '%.4f')} V   THD L {fmt(t1, '%.1f')} R {fmt(t2, '%.1f')} dB"
        if a.target and v1 and v2:
            off = db(math.sqrt(v1 * v2), a.target)           # geometric mean of L and R
            line += f"   {off:+.2f} dB vs target -> " + (
                "OK" if abs(off) <= 0.1 else "turn DOWN" if off > 0 else "turn UP")
        if worst is not None and best is not None and worst > best + CLIP_JUMP_DB:
            line += "   <- CLIPPING? back off"
        print(line, flush=True)
        last = (v1, v2, t1, t2)
    if time.time() - t0 >= a.max_time:
        log(f"   (stopped after --max-time {a.max_time:g} s)")
    setting = ""
    if done.is_set():                          # not after --max-time: that input() is still waiting
        setting = input("   What does the device's volume read? (for the report; Enter to skip) ").strip()
    rig.level_setting = setting
    if last is None:
        return []
    v1, v2, t1, t2 = last
    log(f"   level set: 0 dBFS -> L {fmt(v1, '%.4f')} V  R {fmt(v2, '%.4f')} V, "
        f"THD L {fmt(t1, '%.1f')} R {fmt(t2, '%.1f')} dB" + (f", volume '{setting}'" if setting else ""))
    ctx.setdefault("fullscale", {})[fs] = (v1, v2)
    return [(fs, a.target or "", setting, v1, v2, t1, t2)]


TESTS = {
    "setlevel":  (t_setlevel, ["fs", "target_V", "volume_setting", "L_V_0dBFS", "R_V_0dBFS",
                               "THD_L_dB", "THD_R_dB"]),
    "check":     (t_check, ["fs", "locked", "meas_freq_Hz", "fullscale_L_V", "fullscale_R_V",
                            "LminusR_dB", "dc_L_V", "dc_R_V"]),
    "fr":        (t_fr, ["fs", "analyzer", "pass", "mode", "freq_Hz", "L_V", "R_V",
                         "L_dB_re997", "R_dB_re997", "LminusR_dB"]),
    "thdn":      (t_thdn, ["fs", "analyzer", "sweep", "x", "func", "L", "R"]),
    "fft":       (t_fft, ["fs", "analyzer", "freq_Hz", "level_V"]),
    "images":    (lambda r, a, fs, c: t_fft(r, a, fs, c, images=True),
                  ["fs", "analyzer", "freq_Hz", "level_V"]),
    "imd":       (t_imd, ["fs", "test", "L_dB", "R_dB"]),
    "xtalk":     (t_xtalk, ["fs", "freq_Hz", "LtoR_dB", "RtoL_dB"]),
    "zout":      (t_zout, ["fs", "channel", "V_200k", "V_600", "Zout_ohm"]),
    "polarity":  (t_polarity, ["fs", "L_raw", "R_raw"]),
    "stability": (t_stability, ["fs", "item", "L", "R"]),
    "jitter":    (t_jitter, ["fs", "cable_sim", "jitter_UI", "fj_Hz", "sideband_dBc",
                             "floor_dBc", "predicted_dBc", "rejection_dB"]),
    "interface": (t_interface, ["fs", "test", "x", "result", "value"]),
    "jtest":     (t_jtest, ["fs", "bits", "freq_Hz", "level_V"]),
    "multitone": (t_multitone, ["fs", "freq_Hz", "level_V"]),
    "linearity": (t_linearity, ["fs", "set_dBFS", "L_V", "R_V", "L_err_dB", "R_err_dB"]),
    "imdlevel":  (t_imd_level, ["fs", "test", "level_dBFS", "L_dB", "R_dB"]),
    "filter":    (t_filter, ["fs", "freq_Hz", "level_V"]),
    "impulse":   (t_impulse, ["fs", "kind", "x", "L", "R"]),
    "volsweep":  (t_volsweep, ["fs", "volume_dB", "L_V", "R_V", "THDN_L_dB", "THDN_R_dB",
                               "THD_L_dB", "THD_R_dB"]),
}

# `all`: which tests, and at which sample rates (None = every --fs)
ALL_PLAN = [
    ("check", None), ("stability", "first"), ("fr", None), ("thdn", None), ("fft", None), ("images", None),
    ("imd", None), ("xtalk", None), ("zout", "first"), ("polarity", "first"),
    ("jitter", "base"), ("interface", "48k"),
    # ASR-style additions
    ("jtest", "base"), ("multitone", "first"), ("linearity", "first"),
    ("imdlevel", "first"), ("filter", None),
]


def check_options(rig, a, log):
    """--source upl: is the digital audio option in *OPT?, and which tests does what's
    missing rule out? B29 = 96 kHz, B2 = the older 55 kHz one (44.1/48 kHz here),
    B22 = jitter injection. Stops the run if nothing can feed the DAC."""
    opt = rig.q("*OPT?")
    have = {t.split("(")[0].strip() for t in opt.split(",")}
    log(f"# UPL options: {opt}")
    if "B29" not in have and "B2" not in have:
        raise SystemExit("This UPL has no digital audio option (UPL-B29 or B2), so it can't feed the "
                         "DAC. Use this PC as the source: --source pc --device N (a USB DAC, or a "
                         "USB-to-S/PDIF interface into the DAC's coax/optical input). See the README, "
                         "'Choosing the signal source'.")
    if "B29" not in have:
        high = [f for f in a.fs if f > BRM_MAX]
        if high:
            raise SystemExit(f"This UPL has UPL-B2, which runs at 44.1/48 kHz only: drop {high} "
                             f"from --fs (e.g. --fs 44100,48000).")
    if "B22" not in have:
        rig.src.unsupported["jitter"] = "needs UPL-B22 (jitter injection), not in *OPT?"


def run(rig, a, rep, log):
    """A single test at every --fs."""
    name = "images" if (a.test == "fft" and a.images) else a.test
    if name in rig.src.unsupported:
        log(f"\n=== {name}: {rig.src.unsupported[name]}; skipped ===")
        return
    if name == "volsweep" and rig.dut is None:
        log("\n=== volsweep: needs --dut (a DUT whose volume this script can set); skipped ===")
        return
    run_one(rig, a, rep, log, name, a.fs[:1] if name == "setlevel" else a.fs, {})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", help="COMn or GPIB0::20::INSTR (not needed with --dry-run)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--dry-run", action="store_true", help="no instrument; print the SCPI")
    p.add_argument("--source", choices=("upl", "pc"), default="upl",
                   help="upl: the UPL's digital generator into an S/PDIF/AES input (default); "
                        "pc: this PC plays the tones into a USB (or any) DAC")
    p.add_argument("--device", type=int,
                   help="--source pc: sounddevice output index (upacd_test.py devices lists them)")
    p.add_argument("--shared", action="store_true",
                   help="--source pc: allow Windows shared mode (resampled -- results suspect)")
    p.add_argument("--fs", default="44100,48000,88200,96000",
                   help="comma-separated sample rates; --source upl supports 44100,48000,88200,96000")
    p.add_argument("--bits", type=int, default=24, help="word length sent to the DAC (OUTP:AUD)")
    p.add_argument("--ground", action="store_true", help="INP:LOW GRO instead of FLOat")
    p.add_argument("--settle", type=float, default=0.3, help="seconds after each generator change")
    p.add_argument("--relock", type=float, default=2.0, help="seconds to let the DAC relock")
    add_output_args(p, default_label="dac")
    p.add_argument("--no-reset", action="store_true", help="skip the initial *RST")
    p.add_argument("--stay-remote", action="store_true",
                   help="leave the UPL in REMOTE at the end (default: SYST:COMM:GTL, panels back)")
    p.add_argument("--stepped", action="store_true",
                   help="fr/thdn: step the frequency from the PC instead of the UPL's own sweep")
    p.add_argument("--preserve", action="store_true",
                   help="snapshot the UPL setup first and restore it at the end (MMEM:STOR:STAT 2)")
    p.add_argument("--dut", choices=sorted(DUTS),
                   help="control the DUT too: log its state; with --volume set it for the run")
    p.add_argument("--dut-port", default="COM2", help="--dut serial port (M51: 115200, no handshake)")
    p.add_argument("--volume", type=float,
                   help="--dut: volume (dB) for the run, restored at the end. Leave out for a "
                        "fixed-output DAC (e.g. the M51's fixed-output setting)")
    p.add_argument("--dut-spec", metavar="NAME|FILE",
                   help="JSON file of the DUT's published figures to print next to each result; "
                        "a bare NAME means measurements/dut_specs/NAME.json")
    p.add_argument("--state-file", default="C:\\UPL\\USER\\UPLTMP.SCO")
    p.add_argument("--set-level", action="store_true",
                   help="run the guided `setlevel` step first (DUT with a manual volume control)")
    p.add_argument("--target", type=float,
                   help="setlevel: output (V rms) to reach at 0 dBFS, e.g. 2 (RCA) or 4 (XLR); "
                        "without it, setlevel helps find the loudest clean setting")
    p.add_argument("--max-time", type=float, default=600.0,
                   help="setlevel: stop the tone after this many seconds even without Enter")

    sub = p.add_subparsers(dest="test", required=True)
    for name in ("setlevel", "check", "zout", "polarity", "interface", "linearity", "imdlevel", "all"):
        sub.add_parser(name)
    s = sub.add_parser("stability")
    s.add_argument("--readings", type=int, default=20, help="repeated 997 Hz level readings")
    s.add_argument("--monitor", type=float, default=0.0,
                   help="then stream L/R level for this many seconds (tap relays, flex cables)")
    s = sub.add_parser("volsweep", help="THD+N/THD/level vs the DUT's volume (needs --dut)")
    s.add_argument("--volumes", default="-20,-15,-10,-6,-3,-1,0,1,3,6,10",
                   help="volume settings, dB")
    s.add_argument("--level", type=float, default=-1.0, help="test tone, dBFS")
    s = sub.add_parser("jtest")
    s.add_argument("--jbits", default="24,16", help="word lengths to run the J-test at")
    s.add_argument("--fft-avg", type=int, default=4)
    s = sub.add_parser("multitone")
    s.add_argument("--mt-level", type=float, default=-1.0, help="total peak, dBFS")
    s.add_argument("--fft-avg", type=int, default=4)
    s = sub.add_parser("filter")
    s.add_argument("--fft-avg", type=int, default=16)
    s = sub.add_parser("impulse", help="impulse/step response (WAVEFORM on the 100 kHz analyzer)")
    s.add_argument("--period", type=float, default=0.01,
                   help="impulse spacing, s (the analysis window; 10 ms = 100 Hz FFT resolution)")
    s.add_argument("--imp-level", type=float, default=-3.0,
                   help="impulse height, dBFS (-3: some DACs' output stages clip near 0 dBFS)")
    s.add_argument("--avg", type=int, default=8, help="captures averaged per channel")
    s.add_argument("--trig-frac", type=float, default=0.02,
                   help="trigger level, fraction of the expected impulse peak")
    s.add_argument("--slope", choices=("rise", "fall"), default="rise",
                   help="trigger slope; 'fall' for an inverting DAC with no positive excursion")
    s.add_argument("--trig-timeout", type=float, default=20.0,
                   help="seconds to wait for a trigger before giving up")
    s = sub.add_parser("fr")
    s.add_argument("--start", type=float, default=10.0)
    s.add_argument("--stop", type=float, help="default 20 kHz (or 0.45*fs with --wide)")
    s.add_argument("--points", type=int, default=31)
    s.add_argument("--level", type=float, default=-10.0, help="dBFS")
    s.add_argument("--repeat", type=int, default=2)
    s.add_argument("--wide", action="store_true", help="go to 0.45*fs on the 100 kHz analyzer")
    s = sub.add_parser("thdn")
    s.add_argument("--analyzer", default="A22", help="A22, A100 or A22,A100")
    s.add_argument("--freq-level", type=float, default=-1.0)
    s = sub.add_parser("fft")
    s.add_argument("--freq", type=float, default=997.0)
    s.add_argument("--level", type=float, default=-1.0)
    s.add_argument("--analyzer", default="A22")
    s.add_argument("--images", action="store_true",
                   help="wideband image check: 19 kHz tone on the 100 kHz analyzer")
    s.add_argument("--image-freq", type=float)
    s.add_argument("--fft-avg", type=int, default=4)
    s = sub.add_parser("imd")
    s.add_argument("--level", type=float, default=-3.0)
    s.add_argument("--imd-fft", action="store_true", help="also FFT the CCIF signal for aliases")
    s.add_argument("--fft-avg", type=int, default=4)
    s = sub.add_parser("xtalk")
    s = sub.add_parser("jitter")
    s.add_argument("--ui", type=float, default=0.1, help="peak jitter in UI (max 0.25)")
    s.add_argument("--jfreqs", default="100,300,1000,2000,5000,8000")
    s.add_argument("--cable", action="store_true", help="repeat with the 100 m cable simulator")
    s.add_argument("--fft-avg", type=int, default=4)

    a = p.parse_args()
    a.fs = [int(x) for x in a.fs.split(",")]
    for f in a.fs:
        if a.source == "upl" and f not in FS_MODES:
            p.error(f"--fs {f}: the UPL generator supports {sorted(FS_MODES)}")
    if a.source == "pc" and not a.dry_run and a.device is None:
        p.error("--source pc needs --device (python measurements/upacd_test.py devices)")
    # defaults for options that only some subcommands define (so `all` works)
    defaults = dict(start=10.0, stop=None, points=31, level=None, repeat=2, wide=False,
                    analyzer="A22", freq_level=-1.0, freq=997.0, images=False, image_freq=None,
                    fft_avg=4, imd_fft=False, ui=0.1, jfreqs="100,300,1000,2000,5000,8000", cable=False,
                    jbits="24,16", mt_level=-1.0, readings=20, monitor=0.0)
    for k, v in defaults.items():
        if not hasattr(a, k):
            setattr(a, k, v)
    if a.level is None:
        a.level = -10.0
    a.analyzers = a.analyzer.split(",")
    if a.volume is not None and not a.dut:
        p.error("--volume needs --dut")
    a.volumes = [float(v) for v in str(getattr(a, "volumes", "0")).split(",")]
    a.levels = [-100, -90, -80, -70, -60, -50, -40, -30, -20, -12, -6, -3, -1, 0]
    a.jfreqs = [float(x) for x in str(a.jfreqs).split(",")]
    a.jbits = [int(x) for x in str(a.jbits).split(",")]
    a.ui = min(a.ui, 0.25)
    a.spec = load_spec(a.dut_spec) if a.dut_spec else None

    if a.dry_run:
        u = DryRunUPL(echo=False)
    else:
        if not a.port:
            p.error("--port is required (or use --dry-run)")
        u = connect(a.port, a.baud, a.timeout)
    label = ("dryrun_" if a.dry_run else "") + a.label
    with Run("dac", label=label, outdir=a.outdir, title=f"DAC test: {a.test}") as rep:
        _main(u, a, rep)


def _main(u, a, rep):
    log = Log(None)                     # printed; the report copies it into summary.txt
    rig = Rig(u, log, a, a.source)
    rig.dut = None
    if a.dut:
        rig.dut = DryDut(a.dut) if a.dry_run else DUTS[a.dut](a.dut_port)
    log(f"# dac_test {a.test}  label={a.label}  source={a.source}  fs={a.fs}  "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
    idn = rig.q("*IDN?")
    log(f"# UPL: {idn}")
    rep.info("UPL", idn)
    if a.source == "upl":
        check_options(rig, a, log)
    rep.info("Source", a.source + (f" (device {a.device})" if a.source == "pc" else ""))
    rep.info("Sample rates", ", ".join(str(f) for f in a.fs))
    if a.spec:
        log(f"# DUT reference: {a.spec.get('name', a.dut_spec)}")
        rep.info("DUT reference", a.spec.get("name", a.dut_spec))
    try:
        if rig.dut:
            log(f"# DUT: {rig.dut.describe()}")
            rep.info("DUT", rig.dut.describe())
            if a.volume is not None:
                rig.dut.set_volume(a.volume)
                log(f"# DUT volume set to {a.volume:g} dB for this run (restored at the end)")
        with preserve_state(u, a.state_file, enabled=a.preserve):
            if not a.no_reset:
                rig.setc("*RST", slow=True)
                rig.w("*CLS")
            rig.level_setting = ""
            if a.set_level and a.test != "setlevel":
                run_one(rig, a, rep, log, "setlevel", a.fs[:1], {})
            if a.test == "all":
                run_all(rig, a, rep, log)
            else:
                run(rig, a, rep, log)
            rig.cleanup()
            if rig.level_setting:
                rep.info("DUT volume setting", rig.level_setting)
    finally:
        if rig.dut:
            msg = rig.dut.restore()
            if msg:
                log(f"# DUT {msg}")
            rig.dut.close()
        if rig.src.name == "pc":
            rig.src.close()                          # never leave a tone playing
        if rig.rejected:
            log(f"\n# {len(rig.rejected)} command(s) rejected by the UPL:")
            for c, e in rig.rejected:
                log(f"#   {c}  [{e}]")
            rep.heading("Commands the UPL rejected")
            rep.table(["command", "error"], rig.rejected)
        if not a.stay_remote:
            go_local(u)                              # front panel back, showing the last result
        u.close()
    log(f"\n# done -> {rep.dir}")


def run_all(rig, a, rep, log):
    """`all` with per-test levels: fr at -10 dBFS, fft at -1, imd at -3."""
    ctx = {}
    per_test_level = {"fr": -10.0, "fft": -1.0, "images": -1.0, "imd": -3.0}
    for name, which in ALL_PLAN:
        if name in rig.src.unsupported:
            log(f"\n=== {name}: {rig.src.unsupported[name]}; skipped ===")
            continue
        rates = a.fs
        if which == "first":
            rates = a.fs[:1]
        elif which == "base":
            rates = [f for f in a.fs if f <= BRM_MAX] or a.fs[:1]
        elif which == "48k":
            rates = [48000] if 48000 in a.fs else a.fs[:1]
        a.level = per_test_level.get(name, a.level)
        run_one(rig, a, rep, log, name, rates, ctx)


def run_one(rig, a, rep, log, name, rates, ctx):
    """Test `name` at each of `rates`. The CSV and report section are written even if a
    rate fails, keeping the rates before it."""
    fn, header = TESTS[name]
    rows = []
    try:
        for fs in rates:
            log(f"\n=== {name} @ {fs} Hz ===")
            rows += fn(rig, a, fs, ctx)
    finally:
        rep.csv(f"{name}.csv", header, rows)
        report_test(rep, name, header, rows)


if __name__ == "__main__":
    main()
