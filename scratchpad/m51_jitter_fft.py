#!/usr/bin/env python3
"""
m51_jitter_fft.py (v2) - sideband/jitter check on the M51's analog output,
using the UPL's FFT function.

IMPORTANT, hard-won: only CALC:TRAN:FREQ:ZOOM 1 (unzoomed) gives a trustworthy
TRAC1 readout on this firmware -- validated live against 4 known tones (1k,
2k, 3k, 5.5kHz), all landing within 1 bin (5.859375 Hz, for FFT size S8K) of
truth, with correct amplitude (~2.8-3V vs ~2e-5 silence floor). The zoomed/
centered mode (ZOOM>1 + CENTer) was tried and found unreliable (peak stuck at
silence-floor level, no consistent axis) -- not used here.
Frequency axis for TRAC1 in this (zoom=1) mode: freq = bin_index * resolution,
starting at 0 Hz (NOT the CALC:TRAN:FREQ:STARt?/STOP? values, which describe
a wider theoretical span than what TRAC1 actually returns -- another firmware
quirk). Usable range at S8K/zoom=1 @ 1024 returned points: 0 - ~6000 Hz.
"""
import argparse
import csv
import sys
import time
import numpy as np
import sounddevice as sd

sys.path.insert(0, "..")
sys.path.insert(0, ".")
from nad_m51 import M51
from upl_capture import UPL


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--m51-port", default="COM2")
    p.add_argument("--upl-port", default="COM7")
    p.add_argument("--device", type=int, default=16)
    p.add_argument("--fs", type=int, required=True)
    p.add_argument("--freq", type=float, default=3000.0)
    p.add_argument("--level-dbfs", type=float, default=-1.0)
    p.add_argument("-o", "--output", required=True)
    args = p.parse_args()

    dut = M51(args.m51_port)
    orig_volume = dut.get_volume_db()
    dut.set_volume_db(0.0)
    time.sleep(0.3)
    print(f"M51: source={dut.get_source()!r}, volume=0 dB (was {orig_volume})")

    upl = UPL(args.upl_port, timeout=15.0)
    print("UPL:", upl.query("*IDN?"))
    upl.write("INP:TYPE BAL")
    upl.write("SENS1:FUNCtion 'FFT'")
    upl.write("CALC:TRAN:FREQ:WINDow BLACkman_harris")
    upl.write("CALC:TRAN:FREQ:FFT S8K")
    upl.write("CALC:TRAN:FREQ:ZOOM 1")
    upl.write("FORM ASCii")
    res = float(upl.query("CALC:TRAN:FREQ:RESolution?").split()[0])
    print(f"FFT resolution: {res:.4f} Hz/bin")

    t = np.arange(int(args.fs * 1.0)) / args.fs
    amp = 10 ** (args.level_dbfs / 20.0)
    mono = (amp * np.sin(2 * np.pi * args.freq * t)).astype(np.float32)
    stereo = np.column_stack([mono, mono])
    extra = sd.WasapiSettings(exclusive=True)
    print(f"Playing {args.freq} Hz @ {args.level_dbfs} dBFS on device {args.device} @ {args.fs} Hz (WASAPI exclusive) ...")
    sd.play(stereo, samplerate=args.fs, device=args.device, loop=True, extra_settings=extra)
    time.sleep(1.0)

    try:
        upl.write("INIT:CONT OFF")
        upl.write("INIT")
        upl.query("*OPC?")  # genuinely blocks until the FFT acquisition is done
        raw = upl.query("TRAC? TRAC1")
        trace = np.array([float(x) for x in raw.split(",") if x.strip()])
    finally:
        sd.stop()
        dut.set_volume_db(orig_volume)
        dut.close()
        upl.close()

    freqs = np.arange(len(trace)) * res
    with open(args.output, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_Hz", "level_V"])
        for f, v in zip(freqs, trace):
            w.writerow([f"{f:.4f}", v])
    print(f"Wrote {len(trace)} bins -> {args.output}")

    k0 = int(np.argmax(trace))
    fundamental = trace[k0]
    noise_floor = np.median(trace)
    print(f"Fundamental: {freqs[k0]:.2f} Hz @ {fundamental:.4f} V  (median floor {noise_floor:.2e} V, "
          f"{20*np.log10(fundamental/noise_floor):.1f} dB above it)")
    mask = np.ones(len(trace), dtype=bool)
    mask[max(0, k0 - 3):k0 + 4] = False  # exclude the fundamental's own bins
    order = np.argsort(np.where(mask, trace, -1.0))[::-1][:8]
    print("Top spurs (freq Hz, level V, level rel. fundamental dB):")
    for idx in order:
        rel = 20 * np.log10(trace[idx] / fundamental) if trace[idx] > 0 else float("-inf")
        print(f"  {freqs[idx]:9.2f} Hz  {trace[idx]:.4e} V   {rel:+7.2f} dB")


if __name__ == "__main__":
    sys.exit(main())
