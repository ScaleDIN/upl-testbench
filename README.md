# R&S UPL Audio Analyzer — Remote Control & Test Suite

Tools for driving a Rohde & Schwarz UPL audio analyzer from a modern PC over its RS232 remote
port, pulling data off it, and using it to automatically characterize other gear (a Behringer
DCX2496 crossover, a NAD M51 DAC) via serial-controlled DUTs + UPL measurements. Background,
firmware analysis, and the full narrative of how everything here was discovered/verified is in
`CLAUDE.md` — this file is the "how do I actually run things" reference.

For the UPL's own self-test, see the standalone **[SELFTEST_README.md](SELFTEST_README.md)**.

## Setup

```bash
python -m pip install pyserial numpy scipy sounddevice soundfile
```

Each tool takes `--port` (or `--upl-port`/`--dcx-port`/`--m51-port` when more than one device is
involved). **COM port assignment is whatever your USB-serial adapters currently enumerate as** —
it's not fixed; check with:

```bash
python -c "import serial.tools.list_ports as lp; print([(p.device, p.description) for p in lp.comports()])"
```

If a port that worked before now fails to open with a `FileNotFoundError`/"file not found" from
pyserial, that's a known intermittent USB-serial driver quirk (seen on both a Prolific and an
FTDI adapter in testing) — reboot the PC, plug the adapter into a direct USB port (not a hub),
and disable "allow the computer to turn off this device" under that device's and each USB Root
Hub's Power Management in Device Manager. See `CLAUDE.md`'s "Current live wiring" section for the
full troubleshooting history.

## Core control libraries

These provide the `import`-able classes the test scripts build on. Each is also a standalone CLI.

| File | What it talks to | Protocol |
|---|---|---|
| `upl_capture.py` | R&S UPL, RS232 remote | SCPI, LF-terminated, 115200 8N1 RTS/CTS |
| `dcx2496.py` | Behringer DCX2496, RS232 | MIDI-SysEx-style, 38400 8N1 (unofficial, reverse-engineered — see `dcx2496_protocol.md`) |
| `nad_m51.py` | NAD M51 DAC, RS232 | ASCII `Var=Value`/`Var?`, 115200 8N1, no flow control |
| `ser_in.py` | receives a file the UPL pushes via its `SNDFILE.BAS` macro | raw bytes, 115200, idle-timeout framing |

Quick examples:

```bash
# UPL: confirm remote control is live, read a value, pull a sweep to CSV
python upl_capture.py --port COM7 probe
python upl_capture.py --port COM7 raw "SYST:ERR?"
python upl_capture.py --port COM7 autoexport -o sweep.csv

# DCX2496: enable remote, nudge a gain, set a crossover point
python dcx2496.py --port COM2 enable
python dcx2496.py --port COM2 gain out1 -6.0
python dcx2496.py --port COM2 xover out1 500 --type lr24

# NAD M51: query/set volume and source
python nad_m51.py --port COM2 volume
python nad_m51.py --port COM2 volume -3
python nad_m51.py --port COM2 source
```

`upl_capture.py --help`, `dcx2496.py --help`, `nad_m51.py --help` list every subcommand.

## UPL self-test

See **[SELFTEST_README.md](SELFTEST_README.md)** — `upl_selftest.py`, fully documented there.

## Soundcard audio-analyzer suite

`audio_tests.py` — a UPL-style measurement suite (level, THD, THD+N, SNR, frequency response,
crosstalk) that runs against *this PC's own soundcard*, a WAV file, or synthetically. Useful for
a quick sanity check without any external instrument, or for the "laptop as generator" half of a
UPL-as-analyzer setup.

```bash
python audio_tests.py devices          # list audio devices, find the right index
python audio_tests.py selftest         # validate the analyzer math on a synthetic signal (no sound)
python audio_tests.py analyze some.wav
python audio_tests.py noise            # record input noise floor (no sound played)
python audio_tests.py loopback --freq 1000 --level -6   # PLAYS a tone and records it
python audio_tests.py response -o sweep.csv             # PLAYS a stepped-sine sweep
```

## DCX2496 crossover/EQ characterization

Physical setup for all of the DCX2496 tests below: **UPL generator output → DCX2496 input A**;
**DCX2496 output N → UPL analyzer input** (both XLR balanced). This makes the UPL both the
generator and the analyzer, with the DCX2496 as the device under test in between.

**`dcx_sweep.py`** — the general-purpose permanent tool. Sets a DCX2496 crossover (and/or gain),
runs a UPL level-vs-frequency sweep, saves CSV. Handles one curve or a family of curves (e.g.
several highpass cutoffs) in one run.

```bash
# one highpass curve, cutoff isolated (lowpass disabled)
python dcx_sweep.py --dcx-port COM2 --upl-port COM7 --out-ch out1 \
    --hp-freq 500 --hp-type lr24 --lp-type off -o sweep_500hz.csv

# a family of cutoffs in one run (one CSV column per cutoff)
python dcx_sweep.py --dcx-port COM2 --upl-port COM7 --out-ch out1 \
    --hp-freq 100,300,1000,3000 --hp-type lr24 --lp-type off -o family.csv

# just re-measure whatever the DCX is currently configured to, no writes at all
python dcx_sweep.py --dcx-port COM2 --upl-port COM7 --out-ch out1 --no-configure -o asis.csv
```

**Before trusting a result**, `dcx_sweep.py` prints a warning if the UPL looks like it's in an
unexpected instrument state (`INST?`/`INST2?`/`INP:TYPE?`) — a flat, implausible result across
the whole sweep usually means the UPL got left in a leftover digital-instrument state from a
previous test (fix: `*RST`), and an all-noise-floor result with no frequency lock usually means
the DCX2496 output is muted (fix: `dcx2496.py --port COM2 mute out1 off`). Both were real bugs
hit during development — see `CLAUDE.md`, "FIRST REAL AUTOMATED CROSSOVER MEASUREMENT."

**`scratchpad/` DCX2496 tests** — more specific characterizations, each a standalone script:

```bash
# THD+N vs frequency and vs level, flat passthrough
python scratchpad/dcx_thdn.py --dcx-port COM2 --upl-port COM7 -o results/dcx_thdn.csv

# separates THD+N into pure THD (harmonics) vs noise contribution, vs frequency --
# use this instead of dcx_thdn.py if you want to know whether a bad number is really
# distortion or just the DCX's noise floor (see CLAUDE.md for what this revealed)
python scratchpad/dcx_thd_vs_thdn.py --dcx-port COM2 --upl-port COM7 -o results/dcx_thd_vs_thdn.csv

# gain accuracy (+/-15dB), filter-type comparison (Butterworth/Bessel/Linkwitz-Riley
# at several orders), and limiter behavior, all in one run
python scratchpad/dcx_gauntlet.py --dcx-port COM2 --upl-port COM7 -o results/dcx_gauntlet.json

# balanced (XLR direct) vs single-ended (via XLR-to-RCA-to-XLR adapters) comparison --
# run once per physical wiring state with a different mode label
python scratchpad/dcx_balanced_test.py balanced     --dcx-port COM2 --upl-port COM7
python scratchpad/dcx_balanced_test.py single_ended --dcx-port COM2 --upl-port COM7
```

`dcx_balanced_test.py` warns inline if a run's level is near the noise floor with THD+N near
0dB — that pattern means the signal isn't actually reaching the analyzer (check the physical
adapter chain), not a real balanced/unbalanced difference.

## NAD M51 DAC characterization

Physical setup: laptop → USB → M51 (as the digital source) → M51 analog balanced output → UPL
analyzer input. M51 is controlled over RS232 (volume, source) while the UPL reads the result;
the test tone itself is generated on the laptop and played out over USB to the M51 (find the
right `sounddevice` output index with `python audio_tests.py devices` first, or use
`--exclusive` for WASAPI exclusive mode when you need a bit-exact 96k/192k rate rather than
whatever Windows' own resampler produces).

```bash
# frequency response + THD+N-vs-frequency at a given USB sample rate
python scratchpad/m51_freq_response.py --fs 48000 --device 16 -o results/m51_fr_48k.csv

# THD+N/THD/noise vs the M51's own volume setting -- finds the best gain to leave
# it at when something downstream handles level control
python scratchpad/m51_gain_sweep.py --device 16 --fs 48000 -o results/m51_gain_sweep_48k.csv

# CCIF twin-tone IMD (19k+20k by default) via the UPL's DFD analyzer function
python scratchpad/m51_imd.py --fs 48000 --device 16

# frequency-counter scatter across many rapid readings -- a coarse jitter/clock-
# stability proxy, directly comparable across sample rates
python scratchpad/m51_freq_stability.py --fs 96000 --device 16 -o results/m51_jitter_96k.csv

# FFT-based sideband/jitter check (needs CALC:TRAN:FREQ:ZOOM 1 -- see the script's
# docstring for a hard-won firmware quirk about which zoom mode actually works)
python scratchpad/m51_jitter_fft.py --fs 44100 --device 16 -o results/m51_jitter_fft_44k.csv
```

All M51 scripts default `--m51-port COM2 --upl-port COM7` — override if your ports differ.
`--fs` is required on most of them (the whole point is comparing behavior across sample rates).

## Data-egress tools (getting files off the UPL)

- `upl_capture.py autoexport` — triggers a fresh sweep and pulls trace + x-axis straight over the
  wire to CSV, no file ever created on the UPL. The simplest, most reliable option.
- `ser_in.py` — for the R&S-documented `SNDFILE.BAS`/`SER_IN.EXE` file-transfer mechanism (pulling
  an actual file that already exists on the UPL's disk). `SER_IN.EXE` is 16-bit DOS and won't run
  on modern 64-bit Windows; `ser_in.py` is the Python reimplementation. See its docstring for the
  manual front-panel trigger sequence (the reliable one) vs. the remote/SCPI trigger sequence
  (untested — see `CLAUDE.md` for the port-contention caveat).

## Where things are documented

- **`CLAUDE.md`** — the full working log: firmware/hardware analysis, every SCPI command
  confirmed and how, every bug hit and its fix, every measurement result with its reference
  numbers, and the reasoning behind every tool's design. The authoritative source if this README
  and the code ever disagree.
- **`dcx2496_protocol.md`** — the DCX2496's full reverse-engineered serial protocol, verbatim.
- **`SELFTEST_README.md`** — standalone guide for `upl_selftest.py`.
- **`Application Notes/`, the two operating manual PDFs, and the R&S brochure/spec sheet** (one
  directory up) — original R&S documentation; `CLAUDE.md` has a topic-by-topic catalog of what's
  in the Application Notes folder specifically.
