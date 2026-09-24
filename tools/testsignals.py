#!/usr/bin/env python3
"""
testsignals.py - generate a DAC/DAP test-signal set as WAV files.

The files are device-agnostic: play them from this PC into any DAC (NAD M51,
Elektor DAC, laptop output, Sony NW-A306 in USB-DAC mode), or copy them onto a
player (the A306's own file playback) and let the UPL listen. Either way the UPL
analyzes the analog output.

One folder per format, e.g.  testsignals/44k1_16/, 48k_24/, 96k_24/, 192k_24/.
Every WAV gets a JSON sidecar with its exact content (tones, levels, segment
times), which measurements/upacd_test.py reads via --wav.

THE SET (per format)
    01..04  1 kHz steady at -1 / -3 / -20 / -60 dBFS   level, max output, THD+N,
                                                        AES17 dynamic range (-60)
    05      digital silence                             noise floor (beware auto-mute)
    06/07   1 kHz L-only / R-only, -3 dBFS              crosstalk at 1 kHz
    08/09   octave steps, L-only / R-only, -3 dBFS      crosstalk vs frequency
    10      1/3-octave steps, -6 dBFS, 20 Hz..0.465 fs   frequency response, THD vs f
    11      level staircase, 1 kHz, 2 kHz markers       linearity, THD+N vs level
    12      SMPTE IMD 60 Hz + 7 kHz 4:1
    13      CCIF 19 kHz + 20 kHz 1:1                    (UPL DFD function)
    14      J-test (fs/4 at -3 dBFS + LSB square fs/192, undithered)   jitter sidebands
    15/16   fs/4 at true peak 0 dBTP / +3 dBTP          intersample-over headroom
    17      1 kHz square, -6 dBFS                       filter ringing (UPL WAV display)
    18      440 Hz positive half-waves                  absolute polarity

LEVELS: 0 dBFS = a sine whose peak is the largest positive code (AES17). Dithered
files use TPDF dither of +-1 LSB; J-test and the fs/4 files are deliberately
undithered because their exact sample values are the point.

SAFETY: several files are within 1 dB of full scale, and 16 is designed to exceed
it between samples. Into the UPL analyzer that's fine; into headphones or
through an amplifier into speakers it is not. Unplug headphones.

Examples:
    python tools/testsignals.py                          # default set -> testsignals/
    python tools/testsignals.py --formats 48000/24 --outdir D:/walkman_tests
    python tools/testsignals.py --formats 44100/16,96000/24 --list
"""

import argparse
import json
import math
import os
import sys

import numpy as np
import soundfile as sf

DEFAULT_FORMATS = "44100/16,48000/24,96000/24,192000/24"
FADE_S = 0.010                     # raised-cosine ramp at every segment edge

THIRD_OCT = [20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500,
             630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000,
             10000, 12500, 16000, 20000, 25000, 31500, 40000, 50000, 63000, 80000]
OCTAVE = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 20000,
          31500, 40000, 63000, 80000]

MARKER_HZ, STEP_HZ = 2000.0, 1000.0


def fmt_name(fs, bits):
    k = fs / 1000
    return (f"{k:g}".replace(".", "k") if k != int(k) else f"{int(k)}k") + f"_{bits}"


def usable(freqs, fs):
    """Tones the format can carry: <= 0.465 fs (keeps 20 kHz at 44.1) and the UPL's ~110 kHz."""
    return [f for f in freqs if f <= min(0.465 * fs, 100000)]


def db2lin(dbfs):
    return 10.0 ** (dbfs / 20.0)


class Builder:
    """Accumulates float segments (1.0 = full-scale peak) for L and R."""

    def __init__(self, fs):
        self.fs = fs
        self.L, self.R = [], []
        self.t = 0.0
        self.segments = []

    def _ramp(self, x):
        n = min(int(FADE_S * self.fs), len(x) // 2)
        if n:
            w = 0.5 - 0.5 * np.cos(np.linspace(0, math.pi, n))
            x[:n] *= w
            x[-n:] *= w[::-1]
        return x

    def tone(self, freq, dbfs, seconds, channels="both", role="step", ramp=True):
        n = int(round(seconds * self.fs))
        x = db2lin(dbfs) * np.sin(2 * math.pi * freq * np.arange(n) / self.fs)
        if ramp:
            x = self._ramp(x)
        self._add(x, channels, {"freq_hz": freq, "dbfs": dbfs, "role": role}, seconds)

    def silence(self, seconds):
        self._add(np.zeros(int(round(seconds * self.fs))), "both",
                  {"freq_hz": None, "dbfs": None, "role": "silence"}, seconds)

    def raw(self, x, seconds, info, channels="both"):
        self._add(x, channels, info, seconds)

    def _add(self, x, channels, info, seconds):
        z = np.zeros_like(x)
        self.L.append(x if channels in ("both", "L") else z)
        self.R.append(x if channels in ("both", "R") else z)
        self.segments.append({"t0": round(self.t, 4), "t1": round(self.t + seconds, 4),
                              "channels": channels, **info})
        self.t += seconds

    def stereo(self):
        return np.column_stack([np.concatenate(self.L), np.concatenate(self.R)])


def quantize(x, bits, dither, rng):
    """Float (1.0 = max positive code) -> integer codes. Returns (codes, n_clipped)."""
    top = 2 ** (bits - 1) - 1
    y = x * top
    if dither:
        y = y + rng.random(y.shape) - rng.random(y.shape)       # TPDF, +-1 LSB
    y = np.round(y)
    clipped = int(np.count_nonzero((y > top) | (y < -top - 1)))
    return np.clip(y, -top - 1, top).astype(np.int32), clipped


def write(outdir, name, codes, fs, bits, meta):
    path = os.path.join(outdir, name + ".wav")
    if bits == 16:
        sf.write(path, codes.astype(np.int16), fs, subtype="PCM_16")
    else:
        sf.write(path, codes << 8, fs, subtype="PCM_24")          # int32 carries 24-bit MSB-aligned
    meta = {"file": name + ".wav", "fs": fs, "bits": bits,
            "duration_s": round(len(codes) / fs, 4), **meta}
    with open(os.path.join(outdir, name + ".json"), "w") as f:
        json.dump(meta, f, indent=1)
    return path, meta


def build_set(fs, bits, steady_s):
    """Yield (name, kind, builder_or_array, dither, extra_meta)."""
    floor = -100.0 if bits == 16 else -120.0

    for i, lvl in enumerate([-1, -3, -20, -60], start=1):
        b = Builder(fs)
        b.tone(STEP_HZ, lvl, steady_s)
        yield f"{i:02d}_1k_{lvl}dBFS", "steady", b, True, {}

    b = Builder(fs)
    b.silence(max(steady_s, 30))
    yield "05_silence", "silence", b, False, {
        "notes": "digital zero. Many DACs auto-mute on it, which reads as a flattering "
                 "floor; compare with 04 (-60 dBFS) for the AES17 dynamic-range figure."}

    for i, ch in ((6, "L"), (7, "R")):
        b = Builder(fs)
        b.tone(STEP_HZ, -3, steady_s, channels=ch)
        yield f"{i:02d}_1k_{ch}_only_-3dBFS", "steady", b, True, {"driven": ch}

    for i, ch in ((8, "L"), (9, "R")):
        b = Builder(fs)
        tones = usable(OCTAVE, fs)
        for f in tones:
            b.tone(f, -3, 5.0 if f < 100 else 3.0, channels=ch)
        yield f"{i:02d}_octaves_{ch}_only_-3dBFS", "freq_steps", b, True, {
            "driven": ch, "tones_hz": tones}

    b = Builder(fs)
    tones = usable(THIRD_OCT, fs)
    b.tone(STEP_HZ, -6, 3.0, role="ref")
    for f in tones:
        b.tone(f, -6, 5.0 if f < 100 else 3.0)
    yield "10_third_octaves_-6dBFS", "freq_steps", b, True, {
        "tones_hz": tones, "ref_hz": STEP_HZ,
        "notes": "starts with a 1 kHz reference. Tones above 20 kHz need the UPL's "
                 "wide analyzer (INST2 A100)."}

    b = Builder(fs)
    levels = [-1, -3, -6, -10] + list(range(-20, int(floor) - 1, -10))
    for lvl in levels:
        b.tone(MARKER_HZ, -1, 2.0, role="marker")
        b.tone(STEP_HZ, lvl, 4.0)
    yield "11_level_staircase", "level_steps", b, True, {
        "marker_hz": MARKER_HZ, "step_hz": STEP_HZ, "nominal_dbfs": levels,
        "ref_dbfs": levels[0],
        "notes": "2 kHz markers delimit the 1 kHz steps. Levels are referenced to the "
                 "first step, not the marker, so the DUT's 1k-vs-2k response cancels."}

    b = Builder(fs)
    pk = db2lin(-1)
    n = int(steady_s * fs)
    t = np.arange(n) / fs
    x = b._ramp(pk * 0.8 * np.sin(2 * math.pi * 60 * t) + pk * 0.2 * np.sin(2 * math.pi * 7000 * t))
    b.raw(x, steady_s, {"freq_hz": [60, 7000], "dbfs": -1, "role": "imd", "ratio": "4:1"})
    yield "12_imd_smpte_60+7k", "imd", b, True, {}

    b = Builder(fs)
    x = b._ramp(pk * 0.5 * (np.sin(2 * math.pi * 19000 * t) + np.sin(2 * math.pi * 20000 * t)))
    b.raw(x, steady_s, {"freq_hz": [19000, 20000], "dbfs": -1, "role": "imd", "ratio": "1:1"})
    yield "13_imd_ccif_19k+20k", "imd", b, True, {
        "notes": "UPL: SENS:FUNC 'DFD', mean 19.5 kHz, difference 1 kHz."}

    # J-test: fs/4 sine sampled at its peaks and zeros (exact codes), plus a
    # 1-LSB square wave at fs/192. Built in codes directly, so no float rounding.
    top = 2 ** (bits - 1) - 1
    n = int(steady_s * fs) // 192 * 192
    amp = int(round(top * db2lin(-3)))
    tone = np.tile(np.array([0, amp, 0, -amp], dtype=np.int32), n // 4)
    lsb = np.where((np.arange(n) // 96) % 2 == 0, 0, -1).astype(np.int32)
    yield "14_jtest", "codes", tone + lsb, False, {
        "tones_hz": [fs / 4], "lsb_square_hz": fs / 192, "dbfs": -3,
        "notes": "undithered by design. Look for sidebands around fs/4 in a zoomed FFT; "
                 "the LSB square's own odd harmonics are expected, jitter shows as "
                 "sidebands at the square's harmonics around the carrier."}

    # fs/4 at 45 deg: samples +a,+a,-a,-a. Reconstructed peak = a*sqrt(2).
    n = int(steady_s * fs) // 4 * 4
    for idx, (name, a, tp) in enumerate((("0dBTP", int(round(top / math.sqrt(2))), 0.0),
                                         ("+3dBTP", top, 3.01)), start=15):
        x = np.tile(np.array([a, a, -a, -a], dtype=np.int32), n // 4)
        yield f"{idx}_fs4_truepeak_{name}", "codes", x, False, {
            "tones_hz": [fs / 4], "true_peak_dbtp": tp,
            "notes": "compare THD+N/level between 15 and 16. A DAC or oversampling "
                     "filter without intersample headroom clips 16 (+3 dB) and not 15."}

    b = Builder(fs)
    n = int(10 * fs)
    sq = db2lin(-6) * np.sign(np.sin(2 * math.pi * 1000 * (np.arange(n) + 0.5) / fs))
    b.raw(b._ramp(sq), 10.0, {"freq_hz": 1000, "dbfs": -6, "role": "square"})
    yield "17_square_1k_-6dBFS", "waveform", b, True, {
        "notes": "naive (not band-limited) square. View with the UPL's WAV function "
                 "or a scope: reconstruction-filter ringing and pre-ringing."}

    b = Builder(fs)
    s = np.sin(2 * math.pi * 440 * np.arange(n) / fs)
    b.raw(b._ramp(db2lin(-6) * np.maximum(s, 0)), 10.0,
          {"freq_hz": 440, "dbfs": -6, "role": "polarity"})
    yield "18_halfwave_440_polarity", "waveform", b, True, {
        "notes": "positive half-waves only. A non-inverting DUT shows positive humps."}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--formats", default=DEFAULT_FORMATS,
                   help=f"comma-separated rate/bits (default {DEFAULT_FORMATS})")
    p.add_argument("--outdir", default=os.path.join(os.path.dirname(__file__), "..", "testsignals"))
    p.add_argument("--steady", type=float, default=20.0, help="length of steady tones, s")
    p.add_argument("--seed", type=int, default=1, help="dither RNG seed (reproducible files)")
    p.add_argument("--list", action="store_true", help="print the plan and sizes, write nothing")
    args = p.parse_args()

    total = 0
    for spec in args.formats.split(","):
        fs, bits = (int(v) for v in spec.split("/"))
        if bits not in (16, 24):
            raise SystemExit(f"bits must be 16 or 24, got {bits}")
        folder = os.path.join(args.outdir, fmt_name(fs, bits))
        if not args.list:
            os.makedirs(folder, exist_ok=True)
        rng = np.random.default_rng(args.seed)
        manifest = []
        print(f"{fmt_name(fs, bits)}  ({fs} Hz, {bits}-bit)")
        for name, kind, src, dither, extra in build_set(fs, bits, args.steady):
            if kind == "codes":
                mono, segments = src, [{"t0": 0.0, "t1": round(len(src) / fs, 4),
                                        "channels": "both"}]
                codes, clipped = np.column_stack([mono, mono]), 0
            else:
                codes, clipped = quantize(src.stereo(), bits, dither, rng)
                segments = src.segments
            size = codes.shape[0] * 2 * bits // 8 + 44
            total += size
            meta = {"kind": kind, "dither": "tpdf" if dither else "none",
                    "segments": segments, **extra}
            if clipped:
                print(f"  WARNING {name}: {clipped} samples clipped", file=sys.stderr)
            if args.list:
                print(f"  {name:32s} {codes.shape[0] / fs:6.1f} s  {size / 1e6:6.1f} MB")
                continue
            write(folder, name, codes, fs, bits, meta)
            manifest.append({"file": name + ".wav", "kind": kind,
                             "duration_s": round(codes.shape[0] / fs, 2)})
            print(f"  {name}.wav  {codes.shape[0] / fs:.1f} s")
        if not args.list:
            with open(os.path.join(folder, "manifest.json"), "w") as f:
                json.dump({"fs": fs, "bits": bits, "files": manifest}, f, indent=1)
    print(f"total {total / 1e6:.0f} MB" + ("" if args.list else f" -> {os.path.abspath(args.outdir)}"))


if __name__ == "__main__":
    main()
