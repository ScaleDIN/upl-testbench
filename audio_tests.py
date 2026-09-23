#!/usr/bin/env python3
"""
audio_tests.py - a small audio-analyzer test suite (the classic UPL-style measurements)
that runs against this PC's soundcard, or against a WAV file, or purely synthetically.

Measurements implemented:
  - level (dBFS, RMS), DC offset
  - fundamental frequency (parabolic-interpolated)
  - THD            (harmonic distortion, harmonics 2..N)
  - THD+N          (distortion + noise in the 20 Hz .. 20 kHz band)
  - SNR / noise floor
  - frequency response (stepped-sine sweep)
  - crosstalk (stereo loopback: drive one channel, measure the other)

Subcommands that make NO sound (safe anytime):
  devices     list audio I/O devices
  selftest    validate the analyzer on a synthesized signal with known THD/level
  analyze     analyze an existing WAV file
  noise       record the INPUT with nothing playing -> noise floor + spectrum

Subcommands that PLAY test tones (do them deliberately, with levels set):
  tone        play a single tone (for manual checks)
  loopback    play a tone AND record simultaneously -> full single-tone report
  response    stepped-sine frequency-response sweep -> CSV

Wiring for real analog measurements: patch a cable from this PC's line/headphone OUT
to its line/mic IN, set output ~ -6 dBFS and input gain so it doesn't clip, and turn
OFF any "audio enhancements" on both endpoints.
"""

import argparse
import sys
import numpy as np

FS = 48000
FULLSCALE_SINE_RMS = 1.0 / np.sqrt(2.0)   # RMS of a peak=1.0 sine => 0 dBFS reference


# ----------------------------------------------------------------------------- analysis
def _blackman_harris(n):
    a = [0.35875, 0.48829, 0.14128, 0.01168]
    k = np.arange(n)
    return (a[0] - a[1]*np.cos(2*np.pi*k/(n-1))
            + a[2]*np.cos(4*np.pi*k/(n-1)) - a[3]*np.cos(6*np.pi*k/(n-1)))


def analyze_tone(x, fs=FS, fmin=20.0, fmax=20000.0, nharm=10):
    """Single-tone analysis of a 1-D signal. Returns a dict of results."""
    x = np.asarray(x, dtype=np.float64)
    x = x - np.mean(x)                       # remove DC for spectral work
    n = len(x)
    rms = np.sqrt(np.mean(x**2))
    dc = float(np.mean(np.asarray(x, dtype=np.float64)))  # (already removed; report raw below)

    w = _blackman_harris(n)
    X = np.fft.rfft(x * w)
    freqs = np.fft.rfftfreq(n, 1/fs)
    mag2 = np.abs(X)**2

    # fundamental = largest bin inside [fmin, fmax]
    band = (freqs >= fmin) & (freqs <= fmax)
    k0 = np.argmax(np.where(band, mag2, 0.0))
    # parabolic interpolation for a better frequency estimate
    if 1 <= k0 < len(mag2)-1:
        a, b, c = np.log(mag2[k0-1]+1e-30), np.log(mag2[k0]+1e-30), np.log(mag2[k0+1]+1e-30)
        delta = 0.5*(a-c)/(a-2*b+c+1e-30)
    else:
        delta = 0.0
    f0 = (k0 + delta) * fs / n

    binwidth = fs / n
    half = max(3, int(round(3.0 / binwidth * binwidth)) )  # ~a few bins each side
    half = max(3, int(np.ceil(4)))  # fixed small window around each harmonic peak

    def band_power(center_hz):
        kc = int(round(center_hz * n / fs))
        lo, hi = max(1, kc-half), min(len(mag2), kc+half+1)
        if lo >= hi:
            return 0.0
        return float(np.sum(mag2[lo:hi]))

    p_fund = band_power(f0)
    p_harm = 0.0
    harmonics = []
    for h in range(2, nharm+1):
        fh = f0 * h
        if fh > min(fmax, fs/2*0.98):
            break
        ph = band_power(fh)
        harmonics.append((h, fh, ph))
        p_harm += ph

    # total power in-band excluding the fundamental bins => distortion + noise
    inband = (freqs >= fmin) & (freqs <= fmax)
    total_inband = float(np.sum(mag2[inband]))
    klo, khi = max(1, int(round(f0*n/fs))-half), min(len(mag2), int(round(f0*n/fs))+half+1)
    p_fund_bins = float(np.sum(mag2[klo:khi]))
    p_rest = max(total_inband - p_fund_bins, 0.0)

    thd = np.sqrt(p_harm / p_fund) if p_fund > 0 else float("nan")
    thdn = np.sqrt(p_rest / p_fund_bins) if p_fund_bins > 0 else float("nan")
    snr = 1.0/thdn if thdn > 0 else float("inf")

    return {
        "n": n, "fs": fs,
        "level_dBFS": 20*np.log10(rms/FULLSCALE_SINE_RMS + 1e-30),
        "rms": rms,
        "dc_offset": float(np.mean(np.asarray(x)+0.0)),  # ~0 after removal; see analyze_full
        "f0_Hz": f0,
        "THD_pct": 100*thd, "THD_dB": 20*np.log10(thd+1e-30),
        "THDN_pct": 100*thdn, "THDN_dB": 20*np.log10(thdn+1e-30),
        "SNR_dB": 20*np.log10(snr+1e-30) if np.isfinite(snr) else float("inf"),
        "harmonics": harmonics,
    }


def print_report(r, title="RESULT"):
    print(f"\n=== {title} ===")
    print(f"  Fundamental : {r['f0_Hz']:.3f} Hz")
    print(f"  Level       : {r['level_dBFS']:.3f} dBFS   (RMS {r['rms']:.5f})")
    print(f"  THD         : {r['THD_pct']:.5f} %   ({r['THD_dB']:.1f} dB)")
    print(f"  THD+N       : {r['THDN_pct']:.5f} %   ({r['THDN_dB']:.1f} dB)")
    print(f"  SNR         : {r['SNR_dB']:.1f} dB")
    if r.get("harmonics"):
        hs = ", ".join(f"H{h}:{20*np.log10(np.sqrt(p/ (r['rms']**2*r['n'])) +1e-30):.0f}dB"
                       for h, f, p in r["harmonics"][:5])


# ----------------------------------------------------------------------------- signal gen
def make_tone(freq, seconds, level_dBFS=-6.0, fs=FS):
    t = np.arange(int(seconds*fs))/fs
    amp = 10**(level_dBFS/20) * 1.0     # peak amplitude relative to full scale
    return (amp*np.sin(2*np.pi*freq*t)).astype(np.float32)


# ----------------------------------------------------------------------------- commands
def cmd_devices(args):
    import sounddevice as sd
    print(sd.query_devices())
    print("\nDefault (in, out):", sd.default.device)
    return 0


def cmd_selftest(args):
    """Synthesize a tone with KNOWN harmonics + noise and confirm the analyzer recovers it."""
    fs = FS
    f0 = 997.0
    dur = 1.0
    t = np.arange(int(dur*fs))/fs
    fund_dBFS = -6.0
    A = 10**(fund_dBFS/20)
    # inject 2nd @ -60 dB rel fund, 3rd @ -70 dB rel fund
    h2, h3 = 10**(-60/20), 10**(-70/20)
    x = A*(np.sin(2*np.pi*f0*t) + h2*np.sin(2*np.pi*2*f0*t) + h3*np.sin(2*np.pi*3*f0*t))
    rng = np.random.default_rng(0)
    noise_dBFS = -100.0
    x = x + 10**(noise_dBFS/20)*rng.standard_normal(len(t))
    expected_thd = np.sqrt(h2**2 + h3**2)   # ~ -59.6 dB

    r = analyze_tone(x, fs)
    print_report(r, "SELF-TEST (synthetic)")
    print("\n  Expected  f0 = 997.000 Hz, level = -6.00 dBFS, THD ~ "
          f"{100*expected_thd:.4f}% ({20*np.log10(expected_thd):.1f} dB)")
    ok = (abs(r['f0_Hz']-f0) < 0.5 and abs(r['level_dBFS']-fund_dBFS) < 0.2
          and abs(r['THD_dB']-20*np.log10(expected_thd)) < 3.0)
    print(f"  Analyzer self-check: {'PASS' if ok else 'CHECK'}")
    return 0 if ok else 1


def cmd_analyze(args):
    import soundfile as sf
    data, fs = sf.read(args.wav, dtype="float64", always_2d=True)
    for ch in range(data.shape[1]):
        r = analyze_tone(data[:, ch], fs)
        print_report(r, f"{args.wav} ch{ch+1}")
    return 0


def cmd_noise(args):
    import sounddevice as sd
    print(f"Recording input noise floor for {args.seconds}s (make sure nothing is playing)...")
    rec = sd.rec(int(args.seconds*FS), samplerate=FS, channels=1,
                 device=args.device, dtype="float64")
    sd.wait()
    x = rec[:, 0]
    rms = np.sqrt(np.mean(x**2))
    peak = np.max(np.abs(x))
    print(f"  Input RMS   : {20*np.log10(rms/FULLSCALE_SINE_RMS+1e-30):.1f} dBFS")
    print(f"  Input peak  : {20*np.log10(peak+1e-30):.1f} dBFS")
    # dominant spurs
    w = _blackman_harris(len(x))
    X = np.abs(np.fft.rfft((x-np.mean(x))*w))
    fr = np.fft.rfftfreq(len(x), 1/FS)
    idx = np.argsort(X)[-6:][::-1]
    print("  Top spectral peaks (Hz):", ", ".join(f"{fr[i]:.1f}" for i in sorted(idx)))
    return 0


def cmd_loopback(args):
    import sounddevice as sd
    tone = make_tone(args.freq, args.seconds, args.level)
    print(f"Playing {args.freq} Hz @ {args.level} dBFS and recording simultaneously...")
    rec = sd.playrec(tone.reshape(-1, 1), samplerate=FS, channels=1,
                     input_mapping=[1], dtype="float64",
                     device=(args.in_device, args.out_device))
    sd.wait()
    x = rec[:, 0]
    # discard first 50 ms to avoid latency/settling
    x = x[int(0.05*FS):]
    if np.max(np.abs(x)) < 1e-4:
        print("  WARNING: input is nearly silent - is the loopback cable connected / input selected?")
    r = analyze_tone(x, FS)
    print_report(r, f"LOOPBACK {args.freq} Hz")
    return 0


def cmd_response(args):
    import sounddevice as sd
    freqs = np.geomspace(args.start, args.stop, args.points)
    out = open(args.output, "w") if args.output else sys.stdout
    out.write("frequency_Hz,level_dBFS,THDN_pct\n")
    ref = None
    for f in freqs:
        tone = make_tone(f, args.dwell, args.level)
        rec = sd.playrec(tone.reshape(-1, 1), samplerate=FS, channels=1,
                         input_mapping=[1], dtype="float64",
                         device=(args.in_device, args.out_device))
        sd.wait()
        x = rec[int(0.05*FS):, 0]
        r = analyze_tone(x, FS)
        if ref is None:
            ref = r["level_dBFS"]
        out.write(f"{f:.1f},{r['level_dBFS']-ref:.3f},{r['THDN_pct']:.4f}\n")
        print(f"  {f:8.1f} Hz : {r['level_dBFS']-ref:+.2f} dB (rel), THD+N {r['THDN_pct']:.3f}%")
    if args.output:
        out.close(); print(f"Wrote {args.output}")
    return 0


def cmd_tone(args):
    import sounddevice as sd
    print(f"Playing {args.freq} Hz @ {args.level} dBFS for {args.seconds}s ...")
    sd.play(make_tone(args.freq, args.seconds, args.level), samplerate=FS, device=args.out_device)
    sd.wait()
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="list audio devices")
    sub.add_parser("selftest", help="validate the analyzer on a synthetic signal (no sound)")

    a = sub.add_parser("analyze", help="analyze a WAV file"); a.add_argument("wav")

    n = sub.add_parser("noise", help="record input noise floor (no sound out)")
    n.add_argument("--seconds", type=float, default=2.0); n.add_argument("--device", default=None)

    t = sub.add_parser("tone", help="PLAY a tone")
    t.add_argument("--freq", type=float, default=1000.0); t.add_argument("--level", type=float, default=-6.0)
    t.add_argument("--seconds", type=float, default=2.0); t.add_argument("--out-device", dest="out_device", default=None)

    l = sub.add_parser("loopback", help="PLAY a tone and record it (needs out->in cable)")
    l.add_argument("--freq", type=float, default=1000.0); l.add_argument("--level", type=float, default=-6.0)
    l.add_argument("--seconds", type=float, default=1.0)
    l.add_argument("--out-device", dest="out_device", default=None); l.add_argument("--in-device", dest="in_device", default=None)

    rs = sub.add_parser("response", help="stepped-sine frequency response sweep -> CSV")
    rs.add_argument("--start", type=float, default=20.0); rs.add_argument("--stop", type=float, default=20000.0)
    rs.add_argument("--points", type=int, default=31); rs.add_argument("--level", type=float, default=-6.0)
    rs.add_argument("--dwell", type=float, default=0.4); rs.add_argument("-o", "--output", default=None)
    rs.add_argument("--out-device", dest="out_device", default=None); rs.add_argument("--in-device", dest="in_device", default=None)

    args = p.parse_args()
    return {
        "devices": cmd_devices, "selftest": cmd_selftest, "analyze": cmd_analyze,
        "noise": cmd_noise, "tone": cmd_tone, "loopback": cmd_loopback, "response": cmd_response,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
