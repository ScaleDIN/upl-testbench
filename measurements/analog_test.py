#!/usr/bin/env python3
"""
analog_test.py - characterize an analog DUT (a preamp, phono stage, line stage, mic
pre, buffer...) with the UPL: analog generator in, analog analyzer out.

  UPL generator (XLR BAL, or BNC UNBAL with --unbal)  ->  DUT input (L, R)
  DUT output (L, R)                                   ->  UPL analyzer inputs 1, 2

The DAC suite's sibling (measurements/dac_test.py): same rig, report and conventions,
but every level is in volts at the DUT's *input* (the generator's EMF) instead of
dBFS, and the tests are the ones that matter for an analog stage: gain, bandwidth,
noise referred to the input, clipping, and input/output impedance.

Needs only a base UPL with UPL-B4 (remote). Sines come from the standard (universal)
generator, 2 Hz-21.75 kHz; its residual THD+N is about -103 dB in loopback (22 kHz),
far below almost any preamp. If *OPT? lists UPL-B1 (low-distortion generator) it is
used for the sines automatically: ~3-4 dB lower THD+N floor, THD ~-122 dB, and the
only way to reach 21.75-110 kHz (`fr --wide`). --no-lowd forces the universal one.
Without B1, `fr --wide` stops at 21.75 kHz and says so.

SAFETY: NOTHING but the UPL on the DUT's outputs -- no power amp, no headphones.
`thdn` drives the input up to --vmax (default 8 V) on purpose, until the DUT clips.
Lower --vmax for a phono stage or anything with a fragile input.

Tests (subcommands), in the order worth running them:
  setlevel   guided, for a DUT with a volume knob: plays --vin at 1 kHz and shows
             output volts, gain and THD live while you turn it, toward --target V
             (or --gain dB). --set-level runs it before any test
  check      gain and L/R balance at 1 kHz, DC offset at the output (input idle),
             absolute polarity per channel
  fr         frequency response, broadband *and* selective RMS (hum/noise pollution
             shows as a difference), -3 dB points, L-R; --wide to 100 kHz on the
             110 kHz analyzer (needs UPL-B1); --riaa: deviation from RIAA playback
  thdn       THD+N and THD vs frequency at --vin; then vs input level, stepping up in
             2 dB steps past --vin until THD+N passes 1 % (or --vmax): output and
             input level at 0.1 % and 1 % THD+N = maximum output / input overload
  noise      input terminated by the generator (muted, --zgen): output noise 22 kHz
             unweighted, A-weighted, CCIR-2k (ARM) and 110 kHz; S/N re --ref-out;
             EIN (noise referred to the input); hum spectrum of the idle output
  fft        spectrum of a 1 kHz tone at --vin: harmonic signature and hum
  imd        SMPTE 60 Hz + 7 kHz 4:1, and CCIF 19 + 20 kHz (DFD), at --vin; then SMPTE
             with the upper tone at 2/4/7/12 kHz: dB/octave says whether the IMD is
             frequency-dependent (feedback/slew), static, or an LF mechanism
  imdlevel   SMPTE and CCIF vs input level, --vin -40 dB up to +10 dB (<= --vmax)
  xtalk      crosstalk L->R and R->L, selective, 100 Hz-20 kHz
  zout       output impedance (200 kOhm vs 600 Ohm analyzer load)
  zin        input impedance, 1 kHz and 20 kHz (generator source 10 vs 600 Ohm; BAL only)
  multitone  17-tone multisine, products between the tones
  all        everything above except setlevel
 DUT control (--dut; in `all` when a DUT is given, unless --dut-asis):
  gainlaw    the DUT's own gain setting stepped (default -15..+15 dB): measured vs set
  xover      crossover filters: each --types at each --freqs, high- or low-pass (--side),
             native sweep; -3/-6 dB points and stopband slope (dB/octave) per curve
  limiter    output vs input with the DUT's limiter on (--thresh): where it starts
 Guided, never part of `all` (they need hands on the DUT):
  tracking   volume-control tracking: set the knob, press Enter, repeat -- gain and
             L-R balance per setting, selective (so the low end isn't noise)
  cmrr       common-mode rejection of a balanced input: measures differential gain,
             then asks you to feed BNC UNBAL into XLR pins 2+3 joined

Usage:
  python measurements/analog_test.py --dry-run all                 # offline, prints SCPI
  python measurements/analog_test.py --port COM2 check
  python measurements/analog_test.py --port COM2 --vin 0.5 --label mypre all
  python measurements/analog_test.py --port COM2 --vin 0.5 --set-level --target 2 all
  python measurements/analog_test.py --port COM2 --vin 0.005 --vmax 0.2 fr --riaa   # MM phono
  python measurements/analog_test.py --port COM2 --unbal --vin 0.5 all             # RCA inputs
  # Behringer DCX2496, one output patched: gen -> input A, output 1 -> analyzer CH1
  python measurements/analog_test.py --port COM7 --vin 1 --dut dcx --dut-port COM2 all
  python measurements/analog_test.py --port COM7 --vin 1 --dut dcx xover \
      --types but12,but24,bes24,lr24,but48 --freqs 500
  python measurements/analog_test.py --port COM7 --vin 1 --dut dcx --dut-asis fr  # as set up

--mono: a one-channel DUT (or only one output patched): only analyzer CH1 is reported
(CH2 is still measured, so the UPL setup stays identical, but shown as n/a); xtalk skipped.

--dut dcx (dcx2496.py over --dut-port, 38400 baud): the output(s) in --dut-out are set flat
at the start -- unmuted, EQ off, crossover off, limiter off, gain 0 dB -- and left flat
at the end. The DCX can't be read back, so its own settings are NOT restored; --dut-asis
measures it exactly as it is (no writes; the DUT-control tests are then skipped). One
output (the default, out1) implies --mono; --dut-out out1,out2 sends out1 to analyzer
CH1 and out2 to CH2. This replaces dcx_thdn.py, dcx_thd_vs_thdn.py, dcx_gauntlet.py and
dcx_sweep.py (live-run 2026-09-23, recoverable from git); their results are in CLAUDE.md.

Output: results/analog/<label>_<timestamp>/ -- report.html, one CSV per test,
summary.txt.

NOT YET RUN ON THE INSTRUMENT (written 2026-09-25). The generator side is new ground:
the DAC suite always drove S/PDIF. Live-proven elsewhere in this project: INST A25 +
SIN (universal generator), SOUR:LOWD ON/OFF, OUTP:TYPE BAL, INP:TYPE BAL, the analyzer set-up, the native
sweep (loopback, LOWD OFF), SOUR:VOLT 1e-20 V as "mute" (R&S selftest), filter
routing, POL, MDIS/DFD on the digital generator. From Vol.2 only: OUTP:IMP R10/R600,
OUTP:TYPE UNB, OUTP:SEL CH1/CH2 on the analog generator, MDIS/DFD/MULT on the analog
generator, SENS:FILT1:CARM, the native sweep with the B1 generator (10 Hz-110 kHz).
Every config command is followed by SYST:ERR?; rejections are printed and listed in
the report. Run `check` first.
"""
import argparse
import math
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import dac_test as dac  # noqa: E402  (the rig, the parsing and the report helpers)
from dac_test import db, fmt, parse, ratio_db, geomspace, Log, _f, _dbv, _groups, _lr, L_COL, R_COL  # noqa: E402
from upl_capture import connect, DryRunUPL, preserve_state, go_local  # noqa: E402
from report import Run, add_output_args  # noqa: E402

MUTE_V = 1e-20          # R&S selftest's "mute": generator on, terminating the input, no signal
F_REF = 1000.0
STD_GEN_MAX = 21750.0   # universal generator; the B1 low-distortion generator goes 10 Hz-110 kHz
LOWD_RANGE = (10.0, 110000.0)
DBU = 0.7746


def dbu(v):
    return db(v, DBU)


def interp_cross(pts, thr):
    """Upward crossing of `thr` by y along [(x, y), ...] (x in V, log-interpolated),
    searched from the THD+N minimum upward: below it, THD+N is noise, not clipping."""
    ok = [(x, y) for x, y in pts if y is not None]
    if not ok:
        return None
    i = min(range(len(ok)), key=lambda k: ok[k][1])
    prev = None
    for x, y in ok[i:]:
        if y is None:
            continue
        if y >= thr:
            if prev is None:
                return x
            (x0, y0) = prev
            t = (thr - y0) / (y - y0) if y != y0 else 0.0
            return x0 * (x / x0) ** t
        prev = (x, y)
    return None


def riaa_db(f, iec=False):
    """RIAA playback response (3180/318/75 us), dB re 1 kHz; iec adds the 7950 us
    IEC rumble pole (IEC 60098 amendment)."""
    def h(f):
        w = 2 * math.pi * f
        num = complex(1, w * 318e-6)
        den = complex(1, w * 3180e-6) * complex(1, w * 75e-6)
        g = num / den
        if iec:
            g *= complex(0, w * 7950e-6) / complex(1, w * 7950e-6)
        return 20 * math.log10(abs(g))
    return h(f) - h(1000.0)


# ---------------------------------------------------------------- the rig

class AnalogSource:
    """The UPL's analog generator. Levels are volts rms (EMF), at the DUT input.
    Sine from the universal generator, or from the B1 low-distortion generator when
    fitted (args.lowd, set from *OPT?). Twin-tone, multitone and polarity signals always
    come from the universal generator. Without B1, no SOUR:LOWD command is ever sent."""
    name = "analog"
    tracks = True
    CH_SEL = {"both": "CH2Is1", "L": "CH1", "R": "CH2"}

    def __init__(self, rig):
        self.rig = rig
        self.ch = "both"
        self.lowd = False
        self.twin_cur = None
        self.unsupported = {}

    def configure(self, analyzer):
        r, a = self.rig, self.rig.args
        r.setc("INST A25", slow=True)
        r.setc(f"INST2 {analyzer}", slow=True)
        r.setc(f"OUTP:TYPE {'UNB' if a.unbal else 'BAL'}")
        if not a.unbal:
            r.setc(f"OUTP:IMP {a.zgen}")
        r.setc("OUTP:SEL CH2Is1")
        self.ch = "both"
        r.setc("SOUR:FUNC SIN", slow=True)
        self.set_lowd(a.lowd)
        self.twin_cur = None

    def set_lowd(self, on):
        if on != self.lowd:
            self.rig.setc(f"SOUR:LOWD {'ON' if on else 'OFF'}", slow=True)
            self.lowd = on

    def clamp(self, v):
        vmax = self.rig.args.vmax
        if v > vmax:
            self.rig.log(f"   ! {v:.4g} V asked, limited to --vmax {vmax:g} V")
            return vmax
        return v

    def tone(self, f, v, ch="both"):
        r = self.rig
        if ch != self.ch:
            r.setc(f"OUTP:SEL {self.CH_SEL[ch]}")
            self.ch = ch
        if self.lowd and not LOWD_RANGE[0] <= f <= LOWD_RANGE[1]:
            f = min(max(f, LOWD_RANGE[0]), LOWD_RANGE[1])
        r.setc(f"SOUR:FREQ {f:.4f} HZ", quiet=True)
        r.setc(f"SOUR:VOLT {self.clamp(v):.6g} V", quiet=True)
        return f

    def silence(self):
        self.rig.setc(f"SOUR:VOLT {MUTE_V:g} V", quiet=True)

    def twin(self, kind, v):
        r = self.rig
        if kind != self.twin_cur:
            self.set_lowd(False)                 # B1 is a sine generator only
            setup = (("SOUR:FUNC MDIS", "SOUR:FREQ 7000 HZ", "SOUR:FREQ2 60 HZ", "SOUR:VOLT:RAT 4")
                     if kind == "SMPTE" else
                     ("SOUR:FUNC DFD", "SOUR:FREQ:DIFF 1000 HZ", "SOUR:FREQ:MEAN 19500 HZ"))
            for c in setup:
                r.setc(c, slow=c.startswith("SOUR:FUNC"))
            self.twin_cur = kind
        r.setc(f"SOUR:VOLT:TOT {self.clamp(v):.6g} V", quiet=True)

    def multitone(self, tones, v):
        r = self.rig
        self.set_lowd(False)
        r.setc("SOUR:FUNC MULT", slow=True)
        r.setc("SOUR:MULT:MODE EQU")
        r.setc(f"SOUR:MULT:COUN {len(tones)}")
        r.setc("SOUR:RAND:SPAC:MODE ATR")      # tones snapped to FFT bins
        r.setc("SOUR:VOLT:CRES:MODE MIN", slow=True)
        for i, f in enumerate(tones, 1):
            r.setc(f"SOUR:FREQ{i} {f:.2f} HZ", quiet=True)
        target = self.clamp(v)
        amp = target / len(tones)
        for _ in range(3):                     # scale the per-tone level to the total
            r.setc(f"SOUR:VOLT1 {amp:.6g} V", quiet=True)
            tot = parse(r.q("SOUR:VOLT:TOT?"))[0]
            if not tot or tot <= 0:
                break
            amp = amp * target / tot
        self.twin_cur = None
        return tones

    def sine(self):
        self.rig.setc("SOUR:FUNC SIN", slow=True)
        self.set_lowd(self.rig.args.lowd)
        self.twin_cur = None

    def cleanup(self):
        self.rig.log("\n-- cleanup: generator muted, both channels, sine")
        self.sine()
        for c in (f"SOUR:VOLT {MUTE_V:g} V", "OUTP:SEL CH2Is1"):
            self.rig.setc(c, quiet=True)
        if not self.rig.args.unbal:
            self.rig.setc(f"OUTP:IMP {self.rig.args.zgen}", quiet=True)


class AnalogRig(dac.Rig):
    """dac_test's Rig (error-checked writes, function switching, native sweep,
    selective RMS, FFT paging) with the analog generator as its source. Every
    `level` argument the inherited methods pass on is volts, not dBFS."""

    def __init__(self, u, log, args):
        super().__init__(u, log, args, "upl")
        self.src = AnalogSource(self)

    def configure(self, analyzer="A22"):
        if self.state == analyzer:
            return
        a = self.args
        self.log(f"\n-- configure: analyzer={analyzer}, generator "
                 f"{'UNBAL (BNC)' if a.unbal else 'BAL (XLR) ' + a.zgen}, "
                 f"{'B1 low-distortion' if a.lowd else 'universal'} sine")
        self.w("*CLS")
        self.src.configure(analyzer)
        # analyzer -- nothing survives an INST2 change, so all of it every time
        self.setc("INP:TYPE BAL")
        self.setc("INP:SEL CH2Is1")          # BOTH is digital-only (-222)
        self.setc(f"INP:LOW {'GRO' if a.ground else 'FLO'}")
        self.setc("INP:IMP R200K")
        self.setc("SENS:VOLT:RANG:AUTO ON")
        self.setc("SENS2:FUNC 'OFF'")
        self.setc("SENS3:FUNC 'FREQ'")
        self.func_cur = None
        self.func("RMS")                     # SENS:FILT OFF is -200 under THD/RMSS/POL
        self.setc("SENS:FILT OFF")
        self.fixed_sel = False
        self.state = analyzer
        self.log(f"   INST? {self.q('INST?')!r}  INST2? {self.q('INST2?')!r}")

    def unlatch(self):
        """A clipping tone's THD+N can latch the A22 notch gain low (floor ~-110 ->
        ~-103 dB; see dac_test.Rig.unlatch). A native 31-point RMS sweep resets it.
        Run after the clipping sweep, so later THD+N readings are honest."""
        self.func("RMS")
        self.sweep(geomspace(20.0, 20000.0, 31), min(self.args.vin, 0.1))
        self.log("   THD+N floor reset: 31-point RMS sweep run (clipping may latch the notch gain)")

    def read12(self):
        (v1, u1), (v2, u2) = super().read12()
        return (v1, u1), ((None, u2) if self.args.mono else (v2, u2))

    def sweep(self, freqs, level):
        out = super().sweep(freqs, level)
        return [(f, c1, (None, c2[1])) for f, c1, c2 in out] if self.args.mono else out

    def spec(self, key, fs=None):
        d = self.args.spec
        if d and key in d:
            self.log(f"   spec: {d[key]}")

    def settle(self, extra=0.0):
        time.sleep(self.args.settle + extra)


# ---------------------------------------------------------------- DUT control

class DcxDut:
    """Behringer DCX2496 through dcx2496.py. Write-only protocol: nothing can be read
    back, so "restore" means "leave flat"."""
    FLAT = "unmuted, EQ off, crossover off, limiter off, gain 0 dB"

    def __init__(self, port, outs, dcx=None):
        if dcx is None:
            from dcx2496 import DCX2496
            dcx = DCX2496(port)
        self.d, self.outs, self.port = dcx, outs, port
        self.touched = False
        self.d.enable_remote()

    def describe(self):
        return (f"Behringer DCX2496 on {self.port}, " + ", ".join(
            f"{o} -> analyzer CH{i + 1}" for i, o in enumerate(self.outs)))

    def flat(self):
        for o in self.outs:
            self.d.set_mute(o, False)
            self.d.set_eq_switch(o, False)
            self.d.set_crossover(o, hp_type="off", lp_type="off")
            self.d.set_limiter(o, enable=False)
            self.d.set_gain(o, 0.0)
        time.sleep(0.3)

    def set_gain(self, db_):
        self.touched = True
        for o in self.outs:
            self.d.set_gain(o, db_)
        time.sleep(0.3)

    def set_crossover(self, **kw):
        self.touched = True
        for o in self.outs:
            self.d.set_crossover(o, **kw)
        time.sleep(0.3)

    def set_limiter(self, enable, thresh_db=None):
        self.touched = True
        for o in self.outs:
            self.d.set_limiter(o, enable=enable, thresh_db=thresh_db,
                               release_ms=100 if enable else None)
        time.sleep(0.3)

    def restore(self):
        if not self.touched:
            return ""
        self.flat()
        return f"outputs {', '.join(self.outs)} left flat ({self.FLAT})"

    def close(self):
        self.d.close()


class _DryDcx:
    """Stands in for dcx2496.DCX2496 in --dry-run: prints each call."""
    def __getattr__(self, name):
        def call(*args, **kw):
            print(f"  [dcx] {name}{args}{kw if kw else ''}")
        return call


DUTS = {"dcx": DcxDut}


def need_dut(rig, method):
    """None if the DUT can do `method`, else why the test is skipped."""
    a = rig.args
    if rig.dut is None:
        return "needs --dut (a DUT this script can set)"
    if a.dut_asis:
        return "--dut-asis: no writes to the DUT"
    if not hasattr(rig.dut, method):
        return f"--dut {a.dut} has no {method}"
    return None


# ---------------------------------------------------------------- tests
# Each: t(rig, a, ctx) -> rows. ctx carries the gain from `check`/`setlevel`.

def measure_gain(rig, a, f=F_REF):
    rig.tone(f, a.vin)
    rig.settle()
    (v1, _), (v2, _) = rig.measure("RMS")
    return v1, v2


def t_setlevel(rig, a, ctx):
    """Guided: plays --vin at 1 kHz and shows output V, gain and THD about once a
    second while the knob is turned, until Enter. THD, not THD+N (clipping latch)."""
    log = rig.log
    rig.configure("A22")
    target = a.target if a.target else (a.vin * 10 ** (a.gain / 20) if a.gain is not None else None)
    log(f"   Plays 1 kHz at {a.vin:g} V into the DUT until you press Enter. NOTHING but the")
    log("   UPL on the outputs (no power amp, no headphones).")
    if target:
        log(f"   Turn the volume until both channels read {target:.4g} V "
            f"(gain {db(target, a.vin):+.1f} dB, within 0.1 dB).")
    else:
        log("   Turn the volume to the setting to test at; THD jumps if it clips.")
    if not a.dry_run:
        input("   Press Enter to start the tone... ")
    rig.tone(F_REF, a.vin)
    rig.settle()
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
        line = (f"   L {fmt(v1, '%.4f')} V ({fmt(db(v1, a.vin), '%+.2f')} dB)  "
                f"R {fmt(v2, '%.4f')} V ({fmt(db(v2, a.vin), '%+.2f')} dB)   "
                f"THD L {fmt(t1, '%.1f')} R {fmt(t2, '%.1f')} dB")
        if target and v1 and v2:
            off = db(math.sqrt(v1 * v2), target)
            line += f"   {off:+.2f} dB vs target -> " + (
                "OK" if abs(off) <= 0.1 else "turn DOWN" if off > 0 else "turn UP")
        if worst is not None and best is not None and worst > best + dac.CLIP_JUMP_DB:
            line += "   <- CLIPPING? back off"
        print(line, flush=True)
        last = (v1, v2, t1, t2)
    setting = ""
    if done.is_set():
        setting = input("   What does the volume read? (for the report; Enter to skip) ").strip()
    rig.level_setting = setting
    if last is None:
        return []
    v1, v2, t1, t2 = last
    ctx["out"] = (v1, v2)
    log(f"   level set: {a.vin:g} V in -> L {fmt(v1, '%.4f')} V  R {fmt(v2, '%.4f')} V, "
        f"gain L {fmt(db(v1, a.vin), '%+.2f')} R {fmt(db(v2, a.vin), '%+.2f')} dB"
        + (f", volume '{setting}'" if setting else ""))
    return [(a.vin, target or "", setting, v1, v2, db(v1, a.vin), db(v2, a.vin), t1, t2)]


def t_check(rig, a, ctx):
    log = rig.log
    rig.configure("A22")
    v1, v2 = measure_gain(rig, a)
    ok, fm = rig.locked(F_REF, max(v1 or 0, v2 or 0), vmin=1e-4)
    g1, g2 = db(v1, a.vin), db(v2, a.vin)
    bal = db(v1, v2) if v1 and v2 else None
    log(f"   signal: {'OK' if ok else 'NONE -- check cables, DUT power, input selector, volume'}"
        f"   measured freq {fmt(fm, '%.2f')} Hz")
    log(f"   {a.vin:g} V in ({fmt(dbu(a.vin), '%+.1f')} dBu) -> L {fmt(v1, '%.4f')} V  "
        f"R {fmt(v2, '%.4f')} V")
    log(f"   gain: L {fmt(g1, '%+.2f')} dB  R {fmt(g2, '%+.2f')} dB   L-R {fmt(bal, '%+.3f')} dB")
    rig.spec("gain")
    ctx["out"] = (v1, v2)
    # DC at the output, input idle (what a power amp downstream would see)
    rig.src.silence()
    rig.settle(0.5)
    (d1, _), (d2, _) = rig.measure("DC")
    log(f"   DC offset (input idle): L {fmt(d1, '%+.4f')} V  R {fmt(d2, '%+.4f')} V"
        + ("   <- > 10 mV: check before connecting a power amp"
           if any(d is not None and abs(d) > 0.01 for d in (d1, d2)) else ""))
    rig.spec("dc")
    # absolute polarity (universal generator's POLARITY signal)
    rig.src.set_lowd(False)
    rig.setc("SOUR:FUNC POL", slow=True)
    rig.setc(f"SOUR:VOLT {rig.src.clamp(a.vin):.6g} V", quiet=True)
    rig.settle()
    rig.func("POL")

    def pol(reply):
        # '1 ...' = "+1 POL" (not inverted), '-1 ...' = inverted (live, dac_test 2026-09-25)
        v, _ = parse(reply)
        return None if v is None else ("normal" if v > 0 else "INVERTED")
    r1 = r2 = ""
    for _ in range(3):                            # first read can be the sentinel
        rig.trig()
        r1, r2 = rig.q("SENS:DATA?"), rig.q("SENS:DATA2?")
        if pol(r1) and pol(r2):
            break
    if a.mono:
        r2 = ""
    log(f"   polarity: L {pol(r1) or 'no result'}  R {pol(r2) or 'no result'}   (raw {r1!r}, {r2!r})")
    rig.src.sine()
    rig.func("RMS")
    return [(a.vin, ok, fm, v1, v2, g1, g2, bal, d1, d2, pol(r1) or r1, pol(r2) or r2)]


A100_SEL_MIN = dac.A100_SEL_MIN


def t_fr(rig, a, ctx):
    log = rig.log
    top = 100000.0 if a.wide else 20000.0
    if a.wide and not a.lowd:
        log(f"   --wide: above {STD_GEN_MAX / 1000:g} kHz needs the UPL-B1 low-distortion generator "
            f"(not fitted or --no-lowd); stopping at {STD_GEN_MAX / 1000:g} kHz")
        top = STD_GEN_MAX
    stop = a.stop or top
    start = max(a.start, LOWD_RANGE[0]) if a.lowd else a.start
    analyzer = "A100" if stop > 21000 else "A22"
    rig.configure(analyzer)
    rig.aperture_follow()
    freqs = geomspace(start, stop, a.points)
    rows, data = [], {}
    for p in range(a.repeat):
        for mode in ("RMS", "RMSS"):
            if mode == "RMSS":
                rig.selective("PTOC")             # 1/3-octave bandpass that follows the tone
            else:
                rig.func(mode)
            rig.tone(F_REF, a.vin)
            rig.settle()
            rig.trig()
            (r1, _), (r2, _) = rig.read12()
            skip = [f for f in freqs if mode == "RMSS" and analyzer == "A100" and f < A100_SEL_MIN]
            todo = [f for f in freqs if f not in skip]
            meas = dict(zip(todo, rig.sweep(todo, a.vin)))
            for f in freqs:
                if f in skip:
                    data[(p, mode, f)] = (None, None, None)
                    rows.append((analyzer, p + 1, mode, round(f, 2), None, None, "", "", "", ""))
                    continue
                fa, (v1, _), (v2, _) = meas[f]
                d1, d2 = db(v1, r1), db(v2, r2)
                lr = db(v1, v2) if v1 and v2 else None
                data[(p, mode, f)] = (d1, d2, lr)
                ref = riaa_db(fa, a.riaa_iec) if a.riaa else None
                rows.append((analyzer, p + 1, mode, round(fa, 2), v1, v2,
                             fmt(d1, "%.3f", ""), fmt(d2, "%.3f", ""), fmt(lr, "%.3f", ""),
                             fmt(ref, "%.3f", "")))
            log(f"   pass {p+1} {mode:<4s} done  (1 kHz: L {fmt(r1, '%.4g')} V, R {fmt(r2, '%.4g')} V; "
                f"gain L {fmt(db(r1, a.vin), '%+.2f')} R {fmt(db(r2, a.vin), '%+.2f')} dB)")

    log(f"   --- FR, {analyzer}, {a.vin:g} V in, {start:.0f}-{stop:.0f} Hz")
    sel = "RMSS" if any(data[(0, "RMSS", f)][0] is not None for f in freqs) else "RMS"
    for ch, name in ((0, "L"), (1, "R")):
        pts = [(f, data[(0, sel, f)][ch]) for f in freqs if data[(0, sel, f)][ch] is not None]
        if not pts:
            continue
        if a.riaa:
            dev = [(f, d - riaa_db(f, a.riaa_iec)) for f, d in pts]
            band = [x for x in dev if 20 <= x[0] <= 20000]
            w = max(band, key=lambda x: abs(x[1])) if band else (None, None)
            log(f"   {name}: RIAA{' (IEC)' if a.riaa_iec else ''} deviation 20 Hz-20 kHz: "
                f"{fmt(min(d for _, d in band) if band else None, '%+.2f')} to "
                f"{fmt(max(d for _, d in band) if band else None, '%+.2f')} dB "
                f"(worst {fmt(w[1], '%+.2f')} dB at {fmt(w[0], '%.0f')} Hz)")
            continue
        band = [d for f, d in pts if 20 <= f <= 20000]
        lo = next((f for f, d in pts if d >= -3), None)        # first freq above -3 dB
        hi = next((f for f, d in reversed(pts) if d >= -3), None)
        log(f"   {name}: 20 Hz-20 kHz {fmt(min(band) if band else None, '%+.2f')} / "
            f"{fmt(max(band) if band else None, '%+.2f')} dB;  "
            f"-3 dB points {'below ' if lo == pts[0][0] else ''}{fmt(lo, '%.1f')} Hz ... "
            f"{'above ' if hi == pts[-1][0] else ''}{fmt(hi, '%.0f')} Hz")
    lrs = [(abs(data[(0, sel, f)][2]), data[(0, sel, f)][2], f) for f in freqs
           if data[(0, sel, f)][2] is not None and 20 <= f <= 20000]
    if lrs:
        _, v, f = max(lrs)
        log(f"   L-R: worst {v:+.3f} dB at {f:.0f} Hz (20 Hz-20 kHz)")
    for ch, name in ((0, "L"), (1, "R")):
        diffs = [(data[(0, "RMS", f)][ch] - data[(0, "RMSS", f)][ch], f) for f in freqs
                 if None not in (data[(0, "RMS", f)][ch], data[(0, "RMSS", f)][ch])]
        if diffs:
            d, f = max(diffs, key=lambda x: abs(x[0]))
            log(f"   {name}: broadband - selective: worst {d:+.2f} dB at {f:.0f} Hz"
                + ("   <- hum/noise/oscillation inflating broadband RMS" if abs(d) > 0.3 else ""))
    if a.repeat > 1:
        spread = max((max(v) - min(v) for f in freqs for ch in (0, 1)
                      for v in [[data[(p, sel, f)][ch] for p in range(a.repeat)
                                 if data[(p, sel, f)][ch] is not None]] if len(v) > 1), default=0.0)
        log(f"   repeatability: max spread {spread:.3f} dB over {a.repeat} passes"
            + ("   <- not repeatable" if spread > 0.1 else ""))
    rig.spec("fr")
    return rows


def level_steps(a):
    """Input levels (V): --vin -60 ... 0 dB, then +2 dB steps up to --vmax."""
    rel = [-60, -50, -40, -30, -20, -10, -6, -3, 0]
    x = 2
    while a.vin * 10 ** (x / 20) <= a.vmax * 1.0001:
        rel.append(x)
        x += 2
    out = [a.vin * 10 ** (r / 20) for r in rel]
    if out[-1] < a.vmax * 0.999 and out[-1] * 10 ** (2 / 20) > a.vmax:
        out.append(a.vmax)
    return out


def t_thdn(rig, a, ctx):
    log = rig.log
    rows = []
    for analyzer in a.analyzers:
        rig.configure(analyzer)
        # vs frequency at --vin, THD+N then THD (native sweep)
        fstop = 20000.0
        for fn in ("THDN", "THD"):
            rig.func(fn)
            for fa, (v1, u1), (v2, u2) in rig.sweep(geomspace(20, fstop, 16), a.vin):
                rows.append((analyzer, "freq", round(fa, 1), fn, "", "", ratio_db(v1, u1), ratio_db(v2, u2)))
        at_vin = [r for r in rows if r[0] == analyzer and r[1] == "freq" and r[3] == "THDN"]
        for ch, name in ((6, "L"), (7, "R")):
            v = [(r[ch], r[2]) for r in at_vin if r[ch] is not None]
            if v:
                log(f"   {analyzer} {name}: THD+N vs frequency at {a.vin:g} V: "
                    f"{min(v)[0]:.1f} dB (at {min(v)[1]:.0f} Hz) to {max(v)[0]:.1f} dB (at {max(v)[1]:.0f} Hz)")
    # vs input level at 1 kHz on A22, up to clipping
    rig.configure("A22")
    steps = level_steps(a)
    log(f"   level sweep at 1 kHz: {steps[0]:.3g} V to at most {steps[-1]:.3g} V, "
        f"stopping once THD+N rises past 1 % (-40 dB) on either channel")
    pts = []
    for vin in steps:
        rig.tone(F_REF, vin)
        rig.settle()
        (o1, _), (o2, _) = rig.measure("RMS")
        (n1, nu1), (n2, nu2) = rig.measure("THDN")
        n1, n2 = ratio_db(n1, nu1), ratio_db(n2, nu2)
        pts.append((vin, o1, o2, n1, n2))
        rows.append(("A22", "level", round(vin, 6), "THDN", o1, o2, n1, n2))
        log(f"     {vin:9.4g} V in ({fmt(dbu(vin), '%+6.1f')} dBu): out L {fmt(o1, '%.4g')} V "
            f"R {fmt(o2, '%.4g')} V   THD+N L {fmt(n1, '%.1f')} R {fmt(n2, '%.1f')} dB")
        # clipping = past 1 % AND rising from the best seen; at the bottom of the
        # sweep THD+N is just noise and can be far above 1 % on a phono stage
        best = [min(v for v in (p_[3 + c] for p_ in pts) if v is not None)
                if any(p_[3 + c] is not None for p_ in pts) else None for c in (0, 1)]
        if any(n is not None and b is not None and n > -40 and n > b + 10
               for n, b in ((n1, best[0]), (n2, best[1]))):
            break
    rig.src.silence()
    rig.func("THD")                             # THD at the same points (unaffected by the latch)
    for vin, *_ in pts:
        rig.tone(F_REF, vin)
        rig.settle()
        rig.trig()
        (h1, hu1), (h2, hu2) = rig.read12()
        rows.append(("A22", "level", round(vin, 6), "THD", "", "", ratio_db(h1, hu1), ratio_db(h2, hu2)))
    rig.src.silence()
    rig.unlatch()
    for ch, name in ((0, "L"), (1, "R")):
        curve = [(p[0], p[3 + ch]) for p in pts]
        outs = {p[0]: p[1 + ch] for p in pts}
        best = min(((n, v) for v, n in curve if n is not None), default=None)
        msg = f"   {name}: best THD+N {fmt(best and best[0], '%.1f')} dB at {fmt(best and best[1], '%.3g')} V in"
        for pct, thr in (("0.1 %", -60.0), ("1 %", -40.0)):
            x = interp_cross(curve, thr)
            if x is None:
                msg += f"; {pct} not reached"
                continue
            near = min(outs, key=lambda v: abs(math.log(v / x)))
            gain = outs[near] / near if outs[near] else None
            vo = x * gain if gain else None
            msg += (f"; {pct} at {x:.3g} V in ({fmt(dbu(x), '%+.1f')} dBu)"
                    f" = {fmt(vo, '%.3g')} V out ({fmt(dbu(vo), '%+.1f')} dBu)")
        log(msg)
    log("   (1 % THD+N output = maximum output; its input = input overload at this volume "
        "setting. With a volume control ahead of the active stage, turn it down to find "
        "the input stage's own overload.)")
    rig.spec("thdn")
    rig.spec("maxout")
    return rows


def t_noise(rig, a, ctx):
    """Output noise with the input terminated by the muted generator (--zgen)."""
    log = rig.log
    rig.configure("A22")
    g = ctx.get("out")
    if not g or None in g:
        g = measure_gain(rig, a)
    gain = [v / a.vin if v else None for v in g]
    ref = [a.ref_out] * 2 if a.ref_out else list(g)
    rig.src.silence()
    rig.settle(1.0)
    rows = []
    res = {}
    for analyzer, weight, filt in (("A22", "22k", None), ("A22", "A", "AWE"), ("A22", "CCIR-2k ARM", "CARM"),
                                   ("A100", "110k", None)):
        rig.configure(analyzer)
        rig.src.silence()
        rig.func("RMS")
        if filt:
            rig.setc(f"SENS:FILT1:{filt} ON")     # after the function: a function change drops it
        rig.settle(0.5)
        (n1, _), (n2, _) = rig.measure("RMS")
        if filt:
            rig.setc("SENS:FILT OFF")
        res[weight] = (n1, n2)
        for n, gg, rf, ch in ((n1, gain[0], ref[0], "L"), (n2, gain[1], ref[1], "R")):
            ein = n / gg if n and gg else None
            rows.append((weight, ch, n, db(rf, n) if rf and n else None, ein, dbu(ein) if ein else None))
    rig.configure("A22")
    log(f"   gain used for EIN: L {fmt(db(gain[0], 1) if gain[0] else None, '%+.2f')} dB  "
        f"R {fmt(db(gain[1], 1) if gain[1] else None, '%+.2f')} dB;  S/N re "
        + (f"{a.ref_out:g} V out" if a.ref_out else f"the output at {a.vin:g} V in"))
    for weight, _ in res.items():
        r = [x for x in rows if x[0] == weight]
        log(f"   {weight:>12s}: noise L {fmt(r[0][2], '%.3g')} V  R {fmt(r[1][2], '%.3g')} V   "
            f"S/N L {fmt(r[0][3], '%.1f')} R {fmt(r[1][3], '%.1f')} dB   "
            f"EIN L {fmt(r[0][5], '%.1f')} R {fmt(r[1][5], '%.1f')} dBu")
    un = [x for x in rows if x[0] == "22k"]
    for x in un:
        if x[4]:
            log(f"   {x[1]}: EIN 22 kHz unweighted = {x[4] * 1e9 / math.sqrt(20000):.2f} nV/rtHz "
                f"(if white; a 1 kOhm resistor is 4.1)")
    log(f"   (the UPL's own A22 floor is ~1.5 uV; readings near it are the analyzer's)")
    rig.spec("snr")
    rig.spec("ein")
    # hum: spectrum of the idle output
    freqs, y = rig.run_fft(avg=a.fft_avg)
    if len(freqs) > 2:
        res_hz = freqs[1] - freqs[0]
        lines = []
        for m in (50, 60, 100, 120, 150, 180, 250, 300):
            v = dac.peak_near(freqs, y, m, max(2 * res_hz, 2.0))
            lines.append(f"{m} Hz {fmt(v * 1e6 if v else None, '%.2f')} uV")
            rows.append((f"hum_{m}Hz", "CH1", v, None, None, None))
        top = sorted(((v, f) for f, v in zip(freqs, y) if 20 <= f <= 20000), reverse=True)[:1]
        log("   hum (CH1 idle spectrum): " + ", ".join(lines))
        if top:
            log(f"   largest line 20 Hz-20 kHz: {top[0][0] * 1e6:.2f} uV at {top[0][1]:.1f} Hz")
        ctx["hum_fft"] = (freqs, y)
    return rows


def t_fft(rig, a, ctx):
    rig.configure(a.analyzer)
    rig.tone(F_REF, a.vin)
    rig.settle()
    freqs, y = rig.run_fft(avg=a.fft_avg)
    dac.analyze_spectrum(freqs, y, F_REF, 1e12, rig.log, f"FFT {a.analyzer}, {a.vin:g} V in")
    return [(a.analyzer, round(f, 3), v) for f, v in zip(freqs, y)]


def t_imd(rig, a, ctx):
    log = rig.log
    rig.configure("A22")
    rows = []
    for kind, fn, tag in (("SMPTE", "MDIS", "SMPTE_60_7k"), ("CCIF", "DFD", "CCIF_19_20k")):
        rig.src.twin(kind, a.vin)
        rig.settle()
        d, _ = settled_read(rig, fn)
        log(f"   {kind} ({a.vin:g} V total): L {fmt(d[0], '%.1f')} dB  R {fmt(d[1], '%.1f')} dB")
        rows.append((tag, a.vin, d[0], d[1]))
    rig.spec("imd")
    rows += smpte_carrier(rig, a)
    rig.src.sine()
    return rows


SMPTE_CARRIERS = (2000, 4000, 7000, 12000)
SETTLE_TOL_DB = 0.3


def settled_read(rig, fn, tol=SETTLE_TOL_DB, maxn=10):
    """Re-trigger until two readings in a row agree within tol dB on both channels.
    The DCX2496's SMPTE reading drifts ~2-3 dB better over the first ~30 s after the
    signal changes (live 2026-09-25; the UPL in loopback is steady to +-1 dB), so a
    single reading depends on how long the tone has been on. Returns ((L, R), n)."""
    rig.func(fn)
    prev = None
    for n in range(1, maxn + 1):
        rig.trig()
        (v1, u1), (v2, u2) = rig.read12()
        d = (ratio_db(v1, u1), ratio_db(v2, u2))
        if prev and all(x is None or y is None or abs(x - y) <= tol for x, y in zip(d, prev)):
            return d, n
        prev = d
        time.sleep(1.0)
    return d, maxn


def smpte_carrier(rig, a):
    """SMPTE with the upper tone moved (60 Hz + 2/4/7/12 kHz, 4:1, --vin total).
    Separates *where* an IMD comes from: rising with the carrier (~6 dB/oct =
    an error proportional to dV/dt, i.e. feedback running out with frequency or
    slew-type) versus flat (a static nonlinearity) versus falling with the carrier
    (an LF mechanism, e.g. a coupling capacitor). The DCX2496 rose ~5 dB/oct
    (2026-09-25); the UPL in loopback stays flat at ~-100 to -108 dB."""
    log = rig.log
    rig.src.twin("SMPTE", a.vin)
    rows, pts = [], []
    for hf in SMPTE_CARRIERS:
        rig.setc(f"SOUR:FREQ {hf} HZ", quiet=True)
        rig.settle()
        d, n = settled_read(rig, "MDIS")
        rows.append((f"SMPTE_60_{hf // 1000}k", a.vin, d[0], d[1]))
        pts.append((hf, d))
        if n > 2:
            log(f"   ({hf} Hz: {n} readings before two agreed within {SETTLE_TOL_DB} dB)")
    rig.setc("SOUR:FREQ 7000 HZ", quiet=True)          # twin()'s cached SMPTE set-up again
    msg = "   SMPTE vs carrier (60 Hz + f, {:g} V): ".format(a.vin) + ", ".join(
        f"{hf // 1000}k {fmt(d[0], '%.1f')}/{fmt(d[1], '%.1f')}" for hf, d in pts) + " dB"
    log(msg)
    for ch, name in ((0, "L"), (1, "R")):
        xy = [(math.log2(hf), d[ch]) for hf, d in pts if d[ch] is not None]
        if len(xy) >= 3:
            mx = sum(x for x, _ in xy) / len(xy)
            my = sum(y for _, y in xy) / len(xy)
            s = (sum((x - mx) * (y - my) for x, y in xy) / sum((x - mx) ** 2 for x, _ in xy))
            what = ("rises with the carrier: a frequency-dependent (feedback/slew-type) nonlinearity"
                    if s > 2 else "falls with the carrier: an LF mechanism (coupling cap, core, supply)"
                    if s < -2 else "flat: a static nonlinearity")
            log(f"   {name}: {s:+.1f} dB/octave of carrier -- {what}")
    return rows


def t_imd_level(rig, a, ctx):
    log = rig.log
    rig.configure("A22")
    rows = []
    levels = [a.vin * 10 ** (r / 20) for r in (-40, -30, -20, -10, -6, -3, 0, 3, 6, 10)]
    levels = [v for v in levels if v <= a.vmax * 1.0001]
    for kind, fn in (("SMPTE", "MDIS"), ("CCIF", "DFD")):
        rig.src.twin(kind, levels[0])
        rig.func(fn)
        res = []
        for v in levels:
            rig.src.twin(kind, v)
            rig.settle()
            rig.trig()
            (v1, u1), (v2, u2) = rig.read12()
            d = (ratio_db(v1, u1), ratio_db(v2, u2))
            rows.append((kind, round(v, 6), d[0], d[1]))
            res.append((v, d))
        best = min(((d[0], v) for v, d in res if d[0] is not None), default=(None, None))
        log(f"   {kind}: best {fmt(best[0], '%.1f')} dB at {fmt(best[1], '%.3g')} V in (L); "
            f"at {res[-1][0]:.3g} V {fmt(res[-1][1][0], '%.1f')} dB")
        rig.func_cur = None
    rig.src.sine()
    return rows


def t_xtalk(rig, a, ctx):
    log = rig.log
    if a.mono:
        log("   --mono: no second channel; skipped")
        return []
    rig.configure("A22")
    rig.selective("PTOC")
    log("   (the undriven input sees the switched-off generator channel -- if that leaves it")
    log("    open, crosstalk reads a little pessimistic; a shorting plug there is the textbook way)")
    rows = []
    for f in (100.0, 1000.0, 10000.0, 20000.0):
        res = []
        for ch in ("L", "R"):
            f = rig.tone(f, a.vin, ch)
            rig.settle(0.3)
            rig.trig()
            (v1, _), (v2, _) = rig.read12()
            res.append(db(v2, v1) if ch == "L" else db(v1, v2))
        rows.append((f, res[0], res[1]))
        log(f"   {f:7.0f} Hz: L->R {fmt(res[0], '%.1f')} dB   R->L {fmt(res[1], '%.1f')} dB")
    rig.tone(F_REF, a.vin)                         # back to both channels
    rig.spec("xtalk")
    return rows


def t_zout(rig, a, ctx):
    log = rig.log
    rig.configure("A22")
    rig.tone(F_REF, a.vin)
    vals = {}
    for imp in ("R200K", "R600"):
        rig.setc(f"INP:IMP {imp}")
        rig.settle(0.5)
        (v1, _), (v2, _) = rig.measure("RMS")
        vals[imp] = (v1, v2)
    rig.setc("INP:IMP R200K")
    rows = []
    for ch, name in ((0, "L"), (1, "R")):
        vh, vl = vals["R200K"][ch], vals["R600"][ch]
        z = 600.0 * (vh / vl - 1.0) if vh and vl else None
        log(f"   {name}: {fmt(vh, '%.4f')} V into 200 kOhm, {fmt(vl, '%.4f')} V into 600 Ohm -> "
            f"Zout ~ {fmt(z, '%.0f')} Ohm")
        rows.append((name, vh, vl, z))
    rig.spec("zout")
    return rows


def t_zin(rig, a, ctx):
    """Input impedance from the output level with the generator's source impedance
    at 10 and 600 Ohm: k = V10/V600 = (Zin + 600)/(Zin + 10), Zin = (600 - 10k)/(k - 1).
    Differential for a balanced input. Resolution falls as Zin rises: at 47 kOhm the
    two readings differ by only 0.11 dB, so treat > ~100 kOhm as 'high'."""
    log = rig.log
    if a.unbal:
        log("   zin needs the balanced generator output (source impedance is switchable only on"
            " XLR BAL): skipped. For an RCA input, run it with an XLR->RCA lead (pin 2 hot, pin 3"
            " to the RCA shell) and without --unbal.")
        return []
    rig.configure("A22")
    rows = []
    for f in (1000.0, 20000.0):
        vals = {}
        for imp in ("R10", "R600"):
            rig.setc(f"OUTP:IMP {imp}", slow=True)
            rig.tone(f, a.vin)
            rig.settle(0.5)
            (v1, _), (v2, _) = rig.measure("RMS")
            vals[imp] = (v1, v2)
        for ch, name in ((0, "L"), (1, "R")):
            v10, v600 = vals["R10"][ch], vals["R600"][ch]
            k = v10 / v600 if v10 and v600 else None
            z = (600 - 10 * k) / (k - 1) if k and k > 1.0002 else None
            log(f"   {f:6.0f} Hz {name}: {fmt(v10, '%.5f')} V (10 Ohm source) / {fmt(v600, '%.5f')} V "
                f"(600 Ohm) = {fmt(db(k, 1) if k else None, '%.3f')} dB -> Zin "
                + (f"~ {z / 1000:.1f} kOhm" if z else "too high to resolve (> ~1 MOhm)"))
            rows.append((f, name, v10, v600, z))
    rig.setc(f"OUTP:IMP {a.zgen}", slow=True)
    rig.tone(F_REF, a.vin)
    rig.spec("zin")
    return rows


def t_multitone(rig, a, ctx):
    log = rig.log
    rig.configure("A22")
    rig.func("FFT")
    rig.setc("CALC:TRAN:FREQ:FFT S8K")
    tones = rig.src.multitone(geomspace(20.0, 20000.0, 17), a.vin)
    rig.settle()
    freqs, y = rig.run_fft(avg=a.fft_avg)
    rows = [(round(f, 3), v) for f, v in zip(freqs, y)]
    if len(freqs) > 2:
        res = freqs[1] - freqs[0]
        found = [max(((v, fx) for fx, v in zip(freqs, y) if abs(fx - f) <= 3 * res), default=None)
                 for f in tones]
        found = [x for x in found if x]
        ref = max(v for v, _ in found) if found else None
        between = [(v, fx) for fx, v in zip(freqs, y) if 20 <= fx <= 20000
                   and all(abs(fx - t) > 4 * res for _, t in found)]
        if ref and between:
            wv, wf = max(between)
            med = sorted(v for v, _ in between)[len(between) // 2]
            log(f"   multitone ({a.vin:g} V total): worst product between tones "
                f"{fmt(db(wv, ref), '%.1f')} dBc at {wf:.0f} Hz; median floor {fmt(db(med, ref), '%.1f')} dBc")
    rig.src.sine()
    return rows


def t_tracking(rig, a, ctx):
    """Volume-control tracking, guided: gain and L-R at each knob setting, selective
    (1 % band at 1 kHz) so settings far down aren't read as noise."""
    log = rig.log
    rig.configure("A22")
    rig.selective("PPCT1")
    rig.tone(F_REF, a.vin)
    log(f"   1 kHz at {a.vin:g} V in. Set the volume, press Enter to record; repeat from")
    log("   loudest to quietest. Type a label first if you like (e.g. '12 o'clock'). q + Enter ends.")
    rows, n = [], 0
    while True:
        if a.dry_run:
            if n >= 3:
                break
            s = f"step {n + 1}"
        else:
            s = input("   volume setting (Enter = record, q = done): ").strip()
            if s.lower() == "q":
                break
        n += 1
        rig.settle(0.3)
        rig.trig()
        (v1, _), (v2, _) = rig.read12()
        g1, g2 = db(v1, a.vin), db(v2, a.vin)
        lr = db(v1, v2) if v1 and v2 else None
        rows.append((n, s or str(n), v1, v2, g1, g2, lr))
        log(f"   [{s or n}] gain L {fmt(g1, '%+.2f')} R {fmt(g2, '%+.2f')} dB   L-R {fmt(lr, '%+.2f')} dB"
            + ("   <- > 1 dB" if lr is not None and abs(lr) > 1 else ""))
    if rows:
        worst = max((r for r in rows if r[6] is not None), key=lambda r: abs(r[6]), default=None)
        if worst:
            log(f"   worst L-R {worst[6]:+.2f} dB at '{worst[1]}' (gain {fmt(worst[4], '%+.1f')} dB)")
    return rows


def t_cmrr(rig, a, ctx):
    """Common-mode rejection of a balanced input. Differential gain first, over the
    normal XLR lead; then the generator's BNC UNBAL output into the DUT's pins 2 AND 3
    joined (pin 1 to the BNC shell). CMRR = differential gain - common-mode gain."""
    log = rig.log
    if a.unbal:
        log("   cmrr: run without --unbal (the differential half uses the XLR output)")
        return []
    fr = (100.0, 1000.0, 10000.0)
    rig.configure("A22")
    rig.selective("PTOC")
    diff = {}
    for f in fr:
        rig.tone(f, a.vin)
        rig.settle(0.3)
        rig.trig()
        diff[f] = rig.read12()
    log("   differential gain: " + ", ".join(
        f"{f:.0f} Hz L {fmt(db(diff[f][0][0], a.vin), '%+.1f')} R {fmt(db(diff[f][1][0], a.vin), '%+.1f')} dB"
        for f in fr))
    rig.src.silence()
    log("   Now: UPL generator BNC (UNBAL) -> DUT input XLR with pins 2 AND 3 joined, pin 1 to the")
    log("   BNC shell. Both channels if you have two adapters, else one at a time (repeat the test).")
    if not a.dry_run:
        input("   Press Enter when connected... ")
    rig.setc("OUTP:TYPE UNB", slow=True)
    rig.selective("PTOC")
    rows = []
    for f in fr:
        rig.tone(f, a.vin)
        rig.settle(0.3)
        rig.trig()
        cm = rig.read12()
        for ch, name in ((0, "L"), (1, "R")):
            d, c = diff[f][ch][0], cm[ch][0]
            cmrr = db(d, c) if d and c else None
            rows.append((f, name, d, c, cmrr))
            log(f"   {f:6.0f} Hz {name}: common-mode out {fmt(c, '%.3g')} V -> CMRR {fmt(cmrr, '%.1f')} dB")
    rig.src.silence()
    rig.setc("OUTP:TYPE BAL", slow=True)
    rig.setc(f"OUTP:IMP {a.zgen}")
    log("   Put the normal XLR lead back.")
    rig.spec("cmrr")
    return rows


def t_gainlaw(rig, a, ctx):
    """The DUT's gain control, stepped: measured change vs set change (re the 0 dB
    setting, or the first), and the absolute gain. DCX2496, 2026-09-23: a constant
    +0.41 dB offset across -15..+15 dB at 1 V in, i.e. perfect tracking."""
    log = rig.log
    why = need_dut(rig, "set_gain")
    if why:
        log(f"   {why}; skipped")
        return []
    rig.configure("A22")
    rig.tone(F_REF, a.vin)
    rows, ref = [], None
    for g in a.gains:
        rig.dut.set_gain(g)
        rig.settle()
        (v1, _), (v2, _) = rig.measure("RMS")
        m = [db(v, a.vin) for v in (v1, v2)]
        if ref is None or g == 0:
            ref = (g, m)
        rows.append([g, v1, v2, m[0], m[1]])
    rig.dut.set_gain(0.0)
    g0, m0 = ref
    for r in rows:
        r += [None if (r[3 + i] is None or m0[i] is None) else (r[3 + i] - m0[i]) - (r[0] - g0)
              for i in (0, 1)]
        log(f"   set {r[0]:+6.1f} dB: gain L {fmt(r[3], '%+.2f')} R {fmt(r[4], '%+.2f')} dB   "
            f"tracking error L {fmt(r[5], '%+.3f')} R {fmt(r[6], '%+.3f')} dB")
    for i, name in ((5, "L"), (6, "R")):
        e = [r[i] for r in rows if r[i] is not None]
        if e:
            log(f"   {name}: tracking error {min(e):+.3f} to {max(e):+.3f} dB; "
                f"gain at the {g0:+g} dB setting {fmt(m0[i - 5], '%+.2f')} dB")
    return [tuple(r) for r in rows]


def _cross_freq(pts, thr, side):
    """Frequency where the response (dB re passband) first drops below `thr`, walking
    in from the passband: from the top for a high-pass, from the bottom for a low-pass."""
    seq = list(reversed(pts)) if side == "hp" else list(pts)
    prev = None
    for f, d in seq:
        if d is None:
            continue
        if d < thr and prev is not None:
            f0, d0 = prev
            t = (thr - d0) / (d - d0)
            return f0 * (f / f0) ** t
        prev = (f, d)
    return None


def _slope(pts, lo=-50.0, hi=-15.0):
    """Stopband slope, dB/octave: least squares over the points between lo and hi dB."""
    use = [(math.log2(f), d) for f, d in pts if d is not None and lo <= d <= hi]
    if len(use) < 2:
        return None
    mx = sum(x for x, _ in use) / len(use)
    my = sum(y for _, y in use) / len(use)
    sxx = sum((x - mx) ** 2 for x, _ in use)
    return abs(sum((x - mx) * (y - my) for x, y in use) / sxx) if sxx else None


def t_xover(rig, a, ctx):
    """Crossover filters: for each type at each cutoff, a native sweep fc/8..fc*8
    (10 Hz-20 kHz), normalized to the passband. Butterworth is -3 dB at fc,
    Linkwitz-Riley -6 dB, Bessel neither; the slope is n x 6 dB/octave for order n
    (LR24 measured 24.6 on the DCX, 2026-09-23)."""
    log = rig.log
    why = need_dut(rig, "set_crossover")
    if why:
        log(f"   {why}; skipped")
        return []
    rig.configure("A22")
    rig.func("RMS")
    rows = []
    for fc in a.freqs:
        fr = geomspace(max(10.0, fc / 8), min(20000.0, fc * 8), a.points)
        for ft in a.types:
            kw = ({"hp_freq": fc, "hp_type": ft, "lp_type": "off"} if a.side == "hp"
                  else {"lp_freq": fc, "lp_type": ft, "hp_type": "off"})
            rig.dut.set_crossover(**kw)
            meas = rig.sweep(fr, a.vin)
            res = []
            for ch in (0, 1):
                v = [m[1 + ch][0] for m in meas]
                top = max((x for x in v if x), default=None)
                res.append([db(x, top) if x and top else None for x in v])
            for (fa, (v1, _), (v2, _)), d1, d2 in zip(meas, res[0], res[1]):
                rows.append((a.side, ft, fc, round(fa, 2), v1, v2, d1, d2))
            msg = f"   {a.side.upper()} {ft:>6s} @ {fc:g} Hz:"
            for ch, name in ((0, "L"), (1, "R")):
                pts = [(m[0], d) for m, d in zip(meas, res[ch])]
                if all(d is None for _, d in pts):
                    continue
                f3, f6, sl = _cross_freq(pts, -3, a.side), _cross_freq(pts, -6, a.side), _slope(pts)
                msg += (f"  {name}: -3 dB {fmt(f3, '%.0f')} Hz, -6 dB {fmt(f6, '%.0f')} Hz, "
                        f"slope {fmt(sl, '%.1f')} dB/oct")
            log(msg)
    rig.dut.set_crossover(hp_type="off", lp_type="off")
    return rows


def t_limiter(rig, a, ctx):
    """Output vs input with the DUT's limiter on, 1 kHz: where the output stops
    following (1 dB below the small-signal gain). DCX2496 at -10 dB, 2026-09-23:
    a hard knee at ~3 V in, output pinned at ~3.06 V up to 7 V in."""
    log = rig.log
    why = need_dut(rig, "set_limiter")
    if why:
        log(f"   {why}; skipped")
        return []
    rig.configure("A22")
    rig.dut.set_limiter(True, a.thresh)
    rows = []
    try:
        for vin in geomspace(0.05, min(a.vmax, 7.0), 20):
            rig.tone(F_REF, vin)
            rig.settle(0.3)                         # the limiter's own release, 100 ms
            (v1, _), (v2, _) = rig.measure("RMS")
            rows.append((round(vin, 5), v1, v2, db(v1, vin), db(v2, vin)))
    finally:
        rig.src.silence()
        rig.dut.set_limiter(False)
    for i, name in ((3, "L"), (4, "R")):
        g = [(r[0], r[i], r[i - 2]) for r in rows if r[i] is not None]
        if not g:
            continue
        g0 = g[0][1]
        knee = None                                 # input where the gain is 1 dB down,
        for (x0, g_0, _), (x1, g_1, _) in zip(g, g[1:]):     # log-interpolated
            if g_1 < g0 - 1.0 <= g_0:
                t = (g0 - 1.0 - g_0) / (g_1 - g_0)
                x = x0 * (x1 / x0) ** t
                knee = (x, x * 10 ** ((g0 - 1.0) / 20))
                break
        top = max(vo for _, _, vo in g if vo)
        log(f"   {name}: small-signal gain {g0:+.2f} dB; "
            + (f"limiting from ~{knee[0]:.3g} V in ({knee[1]:.3g} V out); maximum {top:.3g} V out"
               if knee else f"no limiting up to {g[-1][0]:.3g} V in"))
    log(f"   (threshold {a.thresh:g} dB on the DUT's own scale)")
    return rows


TESTS = {
    "setlevel":  (t_setlevel, ["vin_V", "target_V", "volume_setting", "L_V", "R_V",
                               "gain_L_dB", "gain_R_dB", "THD_L_dB", "THD_R_dB"]),
    "check":     (t_check, ["vin_V", "signal", "meas_freq_Hz", "L_V", "R_V", "gain_L_dB",
                            "gain_R_dB", "LminusR_dB", "dc_L_V", "dc_R_V", "polarity_L", "polarity_R"]),
    "fr":        (t_fr, ["analyzer", "pass", "mode", "freq_Hz", "L_V", "R_V", "L_dB_re1k",
                         "R_dB_re1k", "LminusR_dB", "riaa_dB_re1k"]),
    "thdn":      (t_thdn, ["analyzer", "sweep", "x", "func", "out_L_V", "out_R_V", "L", "R"]),
    "noise":     (t_noise, ["weighting", "channel", "noise_V", "SN_dB", "EIN_V", "EIN_dBu"]),
    "fft":       (t_fft, ["analyzer", "freq_Hz", "level_V"]),
    "imd":       (t_imd, ["test", "vin_V", "L_dB", "R_dB"]),
    "imdlevel":  (t_imd_level, ["test", "vin_V", "L_dB", "R_dB"]),
    "xtalk":     (t_xtalk, ["freq_Hz", "LtoR_dB", "RtoL_dB"]),
    "zout":      (t_zout, ["channel", "V_200k", "V_600", "Zout_ohm"]),
    "zin":       (t_zin, ["freq_Hz", "channel", "V_src10", "V_src600", "Zin_ohm"]),
    "multitone": (t_multitone, ["freq_Hz", "level_V"]),
    "tracking":  (t_tracking, ["step", "setting", "L_V", "R_V", "gain_L_dB", "gain_R_dB", "LminusR_dB"]),
    "cmrr":      (t_cmrr, ["freq_Hz", "channel", "diff_out_V", "cm_out_V", "CMRR_dB"]),
    "gainlaw":   (t_gainlaw, ["set_dB", "L_V", "R_V", "gain_L_dB", "gain_R_dB",
                              "track_err_L_dB", "track_err_R_dB"]),
    "xover":     (t_xover, ["side", "type", "fc_Hz", "freq_Hz", "L_V", "R_V",
                            "L_dB_re_pass", "R_dB_re_pass"]),
    "limiter":   (t_limiter, ["in_V", "out_L_V", "out_R_V", "gain_L_dB", "gain_R_dB"]),
}
DUT_PLAN = ["gainlaw", "xover", "limiter"]
ALL_PLAN = ["check", "fr", "thdn", "noise", "fft", "imd", "imdlevel", "xtalk", "zout", "zin", "multitone"]
TITLES = {
    "setlevel": "Level set by hand", "check": "Gain, balance, DC offset, polarity",
    "fr": "Frequency response", "thdn": "THD+N and THD", "noise": "Noise and hum",
    "fft": "Spectrum of a 1 kHz tone", "imd": "Intermodulation distortion",
    "imdlevel": "IMD vs input level", "xtalk": "Crosstalk", "zout": "Output impedance",
    "zin": "Input impedance", "multitone": "Multitone", "tracking": "Volume-control tracking",
    "cmrr": "Common-mode rejection", "gainlaw": "DUT gain control",
    "xover": "Crossover filters", "limiter": "Limiter",
}


# ---------------------------------------------------------------- the report

def report_test(rep, name, header, rows, a, ctx):
    rep.heading(TITLES.get(name, name))
    if not rows:
        rep.note("No results.", warn=True)
        return
    recs = [dict(zip(header, r)) for r in rows]
    dash = {"linestyle": "--"}
    if name == "fr":
        for (an,), g in _groups(recs, "analyzer").items():
            first = [q for q in g if str(q["pass"]) == "1"]
            series = []
            for mode, lab, style in (("RMSS", "selective ", {}),
                                     ("RMS", "broadband ", {"linestyle": "--", "linewidth": 1.0})):
                m = [q for q in first if q["mode"] == mode]
                if m:
                    series += _lr(m, "freq_Hz", "L_dB_re1k", "R_dB_re1k", lab, style)
            if a.riaa:
                m = [q for q in first if q["mode"] == "RMSS"] or first
                series.append(("RIAA", [_f(q["freq_Hz"]) for q in m], [_f(q["riaa_dB_re1k"]) for q in m],
                               {"color": "#888888", "linestyle": ":"}))
                rep.plot(f"fr_riaa_dev_{an}",
                         [(f"{ch} − RIAA", [_f(q["freq_Hz"]) for q in m],
                           [_f(q[f"{ch}_dB_re1k"]) - _f(q["riaa_dB_re1k"]) for q in m],
                           {"color": col}) for ch, col in (("L", L_COL), ("R", R_COL))],
                         title=f"Deviation from RIAA{' (IEC)' if a.riaa_iec else ''}, {an}",
                         xlabel="Frequency (Hz)", ylabel="dB", logx=True, hlines=[(0, None)], height=3.2)
            rep.plot(f"fr_{an}", series, title=f"Frequency response, {an}, {a.vin:g} V in",
                     xlabel="Frequency (Hz)", ylabel="dB re 1 kHz", logx=True)
            rep.plot(f"fr_balance_{an}",
                     [(f"pass {p}, {'selective' if m == 'RMSS' else 'broadband'}",
                       [_f(q["freq_Hz"]) for q in gg], [_f(q["LminusR_dB"]) for q in gg])
                      for (p, m), gg in _groups(g, "pass", "mode").items()],
                     title=f"L − R, {an}", xlabel="Frequency (Hz)", ylabel="L − R (dB)", logx=True, height=3.2)
    elif name == "thdn":
        for (an,), g in _groups(recs, "analyzer").items():
            s = [q for q in g if q["sweep"] == "freq"]
            series = []
            for func, lab, style in (("THDN", "THD+N ", {}), ("THD", "THD ", dash)):
                ss = [q for q in s if q["func"] == func]
                if ss:
                    series += _lr(ss, "x", "L", "R", lab, style)
            if series:
                rep.plot(f"thdn_freq_{an}", series, title=f"THD+N and THD vs frequency, {a.vin:g} V in, {an}",
                         xlabel="Frequency (Hz)", ylabel="dB", logx=True)
        lv = [q for q in recs if q["sweep"] == "level"]
        if lv:
            series = []
            for func, lab, style in (("THDN", "THD+N ", {}), ("THD", "THD ", dash)):
                ss = [q for q in lv if q["func"] == func]
                if ss:
                    series += _lr(ss, "x", "L", "R", lab, style)
            rep.plot("thdn_level", series, title="THD+N and THD vs input level, 1 kHz",
                     xlabel="Input (V rms)", ylabel="dB", logx=True,
                     hlines=[(-40, "1 %"), (-60, "0.1 %")])
            out = [q for q in lv if q["func"] == "THDN"]
            rep.plot("thdn_transfer", [("L", [_f(q["x"]) for q in out], [_f(q["out_L_V"]) for q in out], {"color": L_COL}),
                                       ("R", [_f(q["x"]) for q in out], [_f(q["out_R_V"]) for q in out], {"color": R_COL})],
                     title="Output vs input, 1 kHz (bends over at clipping)",
                     xlabel="Input (V rms)", ylabel="Output (V rms)", logx=True, logy=True, height=3.4)
    elif name == "noise":
        rep.table(header, rows)
        if "hum_fft" in ctx:
            f, y = ctx["hum_fft"]
            rep.plot("noise_idle_fft", [("CH1 idle", list(f), [_dbv(v) for v in y])],
                     title="Idle output spectrum (input terminated)", xlabel="Frequency (Hz)",
                     ylabel="Level (dBV)", logx=True, markers=False)
    elif name in ("fft", "multitone"):
        rep.plot(name, [(name, [_f(q["freq_Hz"]) for q in recs], [_dbv(q["level_V"]) for q in recs])],
                 title=f"{TITLES[name]}, {a.vin:g} V in", xlabel="Frequency (Hz)", ylabel="Level (dBV)",
                 logx=True, markers=False)
    elif name == "xtalk":
        xs = [_f(q["freq_Hz"]) for q in recs]
        rep.plot("xtalk", [("L → R", xs, [_f(q["LtoR_dB"]) for q in recs], {"color": L_COL}),
                           ("R → L", xs, [_f(q["RtoL_dB"]) for q in recs], {"color": R_COL})],
                 title="Crosstalk", xlabel="Frequency (Hz)", ylabel="dB", logx=True)
        rep.table(header, rows)
    elif name == "imdlevel":
        for (test,), g in _groups(recs, "test").items():
            rep.plot(f"imdlevel_{test}", _lr(g, "vin_V", "L_dB", "R_dB"),
                     title=f"{test} IMD vs input level", xlabel="Input (V rms)", ylabel="IMD (dB)", logx=True)
        rep.table(header, rows)
    elif name == "imd":
        car = [q for q in recs if str(q["test"]).startswith("SMPTE_60_")]
        if car:
            for q in car:
                q["carrier_Hz"] = 1000 * float(str(q["test"]).rsplit("_", 1)[1].rstrip("k"))
            rep.plot("imd_smpte_carrier", _lr(car, "carrier_Hz", "L_dB", "R_dB"),
                     title=f"SMPTE IMD vs upper-tone frequency (60 Hz + f, 4:1, {a.vin:g} V)",
                     xlabel="Upper tone (Hz)", ylabel="IMD (dB)", logx=True, height=3.4)
        rep.table(header, rows)
    elif name == "gainlaw":
        rep.plot("gainlaw", _lr(recs, "set_dB", "track_err_L_dB", "track_err_R_dB"),
                 title="Gain tracking error (measured − set, re the 0 dB setting)",
                 xlabel="Gain setting (dB)", ylabel="Error (dB)", hlines=[(0, None)], height=3.4)
        rep.table(header, rows)
    elif name == "xover" and len(a.types) == 1:          # one type, a family of cutoffs
        chans = [("L", "L_dB_re_pass")] + ([] if a.mono else [("R", "R_dB_re_pass")])
        for ch, col in chans:
            rep.plot(f"xover_{a.side}_{a.types[0]}_{ch}",
                     [(f"{_f(fc):g} Hz", [_f(q["freq_Hz"]) for q in gg], [_f(q[col]) for q in gg])
                      for (fc,), gg in _groups(recs, "fc_Hz").items()],
                     title=f"{a.side.upper()} {a.types[0]} at each cutoff{'' if a.mono else ', ' + ch}",
                     xlabel="Frequency (Hz)", ylabel="dB re passband", logx=True,
                     hlines=[(-3, "-3 dB"), (-6, "-6 dB")])
    elif name == "xover":
        for (side, fc), g in _groups(recs, "side", "fc_Hz").items():
            chans = [("L", "L_dB_re_pass")] + ([] if a.mono else [("R", "R_dB_re_pass")])
            for ch, col in chans:
                rep.plot(f"xover_{side}_{fc}_{ch}",
                         [(t, [_f(q["freq_Hz"]) for q in gg], [_f(q[col]) for q in gg])
                          for (t,), gg in _groups(g, "type").items()],
                         title=f"{side.upper()} filter types at {_f(fc):g} Hz{'' if a.mono else ', ' + ch}",
                         xlabel="Frequency (Hz)", ylabel="dB re passband", logx=True,
                         hlines=[(-3, "-3 dB"), (-6, "-6 dB")])
    elif name == "limiter":
        xs = [_dbv(q["in_V"]) for q in recs]
        series = [("output L", xs, [_dbv(q["out_L_V"]) for q in recs], {"color": L_COL})]
        if not a.mono:
            series.append(("output R", xs, [_dbv(q["out_R_V"]) for q in recs], {"color": R_COL}))
        series.append(("output = input", xs, xs, {"linestyle": "--", "color": "#888888"}))
        rep.plot("limiter", series, title=f"Limiter at {a.thresh:g} dB", xlabel="Input (dBV)",
                 ylabel="Output (dBV)")
        rep.table(header, rows)
    elif name == "tracking":
        xs = [_f(q["gain_L_dB"]) for q in recs]
        rep.plot("tracking", [("L − R", xs, [_f(q["LminusR_dB"]) for q in recs])],
                 title="Channel balance vs volume setting", xlabel="Gain L (dB)", ylabel="L − R (dB)",
                 hlines=[(0, None)], height=3.4)
        rep.table(header, rows)
    else:
        rep.table(header, rows)


# ---------------------------------------------------------------- main

def run_one(rig, a, rep, name, ctx):
    fn, header = TESTS[name]
    rows = []
    try:
        rig.log(f"\n=== {name} ===")
        rows = fn(rig, a, ctx)
    finally:
        rep.csv(f"{name}.csv", header, rows)
        report_test(rep, name, header, rows, a, ctx)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", help="COMn or GPIB0::20::INSTR (not needed with --dry-run)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--dry-run", action="store_true", help="no instrument; print the SCPI")
    p.add_argument("--vin", type=float, default=0.5,
                   help="test level at the DUT input, V rms (default 0.5 V = -3.8 dBu, a line "
                        "level; ~0.005 for MM phono, ~0.0005 for MC)")
    p.add_argument("--vmax", type=float, default=8.0,
                   help="never drive the input above this, V rms (thdn's clipping sweep stops here)")
    p.add_argument("--unbal", action="store_true",
                   help="generator from the BNC UNBAL output (RCA inputs); default XLR BAL")
    p.add_argument("--zgen", default="R10", choices=("R10", "R200", "R600"),
                   help="generator source impedance on BAL (also terminates the input for noise)")
    p.add_argument("--no-lowd", dest="lowd", action="store_false",
                   help="use the universal generator even if UPL-B1 (low distortion) is fitted; "
                        "without B1 it is used anyway")
    p.add_argument("--ground", action="store_true", help="analyzer INP:LOW GRO instead of FLOat")
    p.add_argument("--settle", type=float, default=0.3, help="seconds after each generator change")
    p.add_argument("--ref-out", type=float,
                   help="noise: S/N reference output, V (default: the output at --vin)")
    add_output_args(p, default_label="analog")
    p.add_argument("--no-reset", action="store_true", help="skip the initial *RST")
    p.add_argument("--stay-remote", action="store_true", help="leave the UPL in REMOTE at the end")
    p.add_argument("--stepped", action="store_true",
                   help="fr/thdn: step the frequency from the PC instead of the UPL's own sweep")
    p.add_argument("--preserve", action="store_true",
                   help="snapshot the UPL setup first and restore it at the end (MMEM:STOR:STAT 2)")
    p.add_argument("--state-file", default="C:\\UPL\\USER\\UPLTMP.SCO")
    p.add_argument("--dut-spec", metavar="NAME|FILE",
                   help="JSON of the DUT's published figures (keys: gain dc fr thdn maxout snr ein "
                        "imd xtalk zout zin cmrr), printed next to each result")
    p.add_argument("--set-level", action="store_true", help="run the guided `setlevel` step first")
    p.add_argument("--target", type=float, help="setlevel: output (V rms) to reach at --vin")
    p.add_argument("--gain", type=float, help="setlevel: gain (dB) to reach, instead of --target")
    p.add_argument("--max-time", type=float, default=600.0, help="setlevel: stop the tone after this long")
    p.add_argument("--mono", action="store_true",
                   help="one-channel DUT, or one output patched: report analyzer CH1 only")
    p.add_argument("--dut", choices=sorted(DUTS), help="control the DUT: dcx = Behringer DCX2496")
    p.add_argument("--dut-port", default="COM2", help="--dut serial port")
    p.add_argument("--dut-out", default="out1",
                   help="--dut dcx: output(s) measured, 'out1' or 'out1,out2' (-> analyzer CH1, CH2)")
    p.add_argument("--dut-asis", action="store_true",
                   help="--dut: measure the DUT as it is set up; no writes at all")

    sub = p.add_subparsers(dest="test", required=True)
    for name in ("setlevel", "check", "imd", "imdlevel", "xtalk", "zout", "zin", "tracking", "cmrr", "all"):
        sub.add_parser(name)
    s = sub.add_parser("gainlaw", help="needs --dut")
    s.add_argument("--gains", default="-15,-10,-6,-3,0,3,6,10,15", help="DUT gain settings, dB")
    s = sub.add_parser("xover", help="needs --dut")
    s.add_argument("--side", choices=("hp", "lp"), default="hp")
    s.add_argument("--types", default="but12,but24,bes24,lr24,but48",
                   help="filter types (dcx2496.FILTER_TYPES)")
    s.add_argument("--freqs", default="500", help="cutoff(s), Hz, comma-separated")
    s.add_argument("--points", type=int, default=31)
    s = sub.add_parser("limiter", help="needs --dut")
    s.add_argument("--thresh", type=float, default=-10.0, help="limiter threshold, dB (DUT's scale)")
    s = sub.add_parser("fr")
    s.add_argument("--start", type=float, default=10.0)
    s.add_argument("--stop", type=float, help="default 20 kHz (100 kHz with --wide)")
    s.add_argument("--points", type=int, default=31)
    s.add_argument("--repeat", type=int, default=1)
    s.add_argument("--wide", action="store_true", help="to 100 kHz on the 110 kHz analyzer")
    s.add_argument("--riaa", action="store_true", help="phono stage: deviation from RIAA playback")
    s.add_argument("--riaa-iec", action="store_true", help="--riaa with the IEC 7950 us rumble pole")
    s = sub.add_parser("thdn")
    s.add_argument("--analyzer", default="A22", help="A22, A100 or A22,A100 (the frequency sweep)")
    for name in ("noise", "fft", "multitone"):
        s = sub.add_parser(name)
        s.add_argument("--fft-avg", type=int, default=4)
        if name == "fft":
            s.add_argument("--analyzer", default="A22")

    a = p.parse_args()
    defaults = dict(start=10.0, stop=None, points=31, repeat=1, wide=False, riaa=False, riaa_iec=False,
                    analyzer="A22", fft_avg=4, gains="-15,-10,-6,-3,0,3,6,10,15", side="hp",
                    types="but12,but24,bes24,lr24,but48", freqs="500", thresh=-10.0)
    for k, v in defaults.items():
        if not hasattr(a, k):
            setattr(a, k, v)
    a.riaa = a.riaa or a.riaa_iec
    a.gains = [float(x) for x in str(a.gains).split(",")]
    a.types = str(a.types).split(",")
    a.freqs = [float(x) for x in str(a.freqs).split(",")]
    a.dut_outs = a.dut_out.split(",")
    if (a.dut_asis or a.dut_out != "out1") and not a.dut:
        p.error("--dut-asis / --dut-out need --dut")
    if a.dut == "dcx":
        from dcx2496 import FILTER_TYPES, OUTPUT_CHANNELS
        bad = [t for t in a.types if t not in FILTER_TYPES] + [o for o in a.dut_outs
                                                                if o not in OUTPUT_CHANNELS]
        if bad:
            p.error(f"unknown DCX filter type/output {bad}: types {FILTER_TYPES}, outputs out1..out6")
        if len(a.dut_outs) > 2:
            p.error("--dut-out: at most two outputs (analyzer CH1, CH2)")
        if len(a.dut_outs) == 1:
            a.mono = True           # one output patched: analyzer CH2 carries nothing
    a.analyzers = a.analyzer.split(",")
    if a.vin > a.vmax:
        p.error(f"--vin {a.vin} is above --vmax {a.vmax}")
    if a.vmax > 20:
        p.error("--vmax: the UPL generator's limit is 20 V")
    a.spec = dac.load_spec(a.dut_spec) if a.dut_spec else None

    if a.dry_run:
        u = DryRunUPL(echo=False)
    else:
        if not a.port:
            p.error("--port is required (or use --dry-run)")
        u = connect(a.port, a.baud, a.timeout)
    label = ("dryrun_" if a.dry_run else "") + a.label
    with Run("analog", label=label, outdir=a.outdir, title=f"Analog test: {a.test}") as rep:
        _main(u, a, rep)


def _main(u, a, rep):
    log = Log(None)
    rig = AnalogRig(u, log, a)
    rig.level_setting = ""
    log(f"# analog_test {a.test}  label={a.label}  vin={a.vin:g} V  vmax={a.vmax:g} V  "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
    idn = rig.q("*IDN?")
    log(f"# UPL: {idn}")
    opt = rig.q("*OPT?")
    has_b1 = "B1" in {t.split("(")[0].strip() for t in opt.split(",")}
    log(f"# UPL options: {opt}")
    if a.lowd and not has_b1:
        a.lowd = False
    log("# sine generator: " + ("UPL-B1 low distortion, 10 Hz-110 kHz" if a.lowd else
        "universal, 2 Hz-21.75 kHz (THD+N floor ~-103 dB)"
        + ("" if has_b1 else "; UPL-B1 not fitted -- fine for nearly any preamp")))
    rep.info("UPL", idn)
    rep.info("Input level", f"{a.vin:g} V rms ({dbu(a.vin):+.1f} dBu), max {a.vmax:g} V")
    rep.info("Generator", ("UNBAL (BNC)" if a.unbal else f"BAL (XLR), {a.zgen}")
             + (", B1 low-distortion" if a.lowd else ", universal"))
    if a.spec:
        log(f"# DUT reference: {a.spec.get('name', a.dut_spec)}")
        rep.info("DUT reference", a.spec.get("name", a.dut_spec))
    log("# NOTHING but the UPL on the DUT's outputs: no power amp, no headphones.")
    if a.mono:
        log("# one channel (--mono): analyzer CH1 only")
        rep.info("Channels", "one (analyzer CH1)")
    rig.dut = None
    if a.dut:
        rig.dut = DUTS[a.dut](a.dut_port, a.dut_outs, dcx=_DryDcx() if a.dry_run else None)
        log(f"# DUT: {rig.dut.describe()}")
        rep.info("DUT", rig.dut.describe())
        if a.dut_asis:
            log("# DUT measured as it is set up (--dut-asis): nothing written to it")
            rep.info("DUT settings", "as found (--dut-asis)")
        else:
            rig.dut.flat()
            log(f"# DUT set flat: {rig.dut.FLAT} (its previous settings are not restored)")
            rep.info("DUT settings", f"flat: {rig.dut.FLAT}")
    ctx = {}
    try:
        with preserve_state(u, a.state_file, enabled=a.preserve):
            if not a.no_reset:
                rig.w("*CLS")      # stale errors (e.g. -420 from a VISA open) aren't *RST's
                rig.setc("*RST", slow=True)
                rig.w("*CLS")
            rig.setc(f"SOUR:VOLT {MUTE_V:g} V", quiet=True)     # nothing on the outputs yet
            if a.set_level and a.test != "setlevel":
                run_one(rig, a, rep, "setlevel", ctx)
            plan = [a.test]
            if a.test == "all":
                plan = ALL_PLAN + (DUT_PLAN if rig.dut and not a.dut_asis else [])
            for name in plan:
                run_one(rig, a, rep, name, ctx)
            rig.cleanup()
            if rig.level_setting:
                rep.info("DUT volume setting", rig.level_setting)
    finally:
        try:
            u.write(f"SOUR:VOLT {MUTE_V:g} V")                 # never leave a tone on the DUT
        except Exception:
            pass
        if rig.dut:
            msg = rig.dut.restore()
            if msg:
                log(f"# DUT {msg}")
            rig.dut.close()
        if rig.rejected:
            log(f"\n# {len(rig.rejected)} command(s) rejected by the UPL:")
            for c, e in rig.rejected:
                log(f"#   {c}  [{e}]")
            rep.heading("Commands the UPL rejected")
            rep.table(["command", "error"], rig.rejected)
        if not a.stay_remote:
            go_local(u)
        u.close()
    log(f"\n# done -> {rep.dir}")


if __name__ == "__main__":
    main()
