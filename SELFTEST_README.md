# UPL Self-Test — Standalone Guide

`upl_selftest.py` is a remote replica of Rohde & Schwarz's own factory self-test
(`SELFTEST_Program.TXT`, which runs natively on the UPL's own BASIC interpreter and only shows
a PASS/FAIL indicator per line on the front panel). This script runs the identical command
sequence from a PC over the remote-control link and prints **every underlying measured value**,
plus writes a full text report you can keep and diff against future runs.

This guide is self-contained — you shouldn't need anything else from this repo except the two
files named below. Reference run: 2026-09-22, serial 100330/6, firmware 3.06 — **121/121
readings passed**. (`CLAUDE.md`, if you have it, has the full result table to compare a new run
against, but it isn't required to use this script.)

## 1. Install the dependencies

You need **Python 3.8 or later**. Check what you have:

```bash
python --version
```

If that fails or shows Python 2, try `python3 --version` instead, and use `python3` in place of
`python` in every command below. If you don't have Python at all, install it from
[python.org](https://www.python.org/downloads/) (on Windows, tick "Add python.exe to PATH"
during install) or via your OS's package manager on Linux/macOS.

Then install the one required package, **pyserial** (note: not the similarly-named `serial`
package — that's a different, unrelated library):

```bash
python -m pip install pyserial
```

Nothing else is required — no numpy, no other dependencies for this particular script. **Only if
you'll connect over GPIB** instead of serial (see step 3), also install `pyvisa` plus your GPIB
adapter's VISA library (for the Agilent/Keysight 82357B: the Keysight IO Libraries Suite, then
reboot):

```bash
python -m pip install pyvisa
```

## 2. Get the files

You need exactly two files, in the **same folder**:

- `upl_selftest.py` — the script itself
- `upl_capture.py` — supplies the serial and GPIB communication classes `upl_selftest.py` is built on

Both are in this repository. If you only have `upl_selftest.py`, go back and grab
`upl_capture.py` too — the script will fail to start without it (`ImportError`).

## 3. Hardware setup

Connect **either** way; the script takes both.

- **Serial (the usual way):** a USB-to-serial adapter connecting this PC to the UPL's rear
  **COM2** port. An FTDI-chipset adapter is recommended — some Prolific-chipset adapters have
  shown intermittent driver issues in testing (see the Gotchas section below if a port that worked
  before suddenly won't open). On the UPL's OPTIONS panel, set remote control destination to
  **COM2** (not IEC-bus), and note the baud rate shown there — you'll pass the same number to
  `--baud` below. (115200 is a good default if you're free to choose; see the baud note further
  down.)
- **GPIB:** a GPIB adapter (tested with an Agilent/Keysight 82357B) to the UPL's IEC-bus
  connector. On the OPTIONS panel set remote control destination to **IEC**, address **20**.
  Baud doesn't apply.
- **Remove any cables from the UPL's generator and analyzer front-panel connectors** before
  running. This test is entirely internal loopback — the UPL measures its own generator — and
  the original front-panel self-test carries the same warning.

## 4. Find your COM port

The adapter will show up as a numbered COM port on Windows. Check Device Manager → Ports (COM &
LPT), or run this from a terminal:

```bash
python -c "import serial.tools.list_ports as lp; print([(p.device, p.description) for p in lp.comports()])"
```

Look for your adapter's description in the list (e.g. "USB Serial Port (COM7)") and use that
`COMx` value as `--port` below.

**Over GPIB** the port is a VISA resource name instead, normally `GPIB0::20::INSTR` (board 0,
address 20). To list what VISA sees:

```bash
python -c "import pyvisa; print(pyvisa.ResourceManager().list_resources())"
```

## 5. How to run it

```bash
python upl_selftest.py --port COM7
```

That's the whole thing for a default run. Useful variations:

```bash
# different port or baud
python upl_selftest.py --port COM7 --baud 115200

# over GPIB instead of serial (--baud is ignored)
python upl_selftest.py --port GPIB0::20::INSTR

# name the run (the results folder becomes results/selftest/after_recal_<timestamp>/)
python upl_selftest.py --port COM7 --label after_recal

# also copy the text report to a file of your choosing
python upl_selftest.py --port COM7 -o selftest_2026-09-23.txt

# if a run shows a spurious "N/A" reading right after a frequency change,
# give the generator more time to settle before the first measurement
python upl_selftest.py --port COM7 --settle 0.8
```

Default baud is **115200** (confirmed working directly against real UPL hardware, even though
the printed manual's own SCPI baud table only listed up to 56000). Set the UPL's OPTIONS panel
COM2 baud to match, or override with `--baud` if you're running it at something else.

## What happens when you run it

1. Sends `*RST` — **this clears whatever setup is currently on the UPL's screen**, exactly like
   the front-panel self-test does. Reload your own working setup afterward if you had one loaded.
2. Reads `*OPT?` and the unit's serial number, and works out which sections apply based on which
   options are fitted (e.g. the low-distortion-generator section is skipped if B1 isn't installed,
   the digital-audio section is skipped if no digital option is present).
3. Runs through 10 sections at full resolution, matching the original program point-for-point:

   | # | Section | Points | Spec |
   |---|---|---|---|
   | 1 | Generator range control | 6 (30mV–20V) | ±1.6–2% |
   | 2 | Low-distortion generator (B1) | 4 (150Hz–25kHz) | ±1.6–2.7% / 0.8% |
   | 3 | Analyzer ranges | 48 (16 levels × {1kHz, 40Hz, 15kHz}) | ±1.5–3.0% |
   | 4 | Inherent THD+N @1kHz/2V, A22 | 1 | ≤ −93dB |
   | 5 | THD+N −60dB linearity (2-tone) | 1 | ±0.5dB |
   | 6 | Inherent THD+N @1kHz/2V, A100 | 1 | ≤ −84dB |
   | 7 | Inherent D2 (DFD) @10kHz/200Hz | 1 | ≤ −110dB |
   | 8 | Inherent noise, A22 | 1 | ≤ 2µV |
   | 9 | Inherent noise, A100 | 1 | ≤ 8µV |
   | 10 | Digital audio level/freq (B29) | 3 | 0.1% / 0.01% |

4. Prints every reading live as it goes (set value, measured value, deviation, tolerance, and a
   `<-- OUT OF TOL` flag on anything that fails), then a summary listing every out-of-tolerance
   reading, then `OVERALL: PASS` or `OVERALL: FAIL`.
5. Saves everything to a results folder, `results/selftest/<label>_<YYYYMMDD-HHMMSS>/`
   (label `selftest` unless you give `--label`; `--outdir DIR` to put it elsewhere):
   - `report.html`: open it in a browser. The headline ("PASS: 121/121 readings within
     tolerance"), any out-of-tolerance readings first, then one table per section with set,
     measured, deviation, tolerance and a pass/FAIL mark on every reading.
   - `report.txt`: the same text the console showed, as the selftest has always written it.
   - `readings.csv`: every reading, one row each, for a spreadsheet or comparing with an
     earlier run.
   - `summary.txt`: the full console output.

   `results/index.html` lists every run, so successive selftests line up by date. `-o FILE` also
   copies the text report to `FILE`.

Takes a few minutes end-to-end (121 readings; section 3 alone is 48 of them).

## Reading the output

Each line looks like:

```
  set   0.030 V -> CH1 0.02992 V (-0.24%)  CH2 0.02992 V (-0.26%)  tol 2%
```

`set` is the commanded value, the two channel readings are what the UPL actually measured, the
percentages are the deviation, and `tol` is the R&S factory tolerance for that point. Anything
exceeding tolerance gets an inline `<-- OUT OF TOL` marker and shows up again in the final
summary with its full detail (section, channel, set value, measured value, deviation, tolerance).

The exit code is `0` for a full pass and `1` if anything failed — useful if you ever want to
script "run self-test, alert me only if something's wrong."

## Gotchas

- **Port opens sometimes, fails other times with a "file not found"-style error.** This is a
  known intermittent USB-serial driver quirk seen on both Prolific and FTDI adapters, not a
  wiring problem. Fix, in order of what to try: (1) unplug and replug the adapter, (2) plug it
  into a different USB port directly on the PC rather than a hub, (3) reboot the PC, (4) in
  Device Manager, open the adapter's Properties → Power Management and untick "Allow the
  computer to turn off this device to save power" (do the same for each USB Root Hub too).
- **`*RST` wipes your setup.** If you have a working setup loaded, save it or note it down before
  running this, and reload it afterward.
- **A "reading" of `9.93e37` (or similar absurdly large values) is the UPL's own "not available"
  sentinel**, not a real measurement — this script already filters/flags these, but if you're
  reading a report by hand, don't mistake one for an actual out-of-range value.
- **The one false-failure this script is specifically guarding against**: switching frequency
  bands too fast, right before the very first reading at the new frequency, can catch the UPL
  mid-settle and return the "N/A" sentinel — logged as an out-of-tolerance point even though the
  instrument is fine. The default `--settle 0.4` was chosen after hitting exactly this on the
  first full run (at 15kHz/18mV); raise it if you see an isolated, otherwise-inexplicable failure
  right after a `--- @ ... ---` section header in the console output.
- This is a **condensed-but-full-resolution** replica, not a byte-for-byte port of the BASIC
  source — a couple of front-panel-only conveniences (live pass/fail markers drawn as boxes on
  screen) aren't reproduced, since the whole point here is the numeric values instead.
