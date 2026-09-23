#!/usr/bin/env python3
"""
m51_freq_response.py - audible-band frequency response + THD+N-vs-frequency of
the M51, at a chosen USB sample rate, via WASAPI exclusive (bit-exact rate) +
UPL analog analyzer. Used to check whether 96k/192k measure any differently
from 44.1k/48k in the band that actually matters (20 Hz - 20 kHz), i.e.
whether the higher-rate "benefit" is real or just perceived.
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

SENTINEL = 9e36


def parse_upl(s):
    tok = s.strip().split()[0]
    v = float(tok)
    return None if abs(v) > SENTINEL else v


def upl_trigger_read(upl, func, ch1_cmd="SENS:DATA?", ch2_cmd="SENS:DATA2?"):
    upl.write(f"SENS1:FUNCtion '{func}'")
    upl.write("INIT:CONT OFF")
    upl.write("INIT;*WAI")
    time.sleep(0.15)
    return parse_upl(upl.query(ch1_cmd)), parse_upl(upl.query(ch2_cmd))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--m51-port", default="COM2")
    p.add_argument("--upl-port", default="COM7")
    p.add_argument("--device", type=int, default=16)
    p.add_argument("--fs", type=int, required=True)
    p.add_argument("--volume-db", type=float, default=0.0)
    p.add_argument("--level-dbfs", type=float, default=-6.0)
    p.add_argument("--start", type=float, default=20.0)
    p.add_argument("--stop", type=float, default=20000.0)
    p.add_argument("--points", type=int, default=30)
    p.add_argument("--dwell", type=float, default=0.35)
    p.add_argument("-o", "--output", required=True)
    args = p.parse_args()

    dut = M51(args.m51_port)
    orig_volume = dut.get_volume_db()
    dut.set_volume_db(args.volume_db)
    time.sleep(0.3)
    print(f"M51: source={dut.get_source()!r} volume set to {args.volume_db} dB (was {orig_volume})")

    upl = UPL(args.upl_port)
    print("UPL:", upl.query("*IDN?"))
    upl.write("INP:TYPE BAL")
    upl.write("INP:SEL BOTH")
    upl.write("SENS:VOLT:RANG:AUTO ON")

    extra = sd.WasapiSettings(exclusive=True)
    freqs = np.geomspace(args.start, min(args.stop, args.fs / 2 * 0.95), args.points)
    amp = 10 ** (args.level_dbfs / 20.0)

    rows = []
    try:
        for f in freqs:
            target_s = 1.0
            n_cycles = max(1, round(target_s * f))
            n = int(round(n_cycles * args.fs / f))  # whole cycles, ~1s buffer regardless of freq
            t = np.arange(n) / args.fs
            mono = (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)
            stereo = np.column_stack([mono, mono])
            sd.play(stereo, samplerate=args.fs, device=args.device, loop=True, extra_settings=extra)
            time.sleep(args.dwell + 0.5)  # extra settle past the reset transient
            lvl1, lvl2 = upl_trigger_read(upl, "RMS")
            time.sleep(0.2)
            thdn1, thdn2 = upl_trigger_read(upl, "THDN")
            sd.stop()
            rows.append(dict(freq_Hz=f, level_L_V=lvl1, level_R_V=lvl2, thdn_L_dB=thdn1, thdn_R_dB=thdn2))
            print(f"  {f:9.1f} Hz : L={lvl1 if lvl1 else float('nan'):.5f} V  THD+N(L)={thdn1 if thdn1 else float('nan'):7.2f} dB")
    finally:
        sd.stop()
        dut.set_volume_db(orig_volume)
        dut.close()
        upl.close()

    ref = next((r["level_L_V"] for r in rows if 900 < r["freq_Hz"] < 1100), rows[len(rows)//2]["level_L_V"])
    with open(args.output, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["freq_Hz", "level_dB_rel_1k", "level_L_V", "level_R_V", "thdn_L_dB", "thdn_R_dB"])
        w.writeheader()
        for r in rows:
            rel = 20 * np.log10(r["level_L_V"] / ref) if (r["level_L_V"] and ref) else ""
            w.writerow(dict(freq_Hz=r["freq_Hz"], level_dB_rel_1k=rel, **{k: r[k] for k in ("level_L_V","level_R_V","thdn_L_dB","thdn_R_dB")}))
    print(f"Wrote {len(rows)} points -> {args.output}")


if __name__ == "__main__":
    sys.exit(main())
