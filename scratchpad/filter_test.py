"""Analyzer-filter checks on internal loopback (INP:TYPE GEN2), over RS-232 or GPIB.

Part A -- bandwidth-limited THD+N. The 2026-09-22 live test defined a 22 kHz
user lowpass and saw THD+N barely move; DEMO.BAS showed why: a user filter
must also be ROUTED into a filter slot (SENS:FILT<i>:UFIL<n> ON). Measured:
no filter / 5 kHz LP defined only / 20, 10, 5, 3 kHz LP routed.
Result 2026-09-24: -106.6 / 20k -106.7 / 10k -108.5 / 5k -110.5 / 3k -112.4 dB --
~1.9 dB per halving, not the 3 dB of white noise, so the residual is LF-heavy.

Part B -- FFT through a filter. White noise from the generator (SOUR:FUNC
RAND, time domain), 8k FFT with averaging, read unfiltered, with the built-in
A-weighting filter, and with a user 1-5 kHz bandpass. The FFT honours up to 3
analyzer filters (Vol.1, FFT column of the filter table).

Usage:
  python scratchpad/filter_test.py --port COM2 -o results/filter_test
Writes <o>_thdn.csv and <o>_fft.csv (freq, one column per filter case).
Sends *RST first; leaves filters off, generator back on sine, 0 V.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from upl_capture import connect, read_fft  # noqa: E402


def cmd(u, c):
    """One command, then *OPC? so nothing else is in flight while it executes
    (compound/slow commands corrupted on the PL2303 -- see CLAUDE.md), then
    SYST:ERR? so a rejected command is reported where it happened."""
    u.write(c)
    u.query("*OPC?")
    e = u.query("SYST:ERR?")
    if not e.startswith("0,"):
        print(f"  !! {c!r} -> {e}")
    return e


def measure(u):
    u.write("INIT:CONT OFF;*WAI")
    u.query("*OPC?")
    return u.query("SENS:DATA?").split()[0]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--averages", type=int, default=16)
    p.add_argument("-o", "--output", default="filter_test")
    args = p.parse_args()
    u = connect(args.port, args.baud, 60.0)
    u.write("*CLS")

    # ---------------- Part A: THD+N with and without a routed user filter
    print("Part A: THD+N, B1 low-distortion sine, 1 kHz, 1 V, internal loopback")
    u.set_timeout(60.0)
    for c in ("*RST;*WAI", "INP:TYPE GEN2", "SOUR:LOWD ON", "SOUR:FREQ 1000 HZ",
              "SOUR:VOLT 1 V", "SENS1:FUNC 'THDN'", "SENS:UNIT DB", "SENS:FILT OFF"):
        cmd(u, c)
    rows = []

    def case(label):
        v = measure(u)
        print(f"  {label:34s} THD+N = {v} dB")
        rows.append((label, v))

    # Live 2026-09-24: a 22 kHz LP is accepted when defined but rejected when
    # routed (111 "Error in Filter specification" -- too close to A22's band
    # edge), and the filter then refuses further changes (-222). <= 20 kHz is
    # fine. So: filters off, define type + cutoff, THEN route, per case.
    case("no filter")
    cmd(u, "SENS:UFIL1:LPAS ON")
    cmd(u, "SENS:UFIL1:PASS 5000 HZ")
    case("5 kHz LP defined, NOT routed")
    for fc in (20000, 10000, 5000, 3000):
        cmd(u, "SENS:FILT OFF")
        cmd(u, "SENS:UFIL1:LPAS ON")
        cmd(u, f"SENS:UFIL1:PASS {fc} HZ")
        cmd(u, "SENS:FILT1:UFIL1 ON")
        case(f"{fc // 1000} kHz LP routed (FILT1:UFIL1)")
    cmd(u, "SENS:FILT OFF")
    case("filters off again")
    with open(args.output + "_thdn.csv", "w") as f:
        f.write("case,thdn_dB\n")
        f.writelines(f"{a},{b}\n" for a, b in rows)

    # ---------------- Part B: FFT of white noise through filters
    print("\nPart B: 8k FFT of white noise, unfiltered / A-weighting / 1-5 kHz bandpass")
    for c in ("SOUR:LOWD OFF", "SOUR:FUNC RAND", "SOUR:RAND:DOM TIME", "SOUR:VOLT:TOT 1 V",
              "SENS1:FUNC 'FFT'", "CALC:TRAN:FREQ:FFT S8K",
              "CALC:TRAN:FREQ:WIND BLAC", "CALC:TRAN:FREQ:ZOOM 1",
              f"CALC:TRAN:FREQ:AVER {args.averages}", "FORM ASC"):
        cmd(u, c)
    cases = {
        "unfiltered": ["SENS:FILT OFF"],
        "A-weighting": ["SENS:FILT OFF", "SENS:FILT1:AWE ON"],
        "bandpass 1-5 kHz": ["SENS:FILT OFF", "SENS:UFIL2:BPAS ON",
                             "SENS:UFIL2:PASS:LOW 1000 HZ", "SENS:UFIL2:PASS:UPP 5000 HZ",
                             "SENS:FILT1:UFIL2 ON"],
    }
    spectra, freqs = {}, None
    for name, setup in cases.items():
        for c in setup:
            cmd(u, c)
        u.set_timeout(180.0)
        u.write("INIT:CONT OFF;*WAI")
        u.query("*OPC?")
        u.set_timeout(30.0)
        f, v = read_fft(u)
        print(f"  {name:18s} {len(f)} lines, {f[0]:.0f}-{f[-1]:.0f} Hz")
        freqs = freqs or f
        spectra[name] = v
    with open(args.output + "_fft.csv", "w") as fh:
        fh.write("freq_Hz," + ",".join(spectra) + "\n")
        for i, fr in enumerate(freqs):
            fh.write(f"{fr}," + ",".join(str(s[i]) if i < len(s) else "" for s in spectra.values())
                     + "\n")

    # ---------------- leave it tidy
    for c in ("SENS:FILT OFF", "SOUR:FUNC SIN", "SOUR:VOLT 0 V"):
        cmd(u, c)
    u.close()
    print(f"\nwrote {args.output}_thdn.csv and {args.output}_fft.csv")


if __name__ == "__main__":
    sys.exit(main())
