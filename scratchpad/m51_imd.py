#!/usr/bin/env python3
"""
m51_imd.py - CCIF-style twin-tone intermodulation (IMD) test on the M51's
analog output, at a given USB sample rate.

Classic CCIF pair: 19 kHz + 20 kHz, equal amplitude -> looks at the 1 kHz
difference-tone IM product (and higher-order products) via the UPL's DFD
analyzer function. UPL's own generator must be set to SOUR:FUNC DFD to make
SOUR:FREQ:MEAN/DIFF valid (they're DFD-mode generator parameters used here
purely as the analyzer's frequency reference) -- but its output is muted
(SOUR:VOLT:TOT ~0) since the actual two-tone signal comes from the M51 via
USB, not the UPL's own generator.
"""
import argparse
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
    p.add_argument("--f1", type=float, default=19000.0)
    p.add_argument("--f2", type=float, default=20000.0)
    p.add_argument("--level-dbfs", type=float, default=-7.0, help="level of EACH tone")
    args = p.parse_args()

    mean = (args.f1 + args.f2) / 2.0
    diff = abs(args.f2 - args.f1)

    dut = M51(args.m51_port)
    orig_volume = dut.get_volume_db()
    dut.set_volume_db(0.0)
    time.sleep(0.3)
    print(f"M51: source={dut.get_source()!r}, volume=0 dB (was {orig_volume})")

    upl = UPL(args.upl_port)
    print("UPL:", upl.query("*IDN?"))
    upl.write("INP:TYPE BAL")
    upl.write("SOUR:FUNC DFD")
    upl.write("SOUR:VOLT:TOT 1e-20 V")  # mute the UPL's own generator; not used
    upl.write(f"SOUR:FREQ:MEAN {mean}")
    upl.write(f"SOUR:FREQ:DIFF {diff}")
    upl.write("SENS1:FUNCtion 'DFD'")
    err = upl.query("SYST:ERR?")
    print("UPL SYST:ERR? ->", err)

    t = np.arange(int(args.fs * 1.0)) / args.fs
    amp = 10 ** (args.level_dbfs / 20.0)
    mono = (amp * np.sin(2 * np.pi * args.f1 * t) + amp * np.sin(2 * np.pi * args.f2 * t)).astype(np.float32)
    stereo = np.column_stack([mono, mono])
    extra = sd.WasapiSettings(exclusive=True)
    print(f"Playing {args.f1}+{args.f2} Hz @ {args.level_dbfs} dBFS each, {args.fs} Hz (WASAPI exclusive) ...")
    sd.play(stereo, samplerate=args.fs, device=args.device, loop=True, extra_settings=extra)
    time.sleep(1.0)

    try:
        upl.write("INIT:CONT OFF")
        upl.write("INIT")
        upl.query("*OPC?")
        dfd1 = upl.query("SENS:DATA?")
        dfd2 = upl.query("SENS:DATA2?")
        upl.write("SENS1:FUNCtion 'RMS'")
        upl.write("INIT:CONT OFF"); upl.write("INIT"); upl.query("*OPC?")
        lvl1 = upl.query("SENS:DATA?")
    finally:
        sd.stop()
        dut.set_volume_db(orig_volume)
        dut.close()
        upl.close()

    print(f"\nCCIF IMD (f1={args.f1:.0f} Hz, f2={args.f2:.0f} Hz, diff={diff:.0f} Hz):")
    print(f"  DFD (L) : {dfd1}")
    print(f"  DFD (R) : {dfd2}")
    print(f"  Level (L, combined): {lvl1}")


if __name__ == "__main__":
    sys.exit(main())
