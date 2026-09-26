# R&S UPL Audio Analyzer — Remote Control & Test Suite

Tools for driving a Rohde & Schwarz UPL audio analyzer from a modern PC over its RS‑232 **or GPIB
(IEC‑bus)** remote port, pulling data off it, and using it to automatically characterize other
gear: any DAC, player or audio device, through test suites that treat the device as a black box.
Background, firmware analysis, and the full narrative of how everything here was
discovered/verified is in `CLAUDE.md` — this file is the "how do I actually run things" reference.

Separate guides:
- **[SELFTEST_README.md](SELFTEST_README.md)**: the UPL's own self-test.
- **Equipment-specific control** (tests that also drive a particular unit over its own serial
  port): **[DCX2496_README.md](DCX2496_README.md)** (Behringer DCX2496 crossover),
  **[M51_README.md](M51_README.md)** (NAD M51 DAC).

**Contents**

- [Setup](#setup): install, what's required vs optional, and connecting to the UPL over
  **serial or GPIB**
- [Where results go](#where-results-go): one folder per run, with a readable `report.html`
- [Core control libraries](#core-control-libraries): `upl_capture.py` and the UPL basics
  (dry run, native sweep, FFT paging, `--preserve`, backups)
- [Data-egress tools](#data-egress-tools-getting-files-off-the-upl): getting files off the UPL
- [UPL self-test](#upl-self-test)
- **[Tests for any device](#tests-for-any-device)**: the DAC suite, the analog (preamp) suite,
  test-signal files, file and test-disc playback, analyzer filter checks, the soundcard suite
  - **DAC quick start: [I just want measurements](#i-just-want-measurements-tldr)**
  - **Preamp/analog quick start: [Analog quick start](#analog-quick-start)**
- [Equipment-specific control](#equipment-specific-control): pointers to the per-device guides
- Reference: [firmware archive extraction](#firmware-archive-extraction-toolslzh_extractpy),
  [folder layout](#folder-layout), [where things are documented](#where-things-are-documented)

## Setup

```bash
python -m pip install pyserial numpy scipy sounddevice soundfile matplotlib
python -m pip install pyvisa          # only if you'll use GPIB (see below)
```

### What you need

**Required:**
- a UPL with option **UPL‑B4** (remote control), connected over RS‑232 or GPIB (below)
- Python 3 and the packages above
- for GPIB only: the Keysight IO Libraries Suite and `pyvisa`
- for testing a DAC without a digital audio option (UPL‑B2/B29): a Windows PC, which then plays
  the test signal

**UPL options:** nothing beyond B4 is needed to test a DAC. Without a digital audio option the
PC plays the test signal (see [Choosing the signal source](#choosing-the-signal-source)).
A digital audio option (UPL‑B2 or B29) lets the UPL feed the DAC's S/PDIF or AES input
itself and adds the interface tests; UPL‑B22 adds the jitter test; UPL‑B1 is used by the
selftest's low-distortion sections, and by `analog_test.py` when fitted (without it, the standard
generator; only `fr --wide` above 21.75 kHz needs B1). `upl_selftest.py` skips the sections for options it doesn't
find in `*OPT?`, and `dac_test.py --source upl` checks `*OPT?` before it starts.

**Files not in git.** R&S firmware, manuals, application notes, the UPA‑CD test disc and other
third-party material aren't ours to redistribute. [`external/`](external/README.md) has a folder
for each, with a README saying what goes there and where to find it. **None of them is needed to
run the tools, with one exception:**

| File | Status | Without it |
|---|---|---|
| UPA‑CD zip, in `external/upa-cd/` | **required** for `upacd_test.py` playing disc tracks | disc-track tests don't run; `upacd_test.py --wav` with `tools/testsignals.py` files still works |
| Operating manuals, in `external/manuals/` | optional, strongly recommended | everything runs; Vol.2 is the SCPI reference if you change or extend a script |
| Application notes, factory selftest program, service manuals | optional | everything runs; they're the sources behind the SCPI and hardware notes in `CLAUDE.md` |
| Firmware disks, in `DISK1/`, `DISK2/` | optional | everything runs; only needed to look inside the firmware or reinstall it on a UPL |
| B23 coded-audio library, DUT docs | optional | everything runs |

### Connecting to the UPL: serial or GPIB

Every script's UPL port option (`--port`, or `--upl-port` where a DUT port is also involved) takes
either kind of connection, chosen by the name you give it:

| Connection | Port value | Needs | On the UPL (OPTIONS panel) |
|---|---|---|---|
| **RS‑232** (default) | `COM7` etc. | a USB‑serial adapter with real RTS/CTS on the UPL's rear COM2; `pyserial` | Remote via → **COM2**, 115200 baud |
| **GPIB** | `GPIB0::20::INSTR` | a GPIB adapter (tested: Agilent/Keysight **82357B**) + Keysight IO Libraries Suite + `pyvisa` | Remote via → **IEC**, address **20** |

```bash
python upl_capture.py --port COM7 probe                # serial
python upl_capture.py --port GPIB0::20::INSTR probe    # GPIB
```

Serial needs no GPIB software: `pyvisa` is only imported when a `GPIB…` name is given. GPIB is
~10× faster than RS‑232: much quicker file transfers, and more readings per step in
`upacd_test.py`'s continuous polling. `--baud` is ignored over GPIB. The Keysight suite needed a
PC reboot before VISA would load. See `CLAUDE.md`, "GPIB (Agilent/Keysight 82357B)", for the
gotchas, such as never interrupting a GPIB file transfer. Two things are always serial: links to
a controlled **DUT** (`--dut-port`, `--dcx-port`; see the equipment guides) and
`tools/sndfile_batch.py` (SNDFILE sends over COM2 by design).

To find the ports: a GPIB resource name comes from
`python -c "import pyvisa; print(pyvisa.ResourceManager().list_resources())"`.
**COM port assignment is whatever your USB-serial adapters currently enumerate as** — it's not
fixed; check with:

```bash
python -c "import serial.tools.list_ports as lp; print([(p.device, p.description) for p in lp.comports()])"
```

If a port that worked before now fails to open with a `FileNotFoundError`/"file not found" from
pyserial, that's a known intermittent USB-serial driver quirk (seen on both a Prolific and an
FTDI adapter in testing) — reboot the PC, plug the adapter into a direct USB port (not a hub),
and disable "allow the computer to turn off this device" under that device's and each USB Root
Hub's Power Management in Device Manager. See `CLAUDE.md`'s "Current live wiring" section for the
full troubleshooting history.

### Serial cable: use a null modem with all the handshake lines

The UPL's COM2 uses **RTS/CTS hardware handshake** by default, and it only sends a reply while
its CTS input is TRUE. So the cable needs the handshake lines, not just TX/RX/ground. The right
cable is a full **null modem** (R&S order no. 1050.0346, 2 × DB9 female; Vol.2 §3.17.1, Fig. 3‑18):

| UPL COM2 pin | | PC pin (DB9) |
|---|---|---|
| 2 RxD | ↔ | 3 TxD |
| 3 TxD | ↔ | 2 RxD |
| 5 GND | ↔ | 5 GND |
| 7 RTS | ↔ | 8 CTS |
| 8 CTS | ↔ | 7 RTS |
| 4 DTR | ↔ | 6 DSR (+ 1 DCD) |
| 6 DSR | ↔ | 4 DTR (+ 1 DCD) |

A shop "null modem cable" is usually wired like this. A **null modem adapter** or a cheap
3-wire cable often isn't. Check with a meter: **7↔8 crossed** is the pair that matters. The
USB-serial adapter must bring out real RTS/CTS too (most do; FTDI is the more reliable chipset,
see below).

**Symptoms of a cable without handshake lines:** the UPL goes into REMOTE (it *receives*) but
never answers, not even `*IDN?`, and the tools time out. On the PC, CTS, DSR and CD all read
False:

```bash
python -c "import serial; s=serial.Serial('COM2'); print('CTS',s.cts,'DSR',s.dsr,'CD',s.cd)"
```

With a full null modem and the UPL on, at least CTS and DSR read True. All False with a good
cable means a connector isn't seated: screw both ends in.

**Workaround if only a 3-wire cable is available:** set the UPL's OPTIONS → COM2 → Handshake
to **XON/XOFF** and add `,xon` to the port: `--port COM2,xon`. Text SCPI then works in every tool.
Binary file pulls (`getfile`, `tools/upl_backup.py`) are refused, because XON/XOFF corrupts
binary data (Vol.2 §3.17.6). Set the handshake back to RTS/CTS when the proper cable goes back in.

## Where results go

Every measurement script writes **one folder per run**, never into the folder you ran it from:

```
results/<test>/<label>_<YYYYMMDD-HHMMSS>/
    report.html      open in any browser: run details, tables, graphs (one self-contained file)
    summary.txt      everything the script printed
    *.csv, *.json    the raw data, unrounded -- for Excel, scripts, comparing runs
    plots/*.png      each graph on its own, for pasting elsewhere
    run.json         what ran, when, with which command line
```

**`results/index.html`** lists every run, newest first, with its headline result (e.g. "PASS:
137/137", "Worst THD+N −78.4 dB at 6016 Hz") and a link to its report. It is rebuilt after each run;
`python report.py` rebuilds it by hand.

Two options, the same on every script:

| Option | Does |
|---|---|
| `--label NAME` | names the run folder: the DUT, the cable, the setting (`--label mydac_usb_96k`). Each script has a sensible default (`dac`, `selftest`...). |
| `--outdir DIR` | puts this run exactly in `DIR` instead |

`-o FILE`, where a script has it, now means "just the CSV, to this file, no results folder"
(`-o -` prints it), for piping or a one-off. A run that fails part-way still writes its folder
and report, marked as partial, with everything measured up to that point. `--dry-run` runs are
labelled `dryrun_…` so they can't be mistaken for measurements. Graphs need `matplotlib`; without
it you get everything except the graphs, and the report says so.

`results/` is git-ignored: it holds the serial number, option key and calibration. The instrument
backups (`results/CAL/`, `results/DISK/`, `results/REF/`) are separate folders you name
yourself with `tools/upl_backup.py --outdir`.

The code is `report.py` (`Run`, used as `with Run("mytest", label=...) as rep:` plus
`rep.csv / rep.table / rep.plot`); the start of that file explains how to add it to a new script.

## Core control libraries

These provide the `import`-able classes the test scripts build on. Each is also a standalone CLI.
(Drivers for particular DUTs, `dcx2496.py` and `nad_m51.py`, are covered in their own guides.)

| File | What it talks to | Protocol |
|---|---|---|
| `upl_capture.py` | R&S UPL, RS‑232 or GPIB remote | SCPI. RS‑232: LF-terminated, 115200 8N1 RTS/CTS; GPIB: VISA, address 20 |
| `ser_in.py` | receives a file the UPL pushes via its `SNDFILE.BAS` macro (superseded by `getfile` / `tools/upl_backup.py`) | raw bytes, 115200, idle-timeout framing |

Quick examples:

```bash
# UPL: confirm remote control is live, read a value, pull a sweep to CSV
python upl_capture.py --port COM7 probe
python upl_capture.py --port COM7 raw "SYST:ERR?"
python upl_capture.py --port COM7 autoexport              # -> results/autoexport/trace_<time>/
python upl_capture.py --port GPIB0::20::INSTR probe      # the same, over GPIB

# UPL: run the instrument's OWN sweep engine
python upl_capture.py --port COM7 --label loopback nsweep --start 20 --stop 20000 --points 40

# UPL: have the instrument save its current trace to its own disk, then pull that file
python upl_capture.py --port COM7 storetrace "C:\UPL\FR.EXP"
python upl_capture.py --port COM7 getfile "C:\UPL\FR.EXP" -o FR.EXP

# UPL: full FFT spectrum, paging past the 1024-line limit
python upl_capture.py --port COM7 fft --size 8192
```

`upl_capture.py --help` lists every subcommand.

### Working offline (`--dry-run`)

Every `upl_capture.py` subcommand takes `--dry-run`, which skips the instrument connection entirely, prints
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
stepping `SOUR:FREQ` from the host in a loop. Far fewer round trips —
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
python upl_capture.py --port COM7 fft --size 8192
python upl_capture.py --port COM7 --label zoom10k fft --zoom 8 --center 10000
python upl_capture.py --port COM7 fft --size 8192 -o -      # just the CSV, on screen
```

This is what an earlier "FFT zoom quirk" turned out to be — zoom was never broken, the readout
was returning the wrong eighth of it. `CLAUDE.md`'s "FFT zoom quirk RESOLVED" section
has the full arithmetic. Note that over the bus you set the zoom **factor**, never the SPAN
(`CALC:TRAN:FREQ:SPAN?` is query-only).

### Not clobbering the instrument's setup (`--preserve`)

`nsweep` and `fft` start with `*RST`, which throws away whatever you had configured on the front
panel. `--preserve` brackets the whole measurement with a snapshot/restore instead — the idiom R&S
uses in its own shipped `FLAT_GEN.BAS` macro:

```bash
python upl_capture.py --port COM7 --preserve nsweep --points 40
```

That sends `MMEM:STOR:STAT 2,'C:\UPL\USER\UPLTMP.SCO'` first (mode 2 = the *complete* setup), does
its thing, then `MMEM:LOAD:STAT 2` + `MMEM:DEL`. Override the scratch path with `--state-file`.
It's opt-in because it writes a file to the instrument's disk.

`nsweep --setup C:\UPL\MYSETUP.SAC` loads a stored setup first (`MMEM:LOAD:STAT 0`) — again how
R&S's own programs configure a measurement, rather than sending every panel setting.

### Backing up per-unit state (`diagdump`)

```bash
python upl_capture.py --dry-run diagdump                          # offline, see what it would do
python upl_capture.py --port COM7 --label sern diagdump --devices SERN   # first live run
python upl_capture.py --port COM7 --label full diagdump                   # then the full set
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

## UPL self-test

See **[SELFTEST_README.md](SELFTEST_README.md)** — `upl_selftest.py`, fully documented there.

## Tests for any device

These work on any DUT: the device is whatever sits between the signal source and the UPL's
analyzer input, and nothing here assumes a particular make. Start with these; the
[equipment-specific guides](#equipment-specific-control) only add control of a particular unit.

### DAC characterization (`measurements/dac_test.py`)

One test suite for any DAC, whatever its digital input: something plays a bit-exact test signal
into the DAC, and the UPL's analog analyzer measures what comes out. Every measurement and
diagnosis is the same whichever source plays the signal, so results are comparable across DACs.

#### I just want measurements (TL;DR)

A Windows PC with the DAC on USB (or a USB→S/PDIF interface in front of it), the DAC's L/R
outputs into the UPL's analyzer inputs 1 and 2, **nothing else connected to the DAC's outputs**,
and the UPL on remote (`probe` answers, see [Setup](#setup)):

```bash
python measurements/upacd_test.py devices
```
Note the number of the DAC's **Windows WASAPI** entry, and use it as `N` below:
```bash
python measurements/dac_test.py --port COM7 --source pc --device N --settle 0.6 check
python measurements/dac_test.py --port COM7 --source pc --device N --settle 0.6 --set-level --target 2 --label mydac all
```
- `check` must say `lock: YES`. If it doesn't, fix that first (cable, input, sample rate).
- `--set-level --target 2` walks you through setting the DAC's volume for 2 V at full scale, then
  runs every test. A DAC without a volume control: leave out `--set-level --target 2`.
- It takes a while. The results are in `results/dac/mydac_<timestamp>/report.html`.

With a digital audio option (UPL‑B2/B29) feeding the DAC's S/PDIF/AES input instead, leave out
`--source pc --device N --settle 0.6`. The rest of this section explains each step and option.

#### Choosing the signal source

| You have | Source | Reaches the DAC's… | Sample rates |
|---|---|---|---|
| **a UPL without a digital audio option** (most units), and a Windows PC | **`--source pc --device N`**: this PC plays each tone | **USB** input directly; **coax/optical** input through a USB→S/PDIF interface | whatever the PC output and the DAC both take, e.g. up to 192 kHz |
| a UPL with a **digital audio option** (UPL‑B2 or B29) | `--source upl` (the default): the UPL's own digital generator | coax, optical, AES3 | 44.1, 48, 88.2, 96 kHz (B2: 44.1/48 only) |

To see which options your UPL has: `python upl_capture.py --port COM7 raw "*OPT?"` and look for
`B2` or `B29` (and `B22`, for the jitter test). You don't have to check first: with `--source upl`
the script reads `*OPT?` itself and stops with a pointer here if neither is fitted, or if a B2 is
asked for 88.2/96 kHz.

**The PC source (`--source pc`)** synthesizes each tone on this PC and plays it as exact integer
samples with dither off, so it reaches the DAC bit-exact. For that to hold:
- **Windows only**: it uses WASAPI exclusive mode, so Windows neither resamples nor mixes. Find
  N with `python measurements/upacd_test.py devices` and pick an entry marked
  **Windows WASAPI**; other kinds are refused (unless `--shared`, which resamples: results suspect).
- nothing between the PC and the DAC may change the samples: no volume, EQ or "enhancement" in the
  driver or control panel, and, for a USB→S/PDIF interface, an output rate that follows the
  stream (check what the DAC says it's locked to);
- give it `--settle 0.5`–`0.6`: a new tone only arrives after the audio buffer and the DAC's own
  latency.
- some drivers refuse exclusive mode at some rates unless the buffer size suits them, and
  PortAudio reports that as a misleading **`Invalid device [PaErrorCode -9996]`** even though the
  device number is right. The script retries at 50 ms latency, which fixed the laptop's Realtek
  output at 44.1/88.2 kHz. If a device still fails that way, check the rate with
  `python -c "import sounddevice as sd; sd.check_output_settings(device=N, samplerate=44100, extra_settings=sd.WasapiSettings(exclusive=True))"`.
- the level at 0 dBFS depends on the device's own volume: exclusive mode skips the Windows mixer, but
  the codec's volume control can still act. Set it to 100 % before measuring. (The laptop's headphone
  output gave only ~85 mV at 0 dBFS with its volume turned down, and 1.54 V at 100 %.)

What it can't do: the UPL's analyzer can't track a PC's generator, so selective measurements use a
bandpass the script moves to each tone (same results, set differently). `jitter`, `interface` and
`polarity` need the UPL's digital generator and are skipped. With a USB→S/PDIF interface, the
interface's own clock jitter is part of every result, and nothing here can separate it from the
DAC's. **`--source pc` has been run live through a full `all`**, on the laptop's own headphone
output (2026‑09‑25, `results/dac/rog14_*`). Things that run showed about the PC source:
- `thdn` can't reset the analyzer's THD+N floor (the reset sweep needs the UPL's generator) and
  says so once. It matters only for a DUT cleaner than about −100 dB THD+N.
- A22 won't centre the selective bandpass at 20 kHz; the script backs it off 1 % at a time and
  says where it ended up (a 1/3-octave band still passes the tone).
- `images` on A100 shows no hum figures (37.5 Hz bins can't separate 50 from 60 Hz; use `fft`).
  A fixed spur that happens to sit on k·fs ± f is still listed as an image: check it at other rates.

**The UPL source (`--source upl`, needs B2 or B29)** is bit-exact too, and the UPL sets the sample
rate. It can also degrade the interface on purpose: jitter (with UPL‑B22), a 100 m cable
simulator, low signal voltage, off-nominal sample rates, 16/20/24-bit words. Run live on three
DACs with a B29; B2's 48 kHz limit comes from the manuals, not tried yet.

| Test | PC source | UPL source (B2/B29) |
|---|---|---|
| `setlevel`, `check`, `fr`, `thdn`, `fft`, `imd`, `xtalk`, `zout`, `stability`, `jtest`, `multitone`, `linearity`, `imdlevel`, `filter` | yes, any rate the PC output and the DAC both take | yes |
| `fft --images`, `fr --wide` above 20 kHz | yes | yes, to 43 kHz (B2: to 21.6 kHz, as it stops at 48 kHz) |
| `jitter` | **no** (can't inject jitter) | with UPL‑B22 |
| `interface` (input level, lock range, word length) | **no** | yes |
| `polarity` | **no** (use `testsignals` file 18, half-waves, and a scope) | yes |
| `jtest` as a jitter test | includes the PC/interface's jitter | clean UPL clock |

A player that can only play files itself (a DAP's own playback) can't be driven this way;
use `tools/testsignals.py` + `upacd_test.py --external` for that.

Most DACs need no control: set them up by hand and the suite treats them as a black box. For a
DAC with a remote-control driver, **`--dut NAME --dut-port COMn`** logs its source and volume in
the report, sets `--volume` for the run and restores it, and enables **`volsweep`** (THD+N/THD/
level vs the DUT's volume). Supported so far: `m51` ([M51_README.md](M51_README.md)). Adding
another DUT means one small class in `dac_test.py`'s `DUTS`.

#### Step by step

The commands are for the PC source. **With a digital audio option (UPL‑B2/B29), leave out
`--source pc --device N --settle 0.6`.** Replace `N` with the device number (see above) and
`COM7` with the UPL's port.

1. **Choose the source** ([above](#choosing-the-signal-source)) and **connect it**
   ([Connecting the DAC](#connecting-the-dac)): the source into the DAC, and the DAC's L/R
   outputs into the UPL's analyzer inputs 1 and 2. **Nothing else on the DAC's outputs**: several
   tests play full-scale tones.
2. **Set the DAC up by hand:** the right input, any filter or mode settings you want tested,
   EQ/DSP/"enhancers" off, and fixed-output mode if it has one.
3. **Optional, offline:** `python measurements/dac_test.py --dry-run all` runs everything
   against a stub and prints the SCPI, without touching the instrument or playing anything.
4. **Check lock and level:**
   ```bash
   python measurements/dac_test.py --port COM7 --source pc --device N --settle 0.6 check
   ```
   Every rate should say `lock: YES`. If not: the cable, the DAC's input selection, or a rate
   the DAC doesn't support (drop it from `--fs`).
5. **Set the volume**, if the DAC has one ([Setting the volume](#setting-the-volume)):
   ```bash
   python measurements/dac_test.py --port COM7 --source pc --device N --settle 0.6 --target 2 setlevel
   ```
   Leave out `--target 2` to find the loudest clean setting instead. Then leave the volume alone
   for the rest of the tests. Skip this step for a fixed-output DAC.
6. **Run the tests**, all of them or the ones you want ([Running the tests](#running-the-tests)):
   ```bash
   python measurements/dac_test.py --port COM7 --source pc --device N --settle 0.6 --label mydac all
   ```
   Pick the sample rates with `--fs`. Steps 5 and 6 can be one command:
   `--set-level --target 2 all`.
7. **Read the results:** `results/dac/mydac_<timestamp>/report.html`. `results/index.html`
   lists every run.

#### Connecting the DAC

**From the PC** (`--source pc`): a USB DAC plugs straight into the PC. For a DAC with only coax or
optical inputs, put a USB→S/PDIF interface (a USB audio device with a coax or optical output)
between the PC and the DAC, and pick the interface as the device.

**From the UPL** (`--source upl`): UPL digital out → DAC input. For a coax (S/PDIF) input use the
UPL's **UNBAL BNC output directly**: it is already a transformer-coupled 75 Ω source (Service
Manual Vol.2 p.247: CLC430 driver → 1:1 transformer T2 → 150‖150 Ω = 75 Ω → BNC; Vol.1 p.2.74:
level set as Vpp into 75 Ω, 0–2.125 V), so no 110→75 Ω transformer is needed; BNC→RCA adapter +
75 Ω coax. Use BAL XLR (110 Ω) for AES3 inputs, TOSLINK for optical.

**Either way**, DAC L/R analog out → UPL analyzer inputs 1/2. RCA outputs go into the XLR inputs
via adapters; the script uses `INP:LOW FLOat` (grounding the input's low side added measurable
noise with single-ended sources, see `CLAUDE.md` "Balanced vs single-ended comparison"),
`--ground` to change it.

#### Setting the volume

Most results depend on where the DUT's volume is set, so set it deliberately and record it. What
to aim for:

- **A DAC with a fixed-output or bypass mode:** use it. That's the DAC without its volume
  control, and the setting to compare.
- **A DAC whose volume can reach unity** (0 dB, max): usually set it there. A digital volume
  control costs a dB of dynamic range for every dB it attenuates (the M51 showed exactly this).
  **But check that 0 dBFS doesn't clip** at that setting; if it does, back off until it's clean
  (the M51 needed −1 dB).
- **To compare with Audio Science Review:** set it so 0 dBFS gives **2 V** unbalanced (RCA) or
  **4 V** balanced (XLR), if the volume allows.
- **A headphone amp or player whose volume is just step numbers** (0–120, 1–60…): the numbers
  mean nothing in dB, so pick by output. Either the **loudest clean setting** (the highest step
  where a 0 dBFS tone doesn't clip) or a **fixed output** you use for every device you compare.
  Note the step number. Turn off EQ, DSP, "enhancers" and volume limiters first.

`setlevel` guides you through it. It plays 997 Hz at 0 dBFS and shows both channels' output and
THD about once a second while you turn the knob:

```bash
python measurements/dac_test.py --port COM7 --target 2 setlevel             # aim for 2 V
python measurements/dac_test.py --port COM7 setlevel                        # loudest clean setting
python measurements/dac_test.py --port COM7 --set-level --target 2 all      # set it, then test
```

With `--target` each line says `turn UP` / `turn DOWN` / `OK` (within 0.1 dB, on the average of
L and R). Without it, a line is flagged `CLIPPING?` once THD is 10 dB worse than the best seen so
far: turn up until that appears, then back down until it's gone. Press Enter when done; it then
asks what the device's volume reads and puts that in the report. It measures THD, not THD+N, on
purpose: THD+N of a clipping 0 dBFS tone latches the UPL's THD+N floor about 6 dB high.

**The tone is a full-scale 0 dBFS sine**, played until you press Enter (or `--max-time`): only the
UPL may be connected to the outputs. No headphones, no amplifier.

#### Running the tests

```bash
python measurements/dac_test.py --dry-run all                  # offline: runs everything
python measurements/dac_test.py --port COM7 check              # lock, 0 dBFS level, balance, DC
python measurements/dac_test.py --port COM7 fr                 # frequency response, diagnosed
python measurements/dac_test.py --port COM7 --fs 44100 fft --images
python measurements/dac_test.py --port COM7 --label mydac all  # the lot: ~26 min at 4 rates on GPIB

# USB DAC: the PC is the source (find N with `python measurements/upacd_test.py devices`)
python measurements/dac_test.py --port COM7 --source pc --device N --fs 44100,96000,192000 \
    --settle 0.6 --label mydac_usb all
```

| Test | What it answers |
|---|---|
| `setlevel` | Guided volume setting for a DUT with a manual knob (see [Setting the volume](#setting-the-volume)). Not part of `all`; `--set-level` runs it before any test |
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
| `volsweep` | THD+N, THD and level vs the DUT's own volume setting. Needs `--dut`; not part of `all` |
| `impulse` | Impulse and step response: a one-sample impulse every 10 ms (UPL: an ARB time-table file; PC: a looped buffer), captured with the UPL's WAVEFORM function on the 100 kHz analyzer and averaged over `--avg 8` captures. Classifies the filter (linear phase / minimum phase / no ringing) and reports ringing frequency and duration, polarity, step overshoot and rise time, and magnitude/phase response by FFT (100 Hz resolution). L and R are captured one after the other, so no L/R timing and no absolute latency. If it never triggers, the UPL keeps waiting: press STOP on the panel; `--slope fall` for an inverting DAC. In `all` only with `--with-impulse` (see below). **Slow:** it pulls ~1.1 MB of ASCII waveform per rate at the default `--avg 8`, so about 1 min per rate over GPIB and about 2 min per rate over RS‑232 at 115 200 (all four rates: ~4½ / ~9–10 min). Lower `--avg` or fewer `--fs` to shorten it. Step pre-shoot and ringing frequency aren't reliable yet |
| `all` | Everything above except `volsweep` and `impulse`, in that order. `all --with-impulse` adds `impulse` at every `--fs`, **last**, so a missed trigger (UPL waits until STOP is pressed) can't cost the other results; it accepts `impulse`'s options (`--avg`, `--slope`, …). Off by default for that hang risk more than the time (+~4½ min on GPIB, +~9–10 min on RS‑232 at four rates, against ~26 min for `all` on GPIB). Not every test runs at every `--fs`: `stability`, `zout`, `polarity`, `multitone`, `linearity`, `imdlevel` run at the first rate only; `jitter` and `jtest` at the rates ≤ 48 kHz; `interface` at 48 kHz (or the first rate). Uses −10 dBFS for `fr`, −1 for `fft`/images, −3 for `imd` |

**Options.** General options go **before** the test name, and a test's own options go **after** it:
`dac_test.py --port COM7 --fs 48000 fr --points 61`. `python measurements/dac_test.py --help` and
`... <test> --help` list them too.

| General option | Default | Does |
|---|---|---|
| `--port` | — | UPL: `COMn` or `GPIB0::20::INSTR` (not needed with `--dry-run`) |
| `--baud`, `--timeout` | 115200, 30 s | serial speed; per-reply timeout |
| `--dry-run` | | no instrument; prints the SCPI, canned replies |
| `--source upl\|pc` | `upl` | signal source (see above) |
| `--device N` | | `--source pc`: output device index (`upacd_test.py devices`) |
| `--shared` | | `--source pc`: allow Windows shared mode (resampled, results suspect) |
| `--fs` | `44100,48000,88200,96000` | comma-separated sample rates to test at. `--source upl` accepts only these four; with `--source pc`, any rate the device takes |
| `--bits` | 24 | word length sent to the DAC (`OUTP:AUD`) |
| `--settle` | 0.3 s | wait after each generator change (use ~0.5–0.6 with `--source pc`) |
| `--relock` | 2.0 s | wait for the DAC to relock after a rate change |
| `--ground` | | `INP:LOW GRO` instead of `FLOat` |
| `--stepped` | | `fr`/`thdn`: step the frequency from the PC instead of the UPL's native sweep |
| `--preserve`, `--state-file` | | snapshot the UPL setup first and restore it at the end (`MMEM:STOR:STAT 2`) |
| `--no-reset` | | skip the initial `*RST` |
| `--stay-remote` | | leave the UPL in REMOTE (default: hand the front panel back at the end) |
| `--dut NAME`, `--dut-port`, `--volume dB` | port COM2 | control a supported DUT (see above); `--volume` needs `--dut` |
| `--set-level` | | run the guided `setlevel` step first, then the test(s) |
| `--target V` | | `setlevel`: output to reach at 0 dBFS (V rms); without it, find the loudest clean setting |
| `--max-time` | 600 s | `setlevel`: stop the tone after this long even without Enter |
| `--dut-spec NAME\|FILE` | | print a DUT's published figures next to each result |
| `--label`, `--outdir` | `dac` | where results go (see [Where results go](#where-results-go)) |

| Test | Its options (defaults) |
|---|---|
| `fr` | `--start 10` `--stop` (20 kHz, or 0.45·fs with `--wide`) `--points 31` `--level -10` dBFS `--repeat 2` `--wide` (to 0.45·fs on the 100 kHz analyzer) |
| `thdn` | `--analyzer A22` (`A100`, or `A22,A100`) `--freq-level -1` (dBFS for the vs-frequency sweep) |
| `fft` | `--freq 997` `--level -1` `--analyzer A22` `--images` `--image-freq` (default 19 kHz) `--fft-avg 4` |
| `imd` | `--level -3` `--imd-fft` (also FFT the CCIF signal for aliases) `--fft-avg 4` |
| `jitter` | `--ui 0.1` (max 0.25) `--jfreqs 100,300,1000,2000,5000,8000` `--cable` `--fft-avg 4` |
| `jtest` | `--jbits 24,16` `--fft-avg 4` |
| `multitone` | `--mt-level -1` (total peak, dBFS) `--fft-avg 4` |
| `filter` | `--fft-avg 16` |
| `stability` | `--readings 20` `--monitor 0` (seconds of live L/R level streaming afterwards) |
| `volsweep` | `--volumes -20,-15,-10,-6,-3,-1,0,1,3,6,10` `--level -1` |
| `impulse` | `--period 0.01` s `--imp-level -3` dBFS `--avg 8` `--trig-frac 0.02` `--slope rise` (`fall` for an inverting DAC) `--trig-timeout 20` s |
| `all` | `--with-impulse` (add `impulse`, last), plus `impulse`'s options |

`setlevel`, `check`, `xtalk`, `zout`, `polarity`, `interface`, `linearity` and `imdlevel` take no
options of their own; `all` uses the defaults above for every other test.

**Response above 20 kHz:** `fr --wide`, or `fr --stop <Hz>`. A stop above 21 kHz switches to the
100 kHz analyzer (A100) by itself. The sample rate sets the ceiling: a DAC can't output anything
above fs/2, so at 44.1/48 kHz `--wide` only reaches 19.8/21.6 kHz. Use `--fs 88200,96000` (to
39.7/43.2 kHz), or `--source pc` at 192 kHz (to ~86 kHz). A100 can't make the selective reading
below ~60 Hz and is about 3× noisier than A22, so run a normal `fr` too for the bottom of the
range. For the stopband and images above fs/2, use `filter` or `fft --images`, not a sweep.

The test is the same for every DAC. Optionally, `--dut-spec <name>` prints a DUT's published
figures under each result, from `measurements/dut_specs/<name>.json` (format in that folder's
README). One is included: `elektor-dac2000` (Elektor Audio DAC 2000, Elektor Electronics
11/99–1/2000).

**Comparing with Audio Science Review:** `jtest`, `multitone`, `linearity`, `imdlevel` and `filter`,
plus `thdn` (which prints SINAD = −THD+N at 0 dBFS), `fr` and `fft`, cover ASR's standard DAC set. Set the DAC to 2 V unbalanced /
4 V balanced at 0 dBFS first if it has a volume control. Caveat: the UPL's own THD+N floor is
about −110 dB on a DAC (the M51 read −110 to −113; −103 when latched, see below), far above
ASR's APx555, so SINAD numbers past ~105 dB are mostly the UPL's limit, not the DAC's. Everything else (response, images, jitter lines, linearity,
crosstalk) stays comparable.

88.2/96 kHz need B29's high rate mode (`CONF:DAI HRM`), which Vol.2 says also degrades the analog
analyzer somewhat, so it's switched on only for those rates and back to `BRM` at the end. Output
goes to `results/dac/<label>_<timestamp>/` (git-ignored): `report.html` with a graph for each
test (frequency response L/R selective and broadband, L−R per pass, THD+N and THD vs level and
frequency, spectra, crosstalk, jitter sidebands, linearity...), a CSV per test, and
`summary.txt`. Every config command is error-checked, and anything the UPL rejected is listed at
the end of the run.

**Run live with `--source upl` (2026‑09‑24/25):** every test in the table above except `volsweep`,
on three DACs at 44.1–96 kHz, over RS‑232 and GPIB (results under `results/dac/`). `impulse` ran
live for the first time on 2026‑09‑25; its step pre-shoot and ringing-frequency figures aren't
reliable yet. The UPL quirks found on the way are
handled in the script (see `CLAUDE.md`). One to know about: THD+N of a clipping 0 dBFS tone
leaves the analyzer's THD+N floor ~6 dB worse until a native RMS sweep or a power cycle, so
`thdn` clears it itself; if THD+N readings elsewhere look ~6 dB high, that's the cause. `thdn`'s
`STILL LATCHED?` warning fires whenever the reset check reads above −106 dB, so on a DAC whose
own THD+N is worse than that (e.g. −84 dB) it's a false alarm.
**Not yet run live:** `--dut` / `--volume`, `volsweep`, and `--source pc` into a real external DAC (only the laptop's own output so far).

### Analog DUT characterization: preamps and friends (`measurements/analog_test.py`)

The DAC suite's analog sibling, for anything analog in and analog out: a line preamp, a phono
stage, a mic pre, a buffer. The UPL's analog generator drives the DUT's inputs, and its analog analyzer
measures the outputs. Same results folder layout, same report, and the same UPL workarounds (it
reuses `dac_test.py`'s rig). All levels are **volts rms at the DUT's input** (`--vin`), not dBFS.

**Needs only a base UPL with UPL‑B4 (remote).** Sines come from the standard generator
(2 Hz–21.75 kHz). Its residual THD+N (about −103 dB, 22 kHz bandwidth) sits well below almost
any preamp. If `*OPT?` lists **UPL‑B1** (low-distortion generator), the script uses it for sines
automatically: a floor a few dB lower, THD around −122 dB, and frequency response to 100 kHz
(`fr --wide`). Without B1, `--wide` stops at 21.75 kHz and says so. `--no-lowd` forces the
standard generator even when B1 is fitted.

#### Analog quick start

UPL generator outputs → DUT inputs (XLR, or `--unbal` for the BNC output into RCA inputs); DUT
outputs → UPL analyzer inputs 1 and 2. **Nothing else on the DUT's outputs: no power amp, no
headphones.** `thdn` deliberately drives the DUT into clipping.
```bash
python measurements/analog_test.py --port COM7 --vin 0.5 check
python measurements/analog_test.py --port COM7 --vin 0.5 --set-level --target 2 --label mypre all
```
- `check` must say `signal: OK`. It also prints the gain, L−R, **DC offset at the output** (check
  this before a power amp ever sees the DUT), and absolute polarity.
- `--set-level --target 2` (or `--gain 12`) walks you through turning the volume until 0.5 V in
  gives 2 V out, then runs everything. A fixed-gain DUT: leave it out.
- Phono stage: `--vin 0.005 --vmax 0.2` for MM (0.0005 for MC), and `fr --riaa` (or `--riaa-iec`)
  prints and plots the deviation from the RIAA playback curve.

#### Tests

| Test | What it measures |
|---|---|
| `setlevel` | guided: live output V, gain and THD while you turn the knob toward `--target`/`--gain` |
| `check` | gain and L/R balance at 1 kHz, DC offset at the output (input idle), polarity |
| `fr` | frequency response, broadband and selective (a difference = hum/noise/oscillation), −3 dB points, L−R; `--wide`, `--riaa` |
| `thdn` | THD+N and THD vs frequency at `--vin`; then vs input level, in 2 dB steps up to clipping: input and output at **0.1 % and 1 % THD+N** (maximum output, input overload) |
| `noise` | input terminated by the muted generator (`--zgen`, 10 Ω by default): output noise at 22 kHz, A-weighted, CCIR‑2k (ARM) and 110 kHz; S/N re `--ref-out` (default: the output at `--vin`); **EIN** in dBu and nV/√Hz; hum lines of the idle output |
| `fft` | spectrum of 1 kHz at `--vin`: harmonic signature, hum |
| `imd`, `imdlevel` | SMPTE 60 Hz + 7 kHz 4:1 and CCIF 19 + 20 kHz; at `--vin`, and vs input level. `imd` also moves SMPTE's upper tone (2/4/7/12 kHz) and reports dB/octave: rising ≈ a nonlinearity that grows with frequency (feedback running out, slew), flat = static, falling = an LF mechanism (coupling cap). Each IMD reading is repeated until two agree within 0.3 dB (the DCX2496 drifts ~2–3 dB over the first ~30 s) |
| `xtalk` | crosstalk both ways, selective, 100 Hz–20 kHz |
| `zout` | output impedance (analyzer 200 kΩ vs 600 Ω load) |
| `zin` | input impedance at 1 and 20 kHz (generator source 10 vs 600 Ω; XLR output only) |
| `multitone` | 17-tone multisine, products between the tones |
| `all` | all of the above except `setlevel` |
| `tracking` | guided, not in `all`: volume-control L/R tracking, one reading per knob position |
| `cmrr` | guided, not in `all`: balanced-input common-mode rejection (asks you to feed the BNC output into XLR pins 2+3 joined) |
| `gainlaw` | needs `--dut`: the DUT's own gain setting stepped (default −15…+15 dB), measured vs set |
| `xover` | needs `--dut`: crossover filter types (`--types`) at each cutoff (`--freqs`), high- or low-pass (`--side`); −3/−6 dB points and stopband slope per curve |
| `limiter` | needs `--dut`: output vs input with the DUT's limiter on (`--thresh`), where limiting starts |

**One-channel DUTs** (a mic pre, or one output patched): `--mono` reports analyzer CH1 only.
**A DUT the PC controls:** `--dut dcx` (Behringer DCX2496) sets its output flat first and adds
`gainlaw`, `xover` (filter types and cutoffs: −3/−6 dB points, slope) and `limiter` to `all`;
`--dut-asis` measures it as it is set up. See [DCX2496_README.md](DCX2496_README.md).

`--dut-spec NAME|FILE` prints published figures next to results, as for DACs (keys: `gain dc fr
thdn maxout snr ein imd xtalk zout zin cmrr`). A preamp with a volume control ahead of its active
stage has an input overload that depends on the knob, so `thdn` reports it *at the current
setting*. Turn it down and rerun to find the input stage's own limit.

**First live run 2026‑09‑25: `all` on the DCX2496 (two outputs), clean — no command rejected.**
Results and the SMPTE follow-up are in `CLAUDE.md` ("First live `analog_test.py all`"). Not yet run
on a preamp, a phono stage (`--riaa`), without B1, or `--unbal`/`cmrr`/`tracking`.

### Test-signal files for any DAC or player (`tools/testsignals.py`)

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
# PC plays into a DAC (any USB DAC, a player in USB-DAC mode...)
python measurements/upacd_test.py --upl-port COM7 --device N --exclusive --label mydac_96k \
    --wav testsignals/96k_24/11_level_staircase.wav linearity
# the DUT plays the copied file itself (a DAP's own playback): press play when told
python measurements/upacd_test.py --upl-port COM7 --external --label dap_96k \
    --wav testsignals/96k_24/10_third_octaves_-6dBFS.wav segments
```

Linearity is referenced to the staircase's first step, not the marker, so the DUT's 1 kHz-vs-2 kHz
response cancels. Verified offline against a simulated DUT with an unknown start delay, markers
rejected by the selective filter and no frequency lock below −90 dBFS: all 15 steps were found,
a planted 0.5 dB error at −100 dBFS came back out, and −120 dBFS read the correct noise-limited
+0.9 dB. Not yet run live.

### UPA-CD test-disc playback (`measurements/upacd_test.py`)

Plays R&S Audio Test Disc tracks from this PC into any DUT while the UPL measures. The DUT is
whatever sits between the sound device and the UPL's analyzer input, so the same script covers a
USB DAC, a DAC or processor further down the chain, or **this laptop's own output** — just point
`--device` at a different output and `--label` the run:

```bash
python measurements/upacd_test.py devices                       # find the output index

# a USB DAC
python measurements/upacd_test.py --upl-port COM7 --device N --exclusive \
    --label mydac_44k linearity

# the laptop's own headphone/line output (needs a 3.5mm -> XLR adapter into the UPL)
python measurements/upacd_test.py --upl-port COM7 --device N --exclusive \
    --label laptop_builtin linearity

# any stepped-tone track, generic
python measurements/upacd_test.py --upl-port COM7 --device N --exclusive segments \
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

Tracks are read straight out of the zip in `external/upa-cd/` — no need to unpack 809 MB. `--dry-run` exercises
the whole pipeline, segmentation included, with no instrument and no audio device.

**Level warning:** several disc tracks sit at 0 dBFS and the booklet warns they are "much higher
than conventional program sources". Straight into the UPL analyzer that is fine; through an
amplifier into speakers it is not. `CLAUDE.md` has the full track listing.

### Analyzer filter checks (`measurements/filter_test.py`)

Internal loopback only (`INP:TYPE GEN2`), so nothing needs to be patched. Two parts:

- **Bandwidth-limited THD+N**: runs with no filter, then with a 5 kHz user lowpass that is
  defined but not routed, then with 20/10/5/3 kHz lowpasses that *are* routed into a filter slot.
  It shows that a user filter does nothing until it's routed (`SENS:FILT1:UFIL1 ON`).
- **FFT through a filter**: white noise from the generator, 8k FFT, read unfiltered, through
  A‑weighting, and through a 1–5 kHz user bandpass.

```bash
python measurements/filter_test.py --port COM2      # -> results/filter_test/loopback_<time>/
```

Sends `*RST` first; leaves filters off and the generator at 0 V. Keep user lowpass cutoffs at or
below 20 kHz on the A22 analyzer: 22 kHz is accepted when defined but rejected when routed, and the
filter then refuses further changes.

### Soundcard audio-analyzer suite

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
python audio_tests.py response --label laptop          # PLAYS a stepped-sine sweep
```

## Equipment-specific control

Tests that also *control* a particular unit over its own serial port have their own guides. For
the measurements themselves, prefer the general suites above; these cover only what that unit's
remote control adds.

| Guide | Unit | Adds |
|---|---|---|
| [DCX2496_README.md](DCX2496_README.md) | Behringer DCX2496 crossover | `dcx2496.py` driver; crossover/EQ/gain set by the PC and measured by the UPL (`measurements/analog_test.py --dut dcx`, `measurements/dcx_balanced_test.py`) |
| [M51_README.md](M51_README.md) | NAD M51 DAC | `nad_m51.py` driver; `dac_test.py --dut m51` (volume set/restore, `volsweep`) |

To add a unit: a driver module at the top level, a class in `dac_test.py`'s `DUTS` if it's a DAC
with a volume control, and a `<UNIT>_README.md` here.

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
| top level | UPL control (`upl_capture.py`, `ser_in.py`), `report.py` (results folders + reports), `upl_selftest.py`, `audio_tests.py`; DUT drivers and their tools (`dcx2496.py`, `nad_m51.py`, see the equipment guides) |
| `measurements/` | characterization scripts: each drives the UPL (and usually a DUT) through one test and writes a results folder |
| `tools/` | utilities: disk/file backup, SNDFILE batch transfer, LZH extraction, test-signal generator |
| `external/`, `DISK1/`, `DISK2/` | third-party files (manuals, app notes, UPA‑CD, B23 data, firmware disks, DUT docs), **git-ignored** except a README in each saying what goes there |
| `testsignals/` | generated test WAVs, **git-ignored** — rebuild with `tools/testsignals.py` |
| `results/` | one folder per run (`results/<test>/<label>_<timestamp>/`, see [Where results go](#where-results-go)), `index.html`, and the instrument backups `CAL/`, `DISK/`, `REF/`. **git-ignored** (it holds the serial number, option key and calibration) |

## Where things are documented

- **`CLAUDE.md`** — the full working log: firmware/hardware analysis, every SCPI command
  confirmed and how, every bug hit and its fix, every measurement result with its reference
  numbers, and the reasoning behind every tool's design. The authoritative source if this README
  and the code ever disagree.
- **`SELFTEST_README.md`** — standalone guide for `upl_selftest.py`.
- **`DCX2496_README.md`**, **`M51_README.md`** — per-device guides for units the PC also controls.
- **`dcx2496_protocol.md`** — the DCX2496's full reverse-engineered serial protocol, verbatim.
- **`external/`** — original R&S documentation (manuals, application notes, the factory selftest
  program) and other third-party files, not in git; see [external/README.md](external/README.md).
  `CLAUDE.md` has a topic-by-topic catalog of the application notes.

## Acknowledgements

This project would not exist without the diyAudio thread
[*Rohde & Schwarz R&S UPL audio analyzer renovation*](https://www.diyaudio.com/community/threads/rohde-schwarz-r-s-upl-audio-analyzer-renovation.353461/)
and the people in it. Most of the material everything here was built on came from there: the
3.06 firmware, the operating and service manuals, the application notes, the UPL‑B23 coded-audio
library, the UPA‑CD test disc, and a second unit's selftest report to compare against. Thanks to
everyone who has shared documents, photos and hard-won repair knowledge there.

Special thanks to **Bart Vande Keere** (BVKSound), who started it all. His work is used throughout
this project: the UPL‑B23 coded-audio repack, a UPL‑B10 BASIC example, and a KiCad re-creation of
the UPL‑B1 low-distortion generator schematics,
[github.com/bvksound/UPL-B1](https://github.com/bvksound/UPL-B1).
