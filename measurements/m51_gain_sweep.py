#!/usr/bin/env python3
"""
m51_gain_sweep.py - characterize the NAD M51's THD+N/THD/noise vs its own
Main.Volume setting, to find the best gain to leave it at when a downstream
preamp handles level control.

Signal path: laptop (USB, PC LINK/"USB" source) -> M51 analog balanced out
-> UPL analyzer CH1 (L) / CH2 (R). M51 volume is swept over RS232 (COM2, no
flow control); UPL is read over RS232 (COM7, RTS/CTS). A continuous test tone
is looped out the M51's USB input for the whole sweep.

Usage:
  python measurements/m51_gain_sweep.py --m51-port COM2 --upl-port COM7 --device 15
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

SENTINEL = 9e36  # UPL "N/A" sentinel is ~9.93e37; anything absurdly large = not available


def parse_upl(s):
    tok = s.strip().split()[0]
    v = float(tok)
    return None if abs(v) > SENTINEL else v


def upl_trigger_read(upl, func, ch1_cmd="SENS:DATA?", ch2_cmd="SENS:DATA2?"):
    upl.write(f"SENS1:FUNCtion '{func}'")
    upl.write("INIT:CONT OFF")
    upl.write("INIT;*WAI")
    time.sleep(0.15)
    c1 = parse_upl(upl.query(ch1_cmd))
    c2 = parse_upl(upl.query(ch2_cmd))
    return c1, c2


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--m51-port", default="COM2")
    p.add_argument("--upl-port", default="COM7")
    p.add_argument("--device", type=int, default=None, help="sounddevice output index for the M51")
    p.add_argument("--exclusive", action="store_true", help="use WASAPI exclusive mode (bypasses Windows resampler -- needed for true 96k/192k)")
    p.add_argument("--fs", type=int, default=48000)
    p.add_argument("--freq", type=float, default=1000.0)
    p.add_argument("--level-dbfs", type=float, default=-1.0, help="test tone level, near full-scale by default")
    p.add_argument("--volumes", default="-20,-15,-10,-6,-3,-1,0,1,3,6,10",
                    help="comma list of Main.Volume settings (dB) to test")
    p.add_argument("--settle", type=float, default=0.6)
    p.add_argument("-o", "--output", default="m51_gain_sweep.csv")
    args = p.parse_args()

    volumes = [float(v) for v in args.volumes.split(",")]

    dut = M51(args.m51_port)
    orig_source = dut.get_source()
    orig_volume = dut.get_volume_db()
    print(f"M51: source={orig_source!r} volume={orig_volume} dB (will restore at end)")

    upl = UPL(args.upl_port)
    print("UPL:", upl.query("*IDN?"))
    upl.write("INP:TYPE BAL")
    upl.write("INP:SEL BOTH")
    upl.write("SENS:VOLT:RANG:AUTO ON")
    err = upl.query("SYST:ERR?")
    print("UPL SYST:ERR? ->", err)

    # continuous test tone, looped, out the M51's USB input
    t = np.arange(int(args.fs * 1.0)) / args.fs
    amp = 10 ** (args.level_dbfs / 20.0)
    mono = (amp * np.sin(2 * np.pi * args.freq * t)).astype(np.float32)
    tone = np.column_stack([mono, mono]) if args.exclusive else mono
    play_kwargs = {}
    if args.exclusive:
        play_kwargs["extra_settings"] = sd.WasapiSettings(exclusive=True)
    print(f"Playing {args.freq} Hz @ {args.level_dbfs} dBFS continuously on device {args.device} "
          f"({'WASAPI exclusive' if args.exclusive else 'shared'}) ...")
    sd.play(tone, samplerate=args.fs, device=args.device, loop=True, **play_kwargs)
    time.sleep(0.5)

    rows = []
    try:
        for v in volumes:
            resp = dut.set_volume_db(v)
            time.sleep(args.settle)
            lvl1, lvl2 = upl_trigger_read(upl, "RMS")
            freq1, _ = upl_trigger_read(upl, "RMS", ch1_cmd="SENS3:DATA?", ch2_cmd="SENS3:DATA?")
            thdn1, thdn2 = upl_trigger_read(upl, "THDN")
            thd1, thd2 = upl_trigger_read(upl, "THD")
            row = dict(volume_db=v, level_L_V=lvl1, level_R_V=lvl2, freq_Hz=freq1,
                       thdn_L_dB=thdn1, thdn_R_dB=thdn2, thd_L_dB=thd1, thd_R_dB=thd2)
            rows.append(row)
            print(f"  vol={v:+5.1f}dB  L={lvl1 if lvl1 else float('nan'):.4f}V  "
                  f"THD+N(L)={thdn1 if thdn1 else float('nan'):7.2f}dB  "
                  f"THD(L)={thd1 if thd1 else float('nan'):7.2f}dB  "
                  f"[R: {thdn2 if thdn2 else float('nan'):7.2f} / {thd2 if thd2 else float('nan'):7.2f}]")
    finally:
        sd.stop()
        dut.set_volume_db(orig_volume)
        print(f"Restored M51 volume to {orig_volume} dB")
        dut.close()
        upl.close()

    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {args.output}")

    valid = [r for r in rows if r["thdn_L_dB"] is not None]
    if valid:
        best = min(valid, key=lambda r: r["thdn_L_dB"])
        print(f"\nBest measured THD+N(L): {best['thdn_L_dB']:.2f} dB at volume={best['volume_db']:+.1f} dB")


if __name__ == "__main__":
    sys.exit(main())
