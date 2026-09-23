#!/usr/bin/env python3
"""
upacd_test.py - drive R&S Audio Test Disc (UPA-CD) tracks from this PC into any
DUT while the UPL measures the result.

The DUT is whatever is between the sound device and the UPL's analyzer input:

    laptop --USB--> NAD M51 --balanced--> UPL          (--device <M51 index>)
    laptop --3.5mm--> adapter ----------> UPL          (--device <built-in index>)
    laptop --> M51 --> DCX2496 ---------> UPL          (chain them)

Pick the output with --device (find indices via `python audio_tests.py devices`).
--label just tags the CSV so runs are comparable later.

WHY THE DISC AND NOT THE UPL'S OWN GENERATOR
    These are standard, known signals that exercise the *whole* digital chain at
    exactly 44.1 kHz/16-bit. Track 4 in particular steps 1 kHz down to -91.2 dBFS,
    the bottom of the 16-bit range, which is where DAC dither and truncation
    behaviour actually shows -- a generated sweep does not probe that.

BIT-EXACT PLAYBACK IS MANDATORY
    Windows shared-mode resampling will quietly invalidate a -91 dBFS reading.
    Use --exclusive (WASAPI exclusive) and check the DUT reports 44.1 kHz, not 48.
    The script refuses to run a linearity test without --exclusive unless you
    pass --allow-shared, because a silently-resampled result looks plausible.

HOW SEGMENTATION WORKS (no timing assumptions)
    Track 4 delimits each level step with a 3 s 2 kHz tone at 0 dBFS. So rather
    than trusting absolute time offsets across USB buffering, this polls the
    UPL's RMS + frequency continuously during playback and segments the stream
    by measured frequency: ~2 kHz = marker, ~1 kHz = level step. The track is
    self-indexing. Same approach works for any stepped-tone track.

LEVELS -- READ THIS
    Several tracks sit at 0 dBFS and the booklet warns they are "much higher
    than conventional program sources". Straight into the UPL analyzer that is
    fine. Through an amplifier it is not. Check before connecting speakers.

NOT YET RUN AGAINST HARDWARE. Use --dry-run to exercise the whole pipeline --
segmentation included -- with no instrument and no audio device.

Examples:
    python scratchpad/upacd_test.py --dry-run linearity
    python scratchpad/upacd_test.py devices
    python scratchpad/upacd_test.py --upl-port COM7 --device 16 --exclusive \
        --label m51_44k linearity -o results/m51_linearity.csv
    python scratchpad/upacd_test.py --upl-port COM7 --device 5 --exclusive \
        --label laptop_builtin linearity -o results/laptop_linearity.csv
    python scratchpad/upacd_test.py --upl-port COM7 --device 16 --exclusive \
        segments --track 6 --tones 20,40,100,200,500,1000,5000,7000,10000,16000,18000,20000
"""

import argparse
import io
import os
import statistics
import sys
import time
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from upl_capture import UPL, DryRunUPL  # noqa: E402


# --- disc knowledge, from the scanned booklet (see CLAUDE.md) ----------------

# Track 4: 2 kHz @ 0 dB marker, then 1 kHz at each of these nominal levels.
TRACK4_MARKER_HZ = 2000.0
TRACK4_STEP_HZ = 1000.0
TRACK4_NOMINAL_DBFS = [-20.0, -30.0, -40.0, -50.0, -60.0, -70.0, -80.1, -85.2, -89.5, -91.2]

# Track 32 multifrequency, -12 dB each, sum level RMS -4.2 dB.
TRACK32_TONES_HZ = [52.5, 315.0, 3150.0, 6300.0, 10080.0, 12600.0]

DEFAULT_ZIP = os.path.join("..", "UPA-CD-20260923T062823Z-1-001.zip")
WAV_PREFIX = "UPA-CD/Wav Files/"


def find_track_wav(zip_path, track):
    """Return (name, bytes) for track N out of the UPA-CD zip."""
    with zipfile.ZipFile(zip_path) as z:
        want = f"{track:02d} - "
        for n in z.namelist():
            base = n[len(WAV_PREFIX):] if n.startswith(WAV_PREFIX) else ""
            if base.startswith(want) and base.lower().endswith(".wav"):
                return base, z.read(n)
    raise SystemExit(f"track {track} not found in {zip_path}")


# --- measurement stream -----------------------------------------------------

def poll_upl(upl, seconds, interval=0.0, verbose=True):
    """Free-run the UPL and collect (t, freq_Hz, level_V) for `seconds`.

    INIT:CONT ON leaves the analyzer measuring continuously; each SENS:DATA? /
    SENS3:DATA? pair then returns the latest result. SENS3 is the frequency
    meter (confirmed mapping from IEC_EXAM/EXAM1.BAS)."""
    out = []
    t0 = time.time()
    while True:
        t = time.time() - t0
        if t >= seconds:
            break
        try:
            lvl = float(upl.query("SENS:DATA?"))
            frq = float(upl.query("SENS3:DATA?"))
        except (ValueError, TimeoutError) as e:
            if verbose:
                print(f"  [{t:6.2f}s] read failed: {e}", file=sys.stderr)
            continue
        if lvl > 1e30 or frq > 1e30:      # 9.93e37 = "not available" sentinel
            continue
        out.append((t, frq, lvl))
        if interval:
            time.sleep(interval)
    return out


def segment(samples, tones, tol=0.05, min_samples=3, min_level_v=0.0):
    """Group a (t, freq, level) stream into runs of one tone each.

    Each sample is labelled with whichever expected tone its measured frequency
    matches within `tol` (fractional), or None. Consecutive same-label samples
    become a run; runs shorter than `min_samples` are dropped as transients
    (settling while the tone changes).

    Returns [{tone, t_start, t_end, n, level_v, level_sd}] in time order.
    Median, not mean -- one settling sample inside a run should not move it."""
    labelled = []
    for t, f, lvl in samples:
        if lvl < min_level_v:
            labelled.append((t, None, lvl))
            continue
        match = None
        for tone in tones:
            if abs(f - tone) <= tol * tone:
                match = tone
                break
        labelled.append((t, match, lvl))

    runs = []
    cur = None
    for t, lab, lvl in labelled:
        if cur is not None and lab == cur["tone"]:
            cur["ts"].append(t)
            cur["levels"].append(lvl)
            continue
        if cur is not None:
            runs.append(cur)
        cur = {"tone": lab, "ts": [t], "levels": [lvl]}
    if cur is not None:
        runs.append(cur)

    out = []
    for r in runs:
        if r["tone"] is None or len(r["levels"]) < min_samples:
            continue
        out.append({
            "tone": r["tone"],
            "t_start": r["ts"][0],
            "t_end": r["ts"][-1],
            "n": len(r["levels"]),
            "level_v": statistics.median(r["levels"]),
            "level_sd": statistics.pstdev(r["levels"]) if len(r["levels"]) > 1 else 0.0,
        })
    return out


# --- playback ---------------------------------------------------------------

class Player:
    """Plays a WAV in the background. In --dry-run it plays nothing."""

    def __init__(self, wav_bytes, device, exclusive, dry_run):
        self.dry_run = dry_run
        self.duration = 0.0
        if dry_run:
            return
        import numpy as np
        import soundfile as sf
        import sounddevice as sd
        data, rate = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=True)
        self.data, self.rate, self.sd = data, rate, sd
        self.duration = len(data) / rate
        self.device = device
        self.extra = sd.WasapiSettings(exclusive=True) if exclusive else None
        self.np = np

    def start(self):
        if self.dry_run:
            return
        kw = {"samplerate": self.rate, "device": self.device, "blocking": False}
        if self.extra is not None:
            kw["extra_settings"] = self.extra
        self.sd.play(self.data, **kw)

    def stop(self):
        if not self.dry_run:
            self.sd.stop()


# --- the synthetic stream used by --dry-run ---------------------------------

def fake_track4_stream(rate_hz=4.0):
    """A plausible measurement stream for track 4, so segmentation can be
    tested offline. 0 dBFS marker = 1.0 V; each step is its nominal level
    with a deliberate +0.4 dB error on the -91.2 dB point, plus a couple of
    settling samples between segments that the run filter must discard."""
    samples, t, dt = [], 0.0, 1.0 / rate_hz
    ref_v = 1.0

    def emit(freq, volts, seconds):
        nonlocal t
        for _ in range(int(seconds * rate_hz)):
            samples.append((t, freq, volts))
            t += dt

    for i, nominal in enumerate(TRACK4_NOMINAL_DBFS):
        emit(TRACK4_MARKER_HZ, ref_v, 3.0)
        samples.append((t, 1480.0, ref_v * 0.5)); t += dt      # settling, unlabelled
        err = 0.4 if nominal == -91.2 else 0.0
        emit(TRACK4_STEP_HZ, ref_v * 10 ** ((nominal + err) / 20.0), 10.0)
        samples.append((t, 1480.0, ref_v * 0.5)); t += dt
    return samples


# --- subcommands ------------------------------------------------------------

def db(v, ref):
    import math
    if v <= 0 or ref <= 0:
        return float("nan")
    return 20.0 * math.log10(v / ref)


def cmd_linearity(upl, args):
    """Track 4: D/A linearity, 1 kHz stepped from -20 down to -91.2 dBFS."""
    if args.dry_run:
        samples = fake_track4_stream()
        print("dry run: using a synthetic track-4 measurement stream", file=sys.stderr)
    else:
        name, wav = find_track_wav(args.zip, 4)
        print(f"track: {name}", file=sys.stderr)
        player = Player(wav, args.device, args.exclusive, args.dry_run)
        configure_analyzer(upl, args)
        print(f"playing {player.duration:.1f}s on device {args.device}"
              f"{' (WASAPI exclusive)' if args.exclusive else ''} ...", file=sys.stderr)
        player.start()
        try:
            samples = poll_upl(upl, player.duration + 1.0)
        finally:
            player.stop()
        print(f"collected {len(samples)} readings", file=sys.stderr)

    runs = segment(samples, [TRACK4_MARKER_HZ, TRACK4_STEP_HZ],
                   tol=args.tol, min_samples=args.min_samples)
    markers = [r for r in runs if r["tone"] == TRACK4_MARKER_HZ]
    steps = [r for r in runs if r["tone"] == TRACK4_STEP_HZ]
    print(f"segmented: {len(markers)} markers (2 kHz), {len(steps)} steps (1 kHz)",
          file=sys.stderr)
    if not markers:
        raise SystemExit("no 2 kHz marker segments found -- is anything reaching the UPL? "
                         "Check the UPL reads a level at all, and that --tol is wide enough.")
    if len(steps) != len(TRACK4_NOMINAL_DBFS):
        print(f"WARNING: expected {len(TRACK4_NOMINAL_DBFS)} level steps, got {len(steps)}. "
              "Levels below the DUT's noise floor do not produce a frequency lock and are "
              "dropped -- which is itself a result.", file=sys.stderr)

    ref_v = statistics.median([m["level_v"] for m in markers])   # the 0 dBFS reference
    rows = []
    for i, st in enumerate(steps):
        nominal = TRACK4_NOMINAL_DBFS[i] if i < len(TRACK4_NOMINAL_DBFS) else float("nan")
        meas = db(st["level_v"], ref_v)
        rows.append((nominal, meas, meas - nominal, st["level_v"], st["n"], st["level_sd"]))

    out = open(args.output, "w") if args.output else sys.stdout
    try:
        out.write(f"# UPA-CD track 4 D/A linearity  dut={args.label}  "
                  f"ref_0dBFS={ref_v:.6g} V  exclusive={args.exclusive}\n")
        out.write("nominal_dBFS,measured_dBFS,error_dB,level_V,samples,level_sd_V\n")
        for n, m, e, v, cnt, sd_ in rows:
            out.write(f"{n},{m:.3f},{e:+.3f},{v:.6g},{cnt},{sd_:.3g}\n")
    finally:
        if args.output:
            out.close()
            print(f"wrote {len(rows)} steps -> {args.output}", file=sys.stderr)

    print("\n nominal   measured    error", file=sys.stderr)
    for n, m, e, _v, _c, _s in rows:
        flag = "  <-- " + ("high" if e > 0 else "low") if abs(e) > args.tolerance_db else ""
        print(f" {n:7.1f}  {m:8.2f}  {e:+7.2f} dB{flag}", file=sys.stderr)
    worst = max((abs(r[2]) for r in rows), default=0.0)
    print(f"\nworst linearity error: {worst:.2f} dB", file=sys.stderr)
    return 0


def cmd_segments(upl, args):
    """Generic: play any stepped-tone track and report one level per tone."""
    tones = [float(t) for t in args.tones.split(",")]
    if args.dry_run:
        samples, t = [], 0.0
        for tone in tones:
            for _ in range(20):
                samples.append((t, tone, 0.5)); t += 0.25
        print("dry run: synthetic stepped-tone stream", file=sys.stderr)
    else:
        name, wav = find_track_wav(args.zip, args.track)
        print(f"track: {name}", file=sys.stderr)
        player = Player(wav, args.device, args.exclusive, args.dry_run)
        configure_analyzer(upl, args)
        player.start()
        try:
            samples = poll_upl(upl, player.duration + 1.0)
        finally:
            player.stop()

    runs = segment(samples, tones, tol=args.tol, min_samples=args.min_samples)
    out = open(args.output, "w") if args.output else sys.stdout
    try:
        out.write(f"# UPA-CD track {args.track}  dut={args.label}\n")
        out.write("tone_Hz,t_start_s,t_end_s,level_V,samples,level_sd_V\n")
        for r in runs:
            out.write(f"{r['tone']},{r['t_start']:.2f},{r['t_end']:.2f},"
                      f"{r['level_v']:.6g},{r['n']},{r['level_sd']:.3g}\n")
    finally:
        if args.output:
            out.close()
            print(f"wrote {len(runs)} segments -> {args.output}", file=sys.stderr)
    for r in runs:
        print(f"  {r['tone']:9.1f} Hz  {r['level_v']:.6g} V  ({r['n']} readings)",
              file=sys.stderr)
    return 0


def configure_analyzer(upl, args):
    """Analog balanced input, RMS + frequency, free-running."""
    upl.write("*RST;*WAI")
    upl.write("INP:TYPE BAL")
    upl.write("SENS1:FUNC 'RMS'")
    upl.write("SENS3:FUNC FREQ")
    upl.write("FORM ASC")
    upl.write("INIT:CONT ON")
    err = upl.query("SYST:ERR?")
    if not err.startswith("0,"):
        print(f"WARNING: UPL error after setup: {err}", file=sys.stderr)


def cmd_devices(upl, args):
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            print(f"  {i:3d}  {d['name']}  ({d['max_output_channels']}ch, "
                  f"{d['default_samplerate']:.0f} Hz, {sd.query_hostapis(d['hostapi'])['name']})")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--upl-port", default="COM7")
    p.add_argument("--device", type=int, help="sounddevice OUTPUT index (see `devices`)")
    p.add_argument("--label", default="dut", help="tag for the CSV, e.g. m51_44k / laptop_builtin")
    p.add_argument("--zip", default=DEFAULT_ZIP, help="UPA-CD zip (tracks are read straight out of it)")
    p.add_argument("--exclusive", action="store_true",
                   help="WASAPI exclusive mode -- required for bit-exact playback")
    p.add_argument("--allow-shared", action="store_true",
                   help="permit a linearity run without --exclusive (results will be suspect)")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--tol", type=float, default=0.05, help="frequency match tolerance, fractional")
    p.add_argument("--min-samples", type=int, default=3, help="readings needed to accept a segment")
    p.add_argument("--tolerance-db", type=float, default=1.0, help="flag linearity errors beyond this")
    p.add_argument("--dry-run", action="store_true",
                   help="no instrument, no audio device: exercise the pipeline on a synthetic stream")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="list output devices")

    lin = sub.add_parser("linearity", help="track 4: D/A linearity down to -91.2 dBFS")
    lin.add_argument("-o", "--output")

    seg = sub.add_parser("segments", help="any stepped-tone track: one level per tone")
    seg.add_argument("--track", type=int, required=True)
    seg.add_argument("--tones", required=True, help="comma-separated expected tones in Hz")
    seg.add_argument("-o", "--output")

    args = p.parse_args()

    if args.cmd == "devices":
        return cmd_devices(None, args)
    if args.cmd == "linearity" and not args.dry_run and not args.exclusive and not args.allow_shared:
        raise SystemExit(
            "refusing to run a linearity test in shared mode.\n"
            "  Windows will resample, and a -91.2 dBFS reading would look plausible but be wrong.\n"
            "  Pass --exclusive (or --allow-shared if you really mean it).")
    if not args.dry_run and args.device is None:
        raise SystemExit("--device is required (run the `devices` subcommand to find it)")

    upl = DryRunUPL(echo=False) if args.dry_run else UPL(args.upl_port, timeout=args.timeout)
    try:
        return {"linearity": cmd_linearity, "segments": cmd_segments}[args.cmd](upl, args)
    finally:
        upl.close()


if __name__ == "__main__":
    sys.exit(main())
