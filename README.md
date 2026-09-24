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
| `ser_in.py` | receives a file the UPL pushes via its `SNDFILE.BAS` macro (superseded by `getfile` / `tools/upl_backup.py`) | raw bytes, 115200, idle-timeout framing |

Quick examples:

```bash
# UPL: confirm remote control is live, read a value, pull a sweep to CSV
python upl_capture.py --port COM7 probe
python upl_capture.py --port COM7 raw "SYST:ERR?"
python upl_capture.py --port COM7 autoexport -o sweep.csv

# UPL: run the instrument's OWN sweep engine
python upl_capture.py --port COM7 nsweep --start 20 --stop 20000 --points 40 -o fr.csv

# UPL: have the instrument save its current trace to its own disk, then pull that file
python upl_capture.py --port COM7 storetrace "C:\UPL\FR.EXP"
python upl_capture.py --port COM7 getfile "C:\UPL\FR.EXP" -o FR.EXP

# UPL: full FFT spectrum, paging past the 1024-line limit
python upl_capture.py --port COM7 fft --size 8192 -o fft.csv

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

**GPIB works too.** Anything that takes a UPL `--port` also accepts a VISA name such as
`GPIB0::20::INSTR` (tested with an Agilent/Keysight 82357B; needs the Keysight IO Libraries Suite
and `pip install pyvisa`). On the UPL: OPTIONS → Remote via → IEC, address 20. GPIB is ~10× faster
than RS‑232 for file transfers; see `CLAUDE.md`, "GPIB (Agilent/Keysight 82357B)", for the gotchas.

### Working offline (`--dry-run`)

Every `upl_capture.py` subcommand takes `--dry-run`, which skips the serial port entirely, prints
the exact SCPI it would send, and answers queries with canned values. No instrument and no `--port`
needed — use it to review a sequence before pointing it at real hardware:

```bash
python upl_capture.py --dry-run nsweep --start 20 --stop 20000 --points 40
```

`python upl_capture.py seqcheck` is the offline regression test: it runs `nsweep` and `storetrace`
through that stub and asserts the emitted SCPI still matches what the manual and the R&S app-note
programs document (right commands, right order, `SWE1` not `SWE2`, `FORM ASC` not `FORM REAL`).

### UPL native sweep vs. host-side stepping

`nsweep` hands the whole sweep to the UPL's internal sweep engine (`SOUR:SWE:MODE AUTO` +
`SOUR:FREQ:MODE SWE1`, one `INIT:CONT OFF;*WAI`, then `TRAC? TRAC1` / `TRAC? LIST1`) instead of
stepping `SOUR:FREQ` from the host in a loop the way `dcx_sweep.py` does. Far fewer round trips —
a 40-point sweep runs in ~11 s inside the instrument.

**Verified live 2026‑09‑23** (internal loopback, flat to ±0.05 % from 20 Hz to 20 kHz). The two
things that made an earlier attempt come back empty were `SWE2` (puts frequency on the *Z* axis)
and a missing `DISP:TRAC:FEED`; both are fixed. Each sweep-parameter command takes 2–3 s on the
instrument, so `nsweep` sends them one at a time with `*OPC?` in between. Don't combine slow
commands on one line over a Prolific adapter: it duplicates bytes when the UPL pauses the
transfer (drops CTS). If a trace does come back empty, the tool says so and names the likely
cause.

### FFT readout: always page the blocks

`TRAC?` returns **at most 1024 values**, but an 8k FFT has 3744 lines (analog, unzoomed) or 7488
(zoomed). A single `TRAC?` therefore gives you only the first block — the bottom ~6 kHz at 48 kHz
sampling — silently, with no error. `DISP:TRAC:IND <0..7>` selects the block; `read_fft()` in
`upl_capture.py` pages them and concatenates, taking the X axis from `TRAC? LIST1` per block.

```bash
python upl_capture.py --dry-run fft --size 8192        # see the paging, offline
python upl_capture.py --port COM7 fft --size 8192 -o fft.csv
python upl_capture.py --port COM7 fft --zoom 8 --center 10000 -o zoomed.csv
```

This is what the "FFT zoom quirk" in `m51_jitter_fft.py` turned out to be — zoom was never broken,
the readout was returning the wrong eighth of it. `CLAUDE.md`'s "FFT zoom quirk RESOLVED" section
has the full arithmetic. Note that over the bus you set the zoom **factor**, never the SPAN
(`CALC:TRAN:FREQ:SPAN?` is query-only).

### Not clobbering the instrument's setup (`--preserve`)

`nsweep` and `fft` start with `*RST`, which throws away whatever you had configured on the front
panel. `--preserve` brackets the whole measurement with a snapshot/restore instead — the idiom R&S
uses in its own shipped `FLAT_GEN.BAS` macro:

```bash
python upl_capture.py --port COM7 --preserve nsweep --points 40 -o fr.csv
```

That sends `MMEM:STOR:STAT 2,'C:\UPL\USER\UPLTMP.SCO'` first (mode 2 = the *complete* setup), does
its thing, then `MMEM:LOAD:STAT 2` + `MMEM:DEL`. Override the scratch path with `--state-file`.
It's opt-in because it writes a file to the instrument's disk.

`nsweep --setup C:\UPL\MYSETUP.SAC` loads a stored setup first (`MMEM:LOAD:STAT 0`) — again how
R&S's own programs configure a measurement, rather than sending every panel setting.

### Backing up per-unit state (`diagdump`)

```bash
python upl_capture.py --dry-run diagdump                          # offline, see what it would do
python upl_capture.py --port COM7 diagdump --devices SERN -o results/diag_sern   # first live run
python upl_capture.py --port COM7 diagdump -o results/diag_full                  # then the full set
```

A **read-only** dump of what looks like the unit's stored identity and calibration — serial number,
calibration tables, the installed option key — using the undocumented `DIAG:DEV` command that
R&S's own selftest uses to read the serial number. The one chip holding this data (an X24164
EEPROM on the Digital Board) is cheap to replace, but its contents aren't; this is the attempt to
back them up without opening the case.

Safety is enforced in code: it can only send the query form (`DATA?`), it refuses selectors that
sound like live hardware access before sending anything, and it checks `SYST:ERR?` after every step.

**Run 2026‑09‑23:** `SERN` (serial) and `INSTkey` (option key) read out; the calibration selectors
(`CAGEn`, `CANLr0`, `CLDG`, `CDPHase`) are refused with `-222`. That turned out not to matter:
the calibration lives in ordinary disk files, which `tools/upl_backup.py` pulls (below). Keep the
output private — it contains the serial and option key; `results/` is git-ignored for that reason.

### Getting a stored file off the UPL

`storetrace` writes the trace to a file on the UPL's own disk via `MMEM:STOR:TRAC` (formats: `exp`
= a plain text table that already includes the X axis, which the UPL itself can't read back; `asc`;
`bin`). `getfile` then pulls any file off the disk with `MMEM:DATA?` and prints the MD5 the UPL
computes for it (`MMEM:CHECK?`) so you can compare. It works over both RS‑232 and GPIB; App Note
1GA42 says this isn't supported, which is wrong for firmware 3.06. For more than a file or two,
use `tools/upl_backup.py`.

For just the numbers, `autoexport` or `nsweep` is simpler, and more precise: `TRAC?` gives 6
significant digits, while an EXPort file has only the 4 digits shown on the display.

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

**`measurements/` DCX2496 tests** — more specific characterizations, each a standalone script:

```bash
# THD+N vs frequency and vs level, flat passthrough
python measurements/dcx_thdn.py --dcx-port COM2 --upl-port COM7 -o results/dcx_thdn.csv

# separates THD+N into pure THD (harmonics) vs noise contribution, vs frequency --
# use this instead of dcx_thdn.py if you want to know whether a bad number is really
# distortion or just the DCX's noise floor (see CLAUDE.md for what this revealed)
python measurements/dcx_thd_vs_thdn.py --dcx-port COM2 --upl-port COM7 -o results/dcx_thd_vs_thdn.csv

# gain accuracy (+/-15dB), filter-type comparison (Butterworth/Bessel/Linkwitz-Riley
# at several orders), and limiter behavior, all in one run
python measurements/dcx_gauntlet.py --dcx-port COM2 --upl-port COM7 -o results/dcx_gauntlet.json

# balanced (XLR direct) vs single-ended (via XLR-to-RCA-to-XLR adapters) comparison --
# run once per physical wiring state with a different mode label
python measurements/dcx_balanced_test.py balanced     --dcx-port COM2 --upl-port COM7
python measurements/dcx_balanced_test.py single_ended --dcx-port COM2 --upl-port COM7
```

`dcx_balanced_test.py` warns inline if a run's level is near the noise floor with THD+N near
0dB — that pattern means the signal isn't actually reaching the analyzer (check the physical
adapter chain), not a real balanced/unbalanced difference.

## UPA-CD test-disc playback (`measurements/upacd_test.py`)

Plays R&S Audio Test Disc tracks from this PC into any DUT while the UPL measures. The DUT is
whatever sits between the sound device and the UPL's analyzer input, so the same script covers the
M51, the DCX2496, or **this laptop's own output** — just point `--device` at a different output and
`--label` the run:

```bash
python measurements/upacd_test.py devices                       # find the output index

# NAD M51 over USB
python measurements/upacd_test.py --upl-port COM7 --device 16 --exclusive \
    --label m51_44k linearity -o results/m51_linearity.csv

# the laptop's own headphone/line output (needs a 3.5mm -> XLR adapter into the UPL)
python measurements/upacd_test.py --upl-port COM7 --device 5 --exclusive \
    --label laptop_builtin linearity -o results/laptop_linearity.csv

# any stepped-tone track, generic
python measurements/upacd_test.py --upl-port COM7 --device 16 --exclusive segments \
    --track 6 --tones 20,40,100,200,500,1000,5000,7000,10000,16000,18000,20000
```

`linearity` runs disc **track 4**, which steps 1 kHz down to **−91.2 dBFS** — the bottom of the
16-bit range, where DAC dither and truncation behaviour shows and a generated sweep does not probe.
It reports measured level and error against nominal for each step.

**No timing assumptions.** Track 4 delimits each level step with a 3 s 2 kHz tone at 0 dBFS, so
rather than trusting absolute offsets across USB buffering the script polls the UPL's RMS +
frequency continuously and segments the stream by measured frequency — the track is self-indexing.
For `linearity` the level is **RMS selective** (a 1 % bandpass fixed at 1 kHz), so noise doesn't
lift the bottom steps, and steps are located **by time between the high-level markers** rather than
by frequency lock, which fails below the noise floor. Levels are referenced to the first step.
A step buried in noise therefore still gets a reading: it just reads high, which is the result.

**Bit-exact playback is mandatory.** Windows shared-mode resampling will quietly invalidate a
−91 dBFS reading, so `linearity` refuses to run without `--exclusive` unless you pass
`--allow-shared`. Check the DUT reports 44.1 kHz, not 48.

Tracks are read straight out of `UPA-CD-….zip` — no need to unpack 809 MB. `--dry-run` exercises
the whole pipeline, segmentation included, with no instrument and no audio device.

**Level warning:** several disc tracks sit at 0 dBFS and the booklet warns they are "much higher
than conventional program sources". Straight into the UPL analyzer that is fine; through an
amplifier into speakers it is not. `CLAUDE.md` has the full track listing.

## Test-signal files for any DAC or player (`tools/testsignals.py`)

Generates a device-agnostic WAV test set, one folder per format (default **44.1/16, 48/24, 96/24,
192/24**, ~1.2 GB total, into `testsignals/`, git-ignored). Each WAV has a JSON sidecar describing
its exact tones, levels and segment times.

```bash
python tools/testsignals.py --list                    # plan + sizes, writes nothing
python tools/testsignals.py                           # all four formats
python tools/testsignals.py --formats 48000/24        # just one
```

| # | File | For |
|---|---|---|
| 01–04 | 1 kHz at −1 / −3 / −20 / −60 dBFS | level, max output, THD+N, AES17 dynamic range |
| 05 | digital silence | noise floor (DACs may auto-mute on it) |
| 06–09 | L-only / R-only, 1 kHz and octave steps | crosstalk, vs frequency |
| 10 | 1/3-octave steps, 20 Hz … 0.465·fs | frequency response, THD vs f (>20 kHz needs `INST2 A100`) |
| 11 | 1 kHz level staircase with 2 kHz markers, to −100 (16-bit) / −120 dBFS (24-bit) | linearity, THD+N vs level |
| 12 / 13 | SMPTE 60 Hz + 7 kHz 4:1 / CCIF 19 + 20 kHz | IMD |
| 14 | J-test (fs/4 + LSB square at fs/192, undithered) | jitter sidebands (zoomed FFT) |
| 15 / 16 | fs/4 at true peak 0 / **+3 dBTP** | intersample-over headroom: compare THD+N |
| 17 / 18 | 1 kHz square, 440 Hz half-waves | filter ringing, absolute polarity |

Dithered files use ±1 LSB TPDF; 14–16 are undithered on purpose. **Several files are near or
(16) above full scale — never with headphones plugged in or speakers connected.**

`measurements/upacd_test.py` plays them with `--wav` (tones and staircase levels come from the
sidecar), or with `--external` just listens while a player plays the file itself:

```bash
# PC plays into a DAC (M51, Elektor, NW-A306 in USB-DAC mode...)
python measurements/upacd_test.py --upl-port COM7 --device 16 --exclusive --label m51_96k \
    --wav testsignals/96k_24/11_level_staircase.wav linearity -o results/m51_lin_96k.csv
# the DUT plays the copied file itself (NW-A306 file playback): press play when told
python measurements/upacd_test.py --upl-port COM7 --external --label a306_96k \
    --wav testsignals/96k_24/10_third_octaves_-6dBFS.wav segments -o results/a306_fr_96k.csv
```

Linearity is referenced to the staircase's first step, not the marker, so the DUT's 1 kHz-vs-2 kHz
response cancels. Verified offline against a simulated DUT with an unknown start delay, markers
rejected by the selective filter and no frequency lock below −90 dBFS: all 15 steps were found,
a planted 0.5 dB error at −100 dBFS came back out, and −120 dBFS read the correct noise-limited
+0.9 dB. Not yet run live.

## NAD M51 DAC characterization

Physical setup: laptop → USB → M51 (as the digital source) → M51 analog balanced output → UPL
analyzer input. M51 is controlled over RS232 (volume, source) while the UPL reads the result;
the test tone itself is generated on the laptop and played out over USB to the M51 (find the
right `sounddevice` output index with `python audio_tests.py devices` first, or use
`--exclusive` for WASAPI exclusive mode when you need a bit-exact 96k/192k rate rather than
whatever Windows' own resampler produces).

```bash
# frequency response + THD+N-vs-frequency at a given USB sample rate
python measurements/m51_freq_response.py --fs 48000 --device 16 -o results/m51_fr_48k.csv

# THD+N/THD/noise vs the M51's own volume setting -- finds the best gain to leave
# it at when something downstream handles level control
python measurements/m51_gain_sweep.py --device 16 --fs 48000 -o results/m51_gain_sweep_48k.csv

# CCIF twin-tone IMD (19k+20k by default) via the UPL's DFD analyzer function
python measurements/m51_imd.py --fs 48000 --device 16

# frequency-counter scatter across many rapid readings -- a coarse jitter/clock-
# stability proxy, directly comparable across sample rates
python measurements/m51_freq_stability.py --fs 96000 --device 16 -o results/m51_jitter_96k.csv

# FFT-based sideband/jitter check (needs CALC:TRAN:FREQ:ZOOM 1 -- see the script's
# docstring for a hard-won firmware quirk about which zoom mode actually works)
python measurements/m51_jitter_fft.py --fs 44100 --device 16 -o results/m51_jitter_fft_44k.csv
```

All M51 scripts default `--m51-port COM2 --upl-port COM7` — override if your ports differ.
`--fs` is required on most of them (the whole point is comparing behavior across sample rates).

## DAC characterization (`measurements/dac_test.py`)

One test suite for any DAC, whatever its digital input. `--source` picks where the test signal
comes from; every measurement and diagnosis is shared, so results are comparable across DACs.
(Renamed from `spdif_dac_test.py` on 2026‑09‑24, when the PC source was added.)

- **`--source upl`** (default), for an S/PDIF (coax/optical) or AES3 input: the **UPL's own
  digital generator (B29)** is the source. It's bit-exact, the UPL sets the sample rate, and
  the interface can be degraded on purpose (jitter via B22, 100 m cable simulator, low signal
  voltage, off-nominal sample rate, 16/20/24-bit words).
- **`--source pc --device N`**, for a USB DAC (NAD M51, Sony NW‑A306 in USB‑DAC mode, the
  laptop's own output…): **this PC synthesizes each tone** and plays it through WASAPI exclusive
  mode as exact integer samples with dither off, so it's bit-exact at the USB input too. Any
  sample rate the device accepts works (e.g. 192000). The UPL can't GENTrack a PC, so selective
  measurements use a FIXed bandpass that follows each tone. `jitter`, `interface` and `polarity`
  need the UPL generator and are skipped. Give it more `--settle` (~0.5 s): a new tone only
  arrives after the audio buffer and the DAC's own latency.

A player that can only play files itself (the NW‑A306's own playback) can't be driven this way;
use `tools/testsignals.py` + `upacd_test.py --external` for that.

Physical setup: UPL digital out (BNC unbal for coax, XLR via 110→75 Ω transformer, or optical)
→ DAC input; DAC L/R analog out → UPL analyzer inputs 1/2. RCA outputs go into the XLR inputs
via adapters; the script uses `INP:LOW FLOat` (see the DCX balanced/single-ended test for why),
`--ground` to change it.

```bash
python measurements/dac_test.py --dry-run all                  # offline: runs everything
python measurements/dac_test.py --port COM7 check              # lock, 0 dBFS level, balance, DC
python measurements/dac_test.py --port COM7 fr                 # frequency response, diagnosed
python measurements/dac_test.py --port COM7 --fs 44100 fft --images
python measurements/dac_test.py --port COM7 --label mydac all  # the lot -- tens of minutes (untimed)

# USB DAC: the PC is the source (find N with `python measurements/upacd_test.py devices`)
python measurements/dac_test.py --port COM7 --source pc --device 16 --fs 44100,96000,192000 \
    --settle 0.6 --label m51_usb all
```

| Test | What it answers |
|---|---|
| `check` | Does it lock at each rate? 0 dBFS output (V), L−R balance, DC offset |
| `fr` | Response 10 Hz–20 kHz per rate, both channels, as **broadband RMS and generator-tracking selective RMS**, repeated. Its summary says whether the problem is L/R mismatch, non-signal energy inflating the RMS reading (images, hum, noise), non-repeatability, or a sinc droop (NOS DAC) |
| `thdn` | THD+N and THD vs level and vs frequency; AES17 dynamic range; idle noise (and whether it mutes on digital zero) |
| `fft` / `fft --images` | Harmonic signature and hum; with `--images`, a 19 kHz tone on the 100 kHz analyzer to see reconstruction-filter images at k·fs ± f |
| `imd` | SMPTE 60 Hz + 7 kHz 4:1, CCIF 19 + 20 kHz |
| `xtalk`, `zout`, `polarity` | Crosstalk both ways; output impedance (200 kΩ vs 600 Ω load); absolute polarity |
| `jitter` | Jitter transfer: sinusoidal jitter (default 0.1 UI) at 100 Hz–8 kHz on an fs/4 tone; sideband level vs the unrejected prediction 20·log(π·f0·J) gives rejection vs jitter frequency. `--cable` repeats with the cable simulator |
| `interface` | Minimum input voltage, sample-rate lock range (±100 ppm to ±5 %), whether bits beyond 16 are used |
| `stability` | For "erratic, and different per channel": idle noise 22 kHz vs 100 kHz per channel (HF instability shows as asymmetric ultrasonic noise), level spread over repeated readings, 20 kHz/0 dBFS THD+N on the wide analyzer, output impedance ×3 (dirty relay contacts show as high or wandering). `--monitor 60` then streams L/R level while you tap relays and flex cables |
| `jtest` | Dunn J-test (fs/4 tone + 1-LSB square at fs/192) at 24 and 16 bit, as ASR/Stereophile show it. The 192-sample waveform is uploaded as an ARB time-table file (`MMEM:DATA`, checked with `MMEM:CHECK?`) |
| `multitone` | 17-tone multisine (the UPL's limit; ASR uses 32), tones on FFT bins; worst product and floor between tones |
| `linearity` | Level error 0 to −130 dBFS, 1 % selective; reports how far down it stays within 0.1 dB |
| `imdlevel` | SMPTE and CCIF IMD vs level, −60 to 0 dBFS |
| `filter` | White noise through the DAC, wideband FFT — the reconstruction filter's shape and image-band leakage |

The test is the same for every DAC. Optionally, `--dut-spec <name>` prints a DUT's published
figures under each result, from `measurements/dut_specs/<name>.json` (format in that folder's
README). One is included: `elektor-dac2000` (Elektor Audio DAC 2000, Elektor Electronics
11/99–1/2000).

**Comparing with Audio Science Review:** the last five tests plus `thdn` (which prints SINAD =
−THD+N at 0 dBFS), `fr` and `fft` cover ASR's standard DAC set. Set the DAC to 2 V unbalanced /
4 V balanced at 0 dBFS first if it has a volume control. Caveat: the UPL's own THD+N floor is
about −103 to −106 dB (loopback), far above ASR's APx555, so SINAD numbers past ~100 dB are the
UPL's limit, not the DAC's. Everything else (response, images, jitter lines, linearity,
crosstalk) stays comparable.

88.2/96 kHz need B29's high rate mode (`CONF:DAI HRM`), which Vol.2 says also degrades the analog
analyzer somewhat, so it's switched on only for those rates and back to `BRM` at the end. Output
goes to `results/dac/<label>_<timestamp>/` (git-ignored): a CSV per test plus
`summary.txt`. **Not yet run against hardware** — every config command is error-checked, and a
list of anything the UPL rejected is printed at the end, so the first live `check` shows what
needs fixing. The refactor was checked offline: `--source upl` sends the same SCPI as the old
`spdif_dac_test.py` plus a few redundant resets, and gives identical CSVs in `--dry-run`.

## Analyzer filter checks (`measurements/filter_test.py`)

Internal loopback only (`INP:TYPE GEN2`), so nothing needs to be patched. Two parts:

- **Bandwidth-limited THD+N**: runs with no filter, then with a 5 kHz user lowpass that is
  defined but not routed, then with 20/10/5/3 kHz lowpasses that *are* routed into a filter slot.
  It shows that a user filter does nothing until it's routed (`SENS:FILT1:UFIL1 ON`).
- **FFT through a filter**: white noise from the generator, 8k FFT, read unfiltered, through
  A‑weighting, and through a 1–5 kHz user bandpass.

```bash
python measurements/filter_test.py --port COM2 -o results/filter_test   # -> _thdn.csv, _fft.csv
```

Sends `*RST` first; leaves filters off and the generator at 0 V. Keep user lowpass cutoffs at or
below 20 kHz on the A22 analyzer: 22 kHz is accepted when defined but rejected when routed, and the
filter then refuses further changes.

## Data-egress tools (getting files off the UPL)

- **`upl_capture.py autoexport` / `nsweep`**: pull trace and X axis straight over the wire to
  CSV. No file is created on the UPL. Best if you just want the measurement.
- **`upl_capture.py getfile`**: pull one file off the UPL's disk (`MMEM:DATA?`), RS‑232 or GPIB.
- **`tools/upl_backup.py`**: bulk backup of files off the UPL's disk, each one checked against the
  MD5 the UPL computes itself and retried on a mismatch. About 10 kB/s over RS‑232 and
  100–150 kB/s over GPIB. Read-only on the instrument, but it sends `INIT:FORC STOP` first,
  which halts the running measurement (`--keep-running` to skip). **Don't interrupt a
  file mid-transfer**: over GPIB that hung the UPL until a power cycle.

  ```bash
  # calibration files: try each name in each directory, keep the first hit
  python tools/upl_backup.py --port COM2 --outdir results/CAL \
      --dirs C:\\UPL\\REF C:\\UPL\\SETUP --names AGEN.CAL ANLR0.CAL LDG.CAL CAL_DIG.SAC

  # the whole disk: `MMEM:CAT?` doesn't work on this firmware, so first make a listing on the UPL
  # (quit to DOS: DIR C:\ /S /A > C:\DIRLIST.TXT), fetch it, then fetch everything it lists
  python tools/upl_backup.py --port COM2 --outdir results/DISK --paths C:\\DIRLIST.TXT
  python tools/upl_backup.py --port GPIB0::20::INSTR --outdir results/DISK \
      --dirlist results/DISK/DIRLIST.TXT --skip-existing
  ```
  Writes `<outdir>/<path on the UPL>` plus `manifest.csv` (bytes, SHA‑256, MD5 check result).
  `--count-only` just totals a listing.

- **`ser_in.py` / `tools/sndfile_batch.py`** use R&S's own route, `SNDFILE.BAS`. **Superseded by
  `upl_backup.py`**; kept for reference. `ser_in.py` reimplements R&S's `SER_IN.EXE` (16‑bit DOS,
  won't run on 64‑bit Windows) and receives one file. `sndfile_batch.py` handles the PC side of a
  multi-file SNDFILE pull, while the operator runs the macro on the front panel for each file.
  Every SNDFILE run takes COM2 away from remote control until you reselect it on the OPTIONS panel.
  Serial mode verified; GPIB mode (`--port GPIB0::20::INSTR --data-port COM2`) didn't work when
  tried by hand.

## Firmware archive extraction (`tools/lzh_extract.py`)

The firmware disks and several app notes ship as `.LZH` (LHA) archives. `LHA.EXE` is 16‑bit DOS,
so this is a pure-Python `-lh5-` decoder:

```bash
python tools/lzh_extract.py DISK2/USER.LZH                          # list members
python tools/lzh_extract.py DISK2/USER.LZH SNDFILE.BAS > SNDFILE.BAS
```

Output is raw bytes. The `.BAS` files are tokenized R&S BASIC; string literals are readable,
the rest isn't. (Windows' own `C:\Windows\System32\tar.exe` also reads `.LZH`. This script is
for when that isn't available or you want a single member on stdout.)

## Folder layout

| Folder | Contents |
|---|---|
| top level | core control libraries (`upl_capture.py`, `dcx2496.py`, `nad_m51.py`, `ser_in.py`), `dcx_sweep.py`, `upl_selftest.py`, `audio_tests.py` |
| `measurements/` | characterization scripts: each drives the UPL (and usually a DUT) through one test and writes CSV/JSON |
| `tools/` | utilities: disk/file backup, SNDFILE batch transfer, LZH extraction, test-signal generator |
| `testsignals/` | generated test WAVs, **git-ignored** — rebuild with `tools/testsignals.py` |
| `results/` | measurement output and instrument backups, **git-ignored** (it holds the serial number, option key and calibration) |

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
