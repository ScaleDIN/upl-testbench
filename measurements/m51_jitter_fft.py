#!/usr/bin/env python3
"""
m51_jitter_fft.py (v2) - sideband/jitter check on the M51's analog output,
using the UPL's FFT function.

RESOLVED 2026-09-23 -- the "FFT zoom quirk" was not a firmware quirk.

What was previously recorded here: only ZOOM 1 gave a trustworthy readout;
ZOOM>1 + CENTer left the peak "stuck at silence-floor level, no consistent
axis"; CALC:TRAN:FREQ:STARt?/STOP? described "a wider theoretical span than
what TRAC1 actually returns"; usable range was "0 - ~6000 Hz".

All three symptoms are one cause: **TRAC? returns at most 1024 values**
(Vol.2 sec 3.15.11.2.1). An 8k FFT has 3744 lines unzoomed-analog and 7488
zoomed (Vol.1 sec 2.6.5.12: size*117/256, x2 when zooming). A single TRAC?
therefore hands back only the FIRST block -- silently, no error:
  - unzoomed: block 0 = lines 0..1023 = 0 .. 1024*5.859375 = 5999.9 Hz.
    That IS the "0 - ~6000 Hz" limit, exactly.
  - zoomed:   block 0 is the bottom eighth of the zoom span, nowhere near
    CENTer -- so the tone is in a middle block and block 0 shows noise floor.
    That IS "peak stuck at silence-floor level".
  - STARt?/STOP? were right all along: they describe the whole FFT, while
    TRAC? was returning one block of it.

Fix: select the block with DISP:TRAC:IND <0..7> before each read and
concatenate (Vol.2 sec 3.15.11.2.2, which has R&S's own 8-block loop), and
take the X axis from TRAC? LIST1 per block instead of computing bin*resolution
-- LIST1 is correct for zoomed FFTs too, where the block does not start at 0 Hz.
upl_capture.read_fft() does this; this script now uses it, so the spectrum
covers the full 0 - 21.9 kHz and --zoom is usable.

NOT YET RE-RUN AGAINST THE INSTRUMENT since the change.
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
from upl_capture import UPL, read_fft, fft_line_count


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--m51-port", default="COM2")
    p.add_argument("--upl-port", default="COM7")
    p.add_argument("--device", type=int, default=16)
    p.add_argument("--fs", type=int, required=True)
    p.add_argument("--freq", type=float, default=3000.0)
    p.add_argument("--level-dbfs", type=float, default=-1.0)
    p.add_argument("--zoom", type=int, default=1,
                   help="FFT zoom factor: 1 = off. >1 needs --center; now usable thanks to block paging")
    p.add_argument("--center", type=float,
                   help="zoom center frequency in Hz (defaults to --freq when --zoom > 1)")
    p.add_argument("-o", "--output", required=True)
    args = p.parse_args()
    if args.zoom > 1 and args.center is None:
        args.center = args.freq

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
    if args.center is not None:
        upl.write(f"CALC:TRAN:FREQ:CENT {args.center} HZ")
    # Over the bus you set the zoom FACTOR, not the SPAN (Vol.2 p.3.134).
    upl.write(f"CALC:TRAN:FREQ:ZOOM {args.zoom}")
    upl.write("FORM ASCii")
    res = float(upl.query("CALC:TRAN:FREQ:RESolution?").split()[0])
    expect = fft_line_count(8192, args.zoom)
    print(f"FFT resolution: {res:.4f} Hz/bin, expecting up to {expect} lines "
          f"({-(-expect // 1024)} block(s))")

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
        # Pages DISP:TRAC:IND 0..7 -- a bare TRAC? would truncate at 1024 lines.
        f_list, y_list = read_fft(upl, verbose=True)
        freqs = np.array(f_list)
        trace = np.array(y_list)
    finally:
        sd.stop()
        dut.set_volume_db(orig_volume)
        dut.close()
        upl.close()

    # Frequency axis comes from TRAC? LIST1 per block, not bin*res -- correct for
    # zoomed FFTs too, where a block does not start at 0 Hz.
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
