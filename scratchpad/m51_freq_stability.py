#!/usr/bin/env python3
"""
m51_freq_stability.py - proxy jitter/timing-stability check: play a steady
tone through the M51 at a given USB sample rate, and take many rapid
frequency-counter readings from the UPL (SENS3:DATA?) in free-run mode.
Scatter (std dev, peak-to-peak) in the measured frequency is a coarse proxy
for clock jitter/instability -- not a true phase-noise/J-Test measurement,
but real and directly comparable across sample rates.
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
    p.add_argument("--freq", type=float, default=10000.0)
    p.add_argument("--level-dbfs", type=float, default=-1.0)
    p.add_argument("--n", type=int, default=100, help="number of frequency readings")
    p.add_argument("--interval", type=float, default=0.05)
    p.add_argument("-o", "--output", required=True)
    args = p.parse_args()

    dut = M51(args.m51_port)
    orig_volume = dut.get_volume_db()
    dut.set_volume_db(0.0)
    time.sleep(0.3)

    upl = UPL(args.upl_port)
    print("UPL:", upl.query("*IDN?"))
    upl.write("INP:TYPE BAL")
    upl.write("INP:SEL BOTH")
    upl.write("SENS1:FUNCtion 'RMS'")
    upl.write("SENS3:FUNC 'FREQ'")
    upl.write("INIT:CONT ON")  # free-run so repeated queries give fresh values

    t = np.arange(int(args.fs * 1.0)) / args.fs
    amp = 10 ** (args.level_dbfs / 20.0)
    mono = (amp * np.sin(2 * np.pi * args.freq * t)).astype(np.float32)
    stereo = np.column_stack([mono, mono])
    extra = sd.WasapiSettings(exclusive=True)
    print(f"Playing {args.freq} Hz @ {args.level_dbfs} dBFS @ {args.fs} Hz (WASAPI exclusive) ...")
    sd.play(stereo, samplerate=args.fs, device=args.device, loop=True, extra_settings=extra)
    time.sleep(2.0)
    # burn in: discard readings until the counter's gate has caught up with the live tone
    for _ in range(10):
        upl.query("SENS3:DATA?")
        time.sleep(args.interval)

    readings = []
    try:
        for i in range(args.n):
            r = upl.query("SENS3:DATA?")
            try:
                v = float(r.split()[0])
                if abs(v) < 9e36:
                    readings.append(v)
            except ValueError:
                pass
            time.sleep(args.interval)
    finally:
        sd.stop()
        dut.set_volume_db(orig_volume)
        upl.write("INIT:CONT OFF")
        dut.close()
        upl.close()

    arr = np.array(readings)
    with open(args.output, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["reading_idx", "freq_Hz"])
        for i, v in enumerate(arr):
            w.writerow([i, v])

    mean, std, ptp = arr.mean(), arr.std(), np.ptp(arr)
    print(f"\n{len(arr)} readings @ nominal {args.freq} Hz, fs={args.fs}:")
    print(f"  mean   = {mean:.5f} Hz")
    print(f"  stddev = {std:.6f} Hz  ({std/mean*1e6:.3f} ppm)")
    print(f"  p-p    = {ptp:.6f} Hz  ({ptp/mean*1e6:.3f} ppm)")
    print(f"Wrote {len(arr)} readings -> {args.output}")


if __name__ == "__main__":
    sys.exit(main())
