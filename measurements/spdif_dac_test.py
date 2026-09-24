#!/usr/bin/env python3
"""
spdif_dac_test.py - characterize an S/PDIF-input DAC with the UPL.

Signal path:  UPL digital generator (B29)  ->  DAC S/PDIF input
              DAC analog out (L, R)        ->  UPL analog analyzer (both channels)

The UPL is the source, not the laptop: bit-exact, sample rate set by the UPL,
and the interface itself can be degraded on purpose (jitter via B22, cable
simulator, reduced signal voltage, word length, off-nominal sample rate).

Tests (subcommands), in the order worth running them:
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
  all        everything above, sensible defaults

Comparing with ASR: set the DAC to 2 V (unbalanced) / 4 V (balanced) at 0 dBFS if it
has a volume control; ASR's SINAD = -(THD+N at 0 dBFS), printed by `thdn`. This
UPL's own THD+N floor is roughly -103 to -106 dB (loopback), well above an
APx555's, so SINAD figures beyond ~100 dB are the UPL's floor, not the DAC's.

Usage:
  python measurements/spdif_dac_test.py --dry-run all                 # offline, prints SCPI
  python measurements/spdif_dac_test.py --port COM7 check
  python measurements/spdif_dac_test.py --port COM7 --fs 44100,96000 fr
  python measurements/spdif_dac_test.py --port GPIB0::20::INSTR --label mydac all

Output: results/spdif_dac/<label>_<timestamp>/ -- one CSV per test and
summary.txt (everything printed to the console).

NOT YET RUN AGAINST HARDWARE (written 2026-09-24). Everything below is from
Vol.2 and has never been sent to this unit:
  - the mixed setup, digital generator + analog analyzer (INST D48 + INST2 A22)
  - CONF:DAI HRM for 88.2/96 kHz. Vol.2 3.10.8.5 warns it also reduces
    analog-analyzer performance, so it's used only for those rates and set
    back to BRM at the end
  - SOUR2:FUNC JITT / SOUR2:VOLT <n> UI, OUTP:SIGN:LEV, OUTP:SAMP:MODE VAL
  - SENS:VOLT:APER:MODE GENT, SENS:FREQ:MODE GENT with 'RMSS', 'POL', 'MDIS'
Every config command is followed by SYST:ERR? and a rejection is printed, so the
first live run will show exactly what this firmware accepts. Run `check` first.

Conventions carried over from the rest of the project (see CLAUDE.md):
one command per write and *OPC? after slow ones (the PL2303 byte-doubling
problem); 9.93e37 and -240 dB are "no value" sentinels; *RST does not clear
the error queue, so *CLS.
"""
import argparse
import csv
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from upl_capture import connect, DryRunUPL, read_fft, preserve_state  # noqa: E402

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


def write_csv(path, header, rows, log):
    with open(path, "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(header)
        w.writerows(rows)
    log(f"  -> {path}")


# ---------------------------------------------------------------- the rig

class Rig:
    """Thin layer over upl_capture's UPL: error-checked config writes, function
    switching, trigger-and-read, and the digital-gen/analog-analyzer setup."""

    def __init__(self, u, log, args):
        self.u, self.log, self.args = u, log, args
        self.func_cur = None
        self.state = None           # (fs, analyzer) currently configured
        self.rejected = []

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

    def func(self, name):
        if name != self.func_cur:
            self.setc(f"SENS1:FUNC '{name}'", slow=True)
            self.func_cur = name

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
        self.log(f"\n-- configure: fs={fs} Hz, analyzer={analyzer}, {a.bits}-bit")
        self.w("*CLS")
        self.setc(f"CONF:DAI {'HRM' if fs > BRM_MAX else 'BRM'}", slow=True)
        self.setc("INST D48", slow=True)
        self.setc(f"INST2 {analyzer}", slow=True)
        self.setc("SOUR:DIG:FEED ADAT")
        self.setc(f"OUTP:SAMP:MODE {FS_MODES[fs]}", slow=True)
        self.setc(f"OUTP:AUD {a.bits}")
        self.setc("OUTP:DIG:CSIM OFF")
        self.setc("SOUR2:FUNC OFF", slow=True)
        self.setc("OUTP:SEL CH2Is1")              # both channels, in phase
        self.setc("SOUR:FUNC SIN", slow=True)
        # analyzer -- nothing survives an INST2 change, so all of it every time
        self.setc("INP:TYPE BAL")
        self.setc("INP:SEL BOTH")
        self.setc(f"INP:LOW {'GRO' if a.ground else 'FLO'}")
        self.setc("INP:IMP R200K")
        self.setc("SENS:VOLT:RANG:AUTO ON")
        self.setc("SENS2:FUNC 'OFF'")
        self.setc("SENS3:FUNC 'FREQ'")
        self.setc("SENS:FILT OFF")
        self.func_cur = None
        self.state = (fs, analyzer)
        self.log(f"   INST? {self.q('INST?')!r}  INST2? {self.q('INST2?')!r}")
        time.sleep(a.relock)                      # let the DAC lock to the new rate

    def tone(self, f, dbfs):
        self.setc(f"SOUR:FREQ {f:.4f} HZ", quiet=True)
        self.setc(f"SOUR:VOLT {lin(dbfs):.6g} FS", quiet=True)

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
        self.log("\n-- cleanup: generator muted, jitter/cable sim off, base rate mode")
        for c in ("SOUR:VOLT 0 FS", "SOUR2:FUNC OFF", "OUTP:DIG:CSIM OFF",
                  "OUTP:SEL CH2Is1", "INP:IMP R200K", "SENS:FILT OFF", "CONF:DAI BRM"):
            self.setc(c, quiet=True)


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


def t_fr(rig, a, fs, ctx):
    log = rig.log
    stop = a.stop if a.stop else (0.45 * fs if a.wide else min(20000.0, 0.45 * fs))
    analyzer = "A100" if (a.wide or stop > 21000) else "A22"
    rig.configure(fs, analyzer)
    if not rig.setc("SENS:VOLT:APER:MODE GENT"):
        rig.setc("SENS:VOLT:APER:MODE AUTO")
    freqs = geomspace(a.start, stop, a.points)
    rows, data = [], {}
    for p in range(a.repeat):
        for mode in ("RMS", "RMSS"):
            rig.func(mode)
            if mode == "RMSS":
                rig.setc("SENS:FREQ:MODE GENT")
                rig.setc("SENS:BAND:MODE PTOC")   # 1/3-octave bandpass that follows the generator
            rig.tone(997, a.level)
            time.sleep(a.settle)
            rig.trig()
            (r1, _), (r2, _) = rig.read12()
            for f in freqs:
                rig.tone(f, a.level)
                time.sleep(a.settle)
                rig.trig()
                (v1, _), (v2, _) = rig.read12()
                d1, d2 = db(v1, r1), db(v2, r2)
                lr = db(v1, v2) if v1 and v2 else None
                data[(p, mode, f)] = (d1, d2, lr)
                rows.append((fs, analyzer, p + 1, mode, round(f, 2), v1, v2,
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
        # vs level @ 997 Hz
        for fn in ("THDN", "THD"):
            rig.func(fn)
            for L in a.levels:
                rig.tone(997, L)
                time.sleep(a.settle)
                rig.trig()
                (v1, u1), (v2, u2) = rig.read12()
                rows.append((fs, analyzer, "level", L, fn, ratio_db(v1, u1), ratio_db(v2, u2)))
        # vs frequency @ --freq-level
        for fn in ("THDN", "THD"):
            rig.func(fn)
            for f in geomspace(20, min(20000, 0.45 * fs), 16):
                rig.tone(f, a.freq_level)
                time.sleep(a.settle)
                rig.trig()
                (v1, u1), (v2, u2) = rig.read12()
                rows.append((fs, analyzer, "freq", round(f, 1), fn, ratio_db(v1, u1), ratio_db(v2, u2)))
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
    rig.setc("SENS:FILT1:AWE ON")
    rig.func("THDN")
    rig.tone(997, -60.0)
    time.sleep(a.settle)
    rig.trig()
    (v1, u1), (v2, u2) = rig.read12()
    dr = [None if ratio_db(v, u) is None else 60.0 - ratio_db(v, u) for v, u in ((v1, u1), (v2, u2))]
    # idle noise, digital silence, A-weighted
    rig.setc("SOUR:VOLT 0 FS", quiet=True)
    time.sleep(max(a.settle, 1.0))
    (n1, _), (n2, _) = rig.measure("RMS")
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
    lvl = lin(a.level)
    # SMPTE: SOUR:FREQ = upper (7 kHz), SOUR:FREQ2 = lower (60 Hz), ratio LF:UF 4 (Vol.2 3.10.1.5.5)
    for c in ("SOUR:FUNC MDIS", "SOUR:FREQ 7000 HZ", "SOUR:FREQ2 60 HZ", "SOUR:VOLT:RAT 4",
              f"SOUR:VOLT:TOT {lvl:.6g} FS"):
        rig.setc(c, slow=c.startswith("SOUR:FUNC"))
    time.sleep(a.settle)
    (v1, u1), (v2, u2) = rig.measure("MDIS")
    log(f"   SMPTE 60 Hz + 7 kHz 4:1 ({a.level:+.0f} dBFS): L {fmt(ratio_db(v1, u1), '%.1f')} dB  "
        f"R {fmt(ratio_db(v2, u2), '%.1f')} dB")
    rows.append((fs, "SMPTE_60_7k", ratio_db(v1, u1), ratio_db(v2, u2)))
    rig.spec("imd")
    # CCIF twin tone 19 + 20 kHz as DFD mean/diff
    for c in ("SOUR:FUNC DFD", "SOUR:FREQ:MEAN 19500 HZ", "SOUR:FREQ:DIFF 1000 HZ",
              f"SOUR:VOLT:TOT {lvl:.6g} FS"):
        rig.setc(c, slow=c.startswith("SOUR:FUNC"))
    time.sleep(a.settle)
    (v1, u1), (v2, u2) = rig.measure("DFD")
    log(f"   CCIF 19+20 kHz  DFD ({a.level:+.0f} dBFS):    L {fmt(ratio_db(v1, u1), '%.1f')} dB  "
        f"R {fmt(ratio_db(v2, u2), '%.1f')} dB")
    rows.append((fs, "CCIF_19_20k", ratio_db(v1, u1), ratio_db(v2, u2)))
    if a.imd_fft:
        freqs, y = rig.run_fft(avg=a.fft_avg)
        fund = peak_near(freqs, y, 19000, 20)
        for fx in (1000, 2000, 3000, 18000, 21000, fs - 19000, fs - 20000):
            if freqs and fx < freqs[-1]:
                log(f"     CCIF product/alias at {fx:.0f} Hz: "
                    f"{fmt(db(peak_near(freqs, y, fx, 15), fund), '%.1f')} dBc")
    rig.setc("SOUR:FUNC SIN", slow=True)
    return rows


def t_xtalk(rig, a, fs, ctx):
    log = rig.log
    rig.configure(fs)
    rig.func("RMSS")
    rig.setc("SENS:FREQ:MODE GENT")
    rig.setc("SENS:BAND:MODE PTOC")
    rows = []
    for f in (100.0, 1000.0, 10000.0, min(16000.0, 0.4 * fs)):
        res = []
        for sel in ("CH1", "CH2"):
            rig.setc(f"OUTP:SEL {sel}")
            rig.tone(f, -1.0)
            time.sleep(a.settle)
            rig.trig()
            (v1, _), (v2, _) = rig.read12()
            res.append(db(v2, v1) if sel == "CH1" else db(v1, v2))
        rows.append((fs, f, res[0], res[1]))
        log(f"   {f:7.0f} Hz: L->R {fmt(res[0], '%.1f')} dB   R->L {fmt(res[1], '%.1f')} dB")
    rig.setc("OUTP:SEL CH2Is1")
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
        rig.setc("SOUR:VOLT 0 FS", quiet=True)
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
    rig.trig()
    r1, r2 = rig.q("SENS:DATA?"), rig.q("SENS:DATA2?")
    log(f"   polarity: L {r1!r}  R {r2!r}   (raw replies; format unconfirmed -- "
        "check against the ANLR panel the first time)")
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
        samples, peak = jtest_samples(bits)
        body = "# J-test, 192 samples, fs/4 tone + 1 LSB square at fs/192, %d-bit\nTIMETAB_FILE\n" % bits
        body += "\n".join("%.12f" % s for s in samples) + "\n"
        path = f"C:\\UPL\\USER\\JTEST{bits}.TTF"
        rig.upload(path, body.encode("ascii"))
        rig.setc(f"OUTP:AUD {bits}")
        rig.setc("SOUR:FUNC ARB", slow=True)
        rig.setc(f"MMEM:LOAD:LIST ARB,'{path}'", slow=True)
        rig.setc(f"SOUR:VOLT:TOT {peak:.12f} FS")
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
                 if abs(f - f0) > 6 * res and abs(f - f0) < 3000
                 and all(abs(f - x) > 3 * res for _, x in sb)]
        worst = max(sb) if sb else (None, None)
        log(f"   {bits}-bit J-test, tone {f0:.0f} Hz: worst jitter sideband "
            f"{fmt(worst[0], '%.1f')} dBc at {fmt(worst[1], '%.0f')} Hz; "
            f"worst other spur within 3 kHz {fmt(max([o for o in other if o is not None], default=None), '%.1f')} dBc")
        rows += [(fs, bits, round(f, 3), v) for f, v in zip(freqs, y)]
    rig.setc(f"OUTP:AUD {a.bits}")
    rig.setc("SOUR:FUNC SIN", slow=True)
    log("   (bit-exactness of the ARB playback is unverified: loop the UPL digital out into its own"
        " digital in once and check the fs/192 lines are there at the 1-LSB level)")
    return rows


def t_multitone(rig, a, fs, ctx):
    """17-tone multisine (the UPL's maximum; ASR uses 32), log-spaced 20 Hz-20 kHz,
    tones snapped to FFT bins (spacing ATRack) so no window leakage. Everything
    between the tones is distortion + noise."""
    log = rig.log
    rig.configure(fs)
    rig.func("FFT")
    rig.setc("CALC:TRAN:FREQ:FFT S8K")
    rig.setc("SOUR:FUNC MULT", slow=True)
    rig.setc("SOUR:MULT:MODE EQU")
    rig.setc("SOUR:MULT:COUN 17")
    rig.setc("SOUR:RAND:SPAC:MODE ATR")
    rig.setc("SOUR:VOLT:CRES:MODE MIN", slow=True)
    tones = geomspace(20.0, min(20000.0, 0.45 * fs), 17)
    for i, f in enumerate(tones, 1):
        rig.setc(f"SOUR:FREQ{i} {f:.2f} HZ", quiet=True)
    amp = 0.05
    for _ in range(3):                       # scale per-tone level to --level total peak
        rig.setc(f"SOUR:VOLT1 {amp:.6g} FS", quiet=True)
        tot = parse(rig.q("SOUR:VOLT:TOT?"))[0]
        if not tot or tot <= 0:
            break
        amp = min(amp * lin(a.mt_level) / tot, 1.0 / 17)
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
    rig.setc("SOUR:FUNC SIN", slow=True)
    return rows


def t_linearity(rig, a, fs, ctx):
    """Level error vs set level, 0 to -130 dBFS, selective (1 % bandpass tracking
    997 Hz) so noise doesn't lift the low end. 24-bit words, no dither needed."""
    log = rig.log
    rig.configure(fs)
    rig.func("RMSS")
    rig.setc("SENS:FREQ:MODE GENT")
    rig.setc("SENS:BAND:MODE PPCT1")
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
    for name, setup, fn in (
            ("SMPTE", ("SOUR:FUNC MDIS", "SOUR:FREQ 7000 HZ", "SOUR:FREQ2 60 HZ", "SOUR:VOLT:RAT 4"), "MDIS"),
            ("CCIF", ("SOUR:FUNC DFD", "SOUR:FREQ:MEAN 19500 HZ", "SOUR:FREQ:DIFF 1000 HZ"), "DFD")):
        for c in setup:
            rig.setc(c, slow=c.startswith("SOUR:FUNC"))
        rig.func(fn)
        res = []
        for L in levels:
            rig.setc(f"SOUR:VOLT:TOT {lin(L):.6g} FS", quiet=True)
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
    rig.setc("SOUR:FUNC SIN", slow=True)
    return rows


def t_filter(rig, a, fs, ctx):
    """ASR's filter plot: white noise from the digital generator, wideband FFT on
    the 100 kHz analyzer. Shows passband ripple, where the filter starts, and how
    much of the image band gets through."""
    log = rig.log
    rig.configure(fs, "A100")
    rig.setc("SOUR:FUNC RAND", slow=True)
    rig.setc("SOUR:RAND:DOM TIME")
    rig.setc(f"SOUR:VOLT:TOT {lin(-6.0):.6g} FS")
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
    rig.setc("SOUR:FUNC SIN", slow=True)
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


TESTS = {
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


def run(rig, a, outdir, log):
    """A single test at every --fs."""
    name = "images" if (a.test == "fft" and a.images) else a.test
    fn, header = TESTS[name]
    ctx, rows = {}, []
    for fs in a.fs:
        log(f"\n=== {name} @ {fs} Hz ===")
        rows += fn(rig, a, fs, ctx)
    write_csv(os.path.join(outdir, f"{name}.csv"), header, rows, log)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", help="COMn or GPIB0::20::INSTR (not needed with --dry-run)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--dry-run", action="store_true", help="no instrument; print the SCPI")
    p.add_argument("--fs", default="44100,48000,88200,96000",
                   help="comma-separated sample rates (44100,48000,88200,96000)")
    p.add_argument("--bits", type=int, default=24, help="word length sent to the DAC (OUTP:AUD)")
    p.add_argument("--ground", action="store_true", help="INP:LOW GRO instead of FLOat")
    p.add_argument("--settle", type=float, default=0.3, help="seconds after each generator change")
    p.add_argument("--relock", type=float, default=2.0, help="seconds to let the DAC relock")
    p.add_argument("--label", default="dac")
    p.add_argument("--outdir", help="default results/spdif_dac/<label>_<timestamp>")
    p.add_argument("--no-reset", action="store_true", help="skip the initial *RST")
    p.add_argument("--preserve", action="store_true",
                   help="snapshot the UPL setup first and restore it at the end (MMEM:STOR:STAT 2)")
    p.add_argument("--dut-spec", metavar="NAME|FILE",
                   help="JSON file of the DUT's published figures to print next to each result; "
                        "a bare NAME means measurements/dut_specs/NAME.json")
    p.add_argument("--state-file", default="C:\\UPL\\USER\\UPLTMP.SCO")

    sub = p.add_subparsers(dest="test", required=True)
    for name in ("check", "zout", "polarity", "interface", "linearity", "imdlevel", "all"):
        sub.add_parser(name)
    s = sub.add_parser("stability")
    s.add_argument("--readings", type=int, default=20, help="repeated 997 Hz level readings")
    s.add_argument("--monitor", type=float, default=0.0,
                   help="then stream L/R level for this many seconds (tap relays, flex cables)")
    s = sub.add_parser("jtest")
    s.add_argument("--jbits", default="24,16", help="word lengths to run the J-test at")
    s.add_argument("--fft-avg", type=int, default=4)
    s = sub.add_parser("multitone")
    s.add_argument("--mt-level", type=float, default=-1.0, help="total peak, dBFS")
    s.add_argument("--fft-avg", type=int, default=4)
    s = sub.add_parser("filter")
    s.add_argument("--fft-avg", type=int, default=16)
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
        if f not in FS_MODES:
            p.error(f"--fs {f}: supported {sorted(FS_MODES)}")
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
    a.levels = [-100, -90, -80, -70, -60, -50, -40, -30, -20, -12, -6, -3, -1, 0]
    a.jfreqs = [float(x) for x in str(a.jfreqs).split(",")]
    a.jbits = [int(x) for x in str(a.jbits).split(",")]
    a.ui = min(a.ui, 0.25)
    a.spec = load_spec(a.dut_spec) if a.dut_spec else None

    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = a.outdir or os.path.join("results", "spdif_dac", f"{a.label}_{stamp}")
    os.makedirs(outdir, exist_ok=True)
    log = Log(os.path.join(outdir, "summary.txt"))

    if a.dry_run:
        u = DryRunUPL(echo=False)
    else:
        if not a.port:
            p.error("--port is required (or use --dry-run)")
        u = connect(a.port, a.baud, a.timeout)
    rig = Rig(u, log, a)
    log(f"# spdif_dac_test {a.test}  label={a.label}  fs={a.fs}  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"# UPL: {rig.q('*IDN?')}")
    if a.spec:
        log(f"# DUT reference: {a.spec.get('name', a.dut_spec)}")
    try:
        with preserve_state(u, a.state_file, enabled=a.preserve):
            if not a.no_reset:
                rig.setc("*RST", slow=True)
                rig.w("*CLS")
            if a.test == "all":
                run_all(rig, a, outdir, log)
            else:
                run(rig, a, outdir, log)
            rig.cleanup()
    finally:
        if rig.rejected:
            log(f"\n# {len(rig.rejected)} command(s) rejected by the UPL:")
            for c, e in rig.rejected:
                log(f"#   {c}  [{e}]")
        u.close()
    log(f"\n# done -> {outdir}")


def run_all(rig, a, outdir, log):
    """`all` with per-test levels: fr at -10 dBFS, fft at -1, imd at -3."""
    ctx = {}
    per_test_level = {"fr": -10.0, "fft": -1.0, "images": -1.0, "imd": -3.0}
    for name, which in ALL_PLAN:
        fn, header = TESTS[name]
        rates = a.fs
        if which == "first":
            rates = a.fs[:1]
        elif which == "base":
            rates = [f for f in a.fs if f <= BRM_MAX] or a.fs[:1]
        elif which == "48k":
            rates = [48000] if 48000 in a.fs else a.fs[:1]
        a.level = per_test_level.get(name, a.level)
        rows = []
        for fs in rates:
            log(f"\n=== {name} @ {fs} Hz ===")
            rows += fn(rig, a, fs, ctx)
        write_csv(os.path.join(outdir, f"{name}.csv"), header, rows, log)


if __name__ == "__main__":
    main()
