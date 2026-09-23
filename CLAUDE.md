# R&S UPL — analysis, modernization, and data‑egress project

Working notes for the Rohde & Schwarz UPL audio analyzer. Captures what we found in the
v3.06 firmware install media and the plan/tools for (a) keeping the instrument alive long‑term
and (b) getting measurement data off it easily. Last updated 2026‑09‑23.

**For "how do I actually run the tools/tests," see `README.md` (general) and
`SELFTEST_README.md` (standalone, for `upl_selftest.py`) — both added 2026‑09‑23. This file
(`CLAUDE.md`) is the working log/narrative: what was tried, what broke, what was found, and why
things are built the way they are. The READMEs are the quick-start; this is the deep reference.

**Correction, 2026‑09‑23:** several scripts described below as "ephemeral"/"not in this repo"
(in the AppData temp scratchpad) have since been cleaned up and promoted into this project's own
permanent `scratchpad/` folder (with `argparse` CLIs replacing their original hardcoded
COM2/COM7/temp-path values) — `dcx_thdn.py`, `dcx_thd_vs_thdn.py`, `dcx_gauntlet.py`,
`dcx_balanced_test.py`. They're real, runnable, documented in `README.md` now. Also discovered/
catalogued in this pass: a substantial **NAD M51 DAC** control module + test suite
(`nad_m51.py` + `scratchpad/m51_*.py`) that was built earlier in the project but not previously
described in this log in detail — see `README.md` for what each one does and how to run it.

## Goal / context

- The user owns a working R&S UPL audio analyzer and wants: (1) a hedge against the internal
  CPU board becoming unobtainable, and (2) an easier way to get measurement data off it than
  the current **Gotek floppy‑emulator kludge** (which writes floppy *images* to USB that then
  need special software to unpack).
- This directory is the **UPL firmware 3.06 install media** (self‑extracted from `UPL_306.EXE`,
  R&S download, 2006). `DISK1` = program disk, `DISK2` = examples disk. Archives are **LHA/LZH**.

## How to extract the install media

The `.LZH` archives are LHA. Windows' built‑in **bsdtar** (libarchive) reads them directly —
the Git‑Bash `tar` (GNU) does not:

```
& "$env:SystemRoot\System32\tar.exe" -xf DISK1\UPL.LZH -C <dest>
```

`LHA.EXE` is a 16‑bit DOS tool and will not run on 64‑bit Windows. `X_DATA.EXE` / `UPL_306.EXE`
SFX are not bsdtar‑readable (not needed — they're example data / the outer self‑extractor).

## Instrument architecture (reverse‑engineered from the firmware)

- The UPL is a **DOS PC on a passive ISA backplane** plus the measurement cards. Boot chain:
  `ROOT/AUTOEXEC.UPL` + `CONFIG.*` load HIMEM/EMM386, detect the CPU, then run `UPL\UPL.BAT` → `UPL_UI.EXE`.
- **`DISK1/UPL/UPL_UI.EXE`** (1.6 MB, **16‑bit Borland C++**) is the entire instrument application.
  It drives the measurement hardware by **direct ISA port I/O + IRQ + DMA** and loads the DSP images.
  **There is no separate driver, DLL, or documented register map for the measurement hardware** —
  it's all baked into this closed‑source binary.
- **DSPs are TMS320C3x** (floating‑point). Images in `DISK1/DSP/` are **TI COFF** (magic `0x0093`):
  `A.OUT` = generator/analyzer control (`genisr`, `anaisr`), `B.OUT` = FFT engine (`real0/imag0…`,
  `sintable`), plus `LOADER.OUT`, `DUMP.OUT`.
- **`DISK1/DRIVER/*.SYS`** are DOS char drivers for *peripherals only*: `IECX`=IEEE‑488/GPIB,
  `GRAPHX`=display, `STRINX`=front‑panel console/keyboard, `BEPX`=beeper, `COMX`=serial.
- Calibration is per‑board and serial‑locked (`SETUP/CAL_*.SET`, `CAL_DIG.SAC`) — irreplaceable state.

### Feasibility verdict on "modern PC + USB‑to‑ISA bridge"
**Not viable** for running the measurement hardware: no register documentation, and USB adds
latency and can't service ISA IRQ/DMA in real time. The realistic path is to **keep the original
firmware running on an ISA‑bus CPU** and modernize *around* it (data egress over serial/GPIB).

## CPU‑board longevity (the "unobtanium" concern) — GOOD NEWS

The CPU board is the **least R&S‑proprietary part** and is replaceable from the industrial‑PC market.

- **No board lock.** `TOOLS/CPU.EXE` only detects CPU *class* (286/386/486/586/686); `AUTOEXEC.UPL`
  maps that to `BOARD` (486→`UM486`, 586→`UM586`, else `SX386`). No dongle, no board‑ID handshake.
- **Original boards:** an **AI5VG+** (half‑size Socket‑7 PICMG SBC, onboard VGA) *or* a **Kontron
  Geode GX1** module on a carrier. Both 586‑class → firmware sees `UM586`.
- **The slot (schematic X6)** is a **standard full 16‑bit ISA (AT) slot**, fully populated, and the
  **CPU card is powered entirely from the slot** (+5V B3/B29/D16, +12V B9, −5V B5). No PICMG PCI
  section, no aux power connector.
- **Video/LCD/IDE/FDC live on the UPL mainframe** as their own ISA cards (**Cirrus Logic** VGA),
  **not** on the CPU board. So a CPU swap does not touch the display/storage path, and `GRAPHX`
  (Cirrus‑specific) keeps working.

### Replacement CPU spec (drop‑in target)
- Single **16‑bit ISA card**, bus‑powered from +5V, mechanically fits the UPL card cage.
- **586‑class x86 running DOS** (→ `UM586`). Moderate clock to avoid DOS delay‑loop timing bugs.
- **Onboard VGA / IDE / FDC must be disable‑able** so they don't collide with the mainframe's
  Cirrus VGA (A000/B800, 3C0–3DF), IDE (1F0/170), FDC (3F0). This is the only real constraint.
- Must tolerate/ignore **−15V on B7** (the UPL busses −15V onto the standard −12V pin).
- Best candidate: an **ICOP/DMP Vortex86 ISA SBC** (native DOS, real ISA, VGA/IO disable‑able).
  Zero‑risk alt: NOS **AI5VG+** or sibling Socket‑7 half‑size card.

### Longevity action plan (priority order)
1. **Image the mainframe boot disk (raw) and archive the calibration data NOW** — the only
   irreplaceable state. (Board is replaceable; its stored state is not.)
2. **Buy a NOS spare** (AI5VG+ or Geode module), or a donor UPL — zero‑engineering insurance.
3. **Qualify one Vortex86 ISA SBC** (VGA/IDE/FDC disabled) as the reproducible long‑term fallback.

## Installed options (confirmed by user, 2026‑09‑22) — ALL options fitted

Hardware:
- **UPL‑B1** — Low Distortion Generator (ultra‑low‑THD analog gen; measure the DUT, not the instrument).
- **UPL‑B29** — Digital Audio I/O, 96 kHz (AES3/EBU + SPDIF generate & analyze; 32/44.1/48/88.2/96 kHz,
  variable 35–106 kHz, high‑rate mode). (B2 = the base 55 kHz variant; user has the 96 kHz B29.)
- (UPL‑B5 speaker/monitor — hardware; assume fitted per "all options".)

Software (user has ALL software options):
- **UPL‑B4** — Remote Control (SCPI over IEC/GPIB and RS232/COM2).
- **UPL‑B6** — Extended Analysis Functions.
- **UPL‑B10** — Automatic Sequence Control (on‑instrument test scripting / UPL‑BASIC sequencer).
- **UPL‑B21** — **Digital Audio Protocol** (in-depth AES3/S-PDIF protocol analysis + generation,
  extends B2/B29; confirmed via brochure, see below). Pairs with 1GA36's `PROT*_DD.SAC` setups.
- **UPL‑B22** — **Jitter and Interface Test** (runs on B29 digital hw; jitter‑sideband DAC demo
  IS available; confirmed via brochure).
- **UPL‑B23** — Coded Audio: decode/analyze AC‑3 / MPEG / DTS bitstreams (IEC 61937) over SPDIF.

No option caveats — full capability across analog, digital (≤96 kHz), jitter, protocol, and
coded‑audio domains. (`*OPT?` on the instrument, 2026-09-22, also showed a bare "B21" among the
option tokens, which is now identified above — previously flagged as unknown.)

### User's DUTs and tailored tests
- **Behringer DCX2496** (DSP speaker management, XLR analog + AES/EBU): verify crossover filter
  slopes via UPL sweep, THD+N/noise/dynamic range of its converters, latency, channel matching,
  digital‑in→analog‑out (via B29).
- **SPDIF DAC**: UPL generates SPDIF (B29) → DAC → UPL analog analyzer: THD+N@0dBFS, −60 dBFS
  linearity, dynamic range, frequency response, DC offset, across 44.1/48/96 kHz. (No jitter
  analysis — needs B22.)
- **Turntable** (needs test LP): wow & flutter, speed error, rumble, RIAA conformance, crosstalk.
- **miniDSP UMIK‑1** (USB calibrated mic): does NOT connect to the UPL (USB audio). It's the
  acoustic front‑end for the **laptop** (`audio_tests.py`) — apply its per‑serial cal file; do
  speaker/room frequency response, distortion vs SPL, RT60. Pairs with laptop‑as‑generator, or
  combine with UPL for electro‑acoustic transfer (UPL = electrical, UMIK‑1 = acoustic).

## Data egress (the main goal) — solution: RS232/GPIB remote, option UPL‑B4

- **The user HAS option UPL‑B4 (Remote Control).** This enables SCPI over **IEC/GPIB or RS232 (COM2)**.
  (Without B4 there is no SCPI on any port; fallbacks would be EXPORT‑to‑file + better retrieval.)
- Retire the Gotek: pull data over a **USB‑serial cable to the UPL rear COM2**, or a USB‑GPIB adapter.

### RS232 remote protocol (verified from `DISK2/IEC_EXAM/RS232_BT.BAS`)
- UPL **COM2**: **8 data, no parity, 1 stop, RTS/CTS handshake**, baud 2400–19200 (use 19200).
- Set OPTIONS panel: remote → **COM2**, and the COM2 params above.
- Cable: R&S **1050.0346**, or a 9‑pin **null‑modem cable with full RTS/CTS**; USB‑serial adapter
  must expose real RTS/CTS.
- **Every command sent is LF‑terminated (`\n`); every reply is LF‑terminated.**
- Check remote is live: `*IDN?` → reply contains "UPL" (and the UPL REM LED lights).
- Files come back as IEEE‑488.2 block: `#<n><len><bytes>`.

### SCPI vocabulary confirmed present (from EXAM*.BAS and the EXE string table)
- Control: `*IDN?`, `*RST`, `*WAI`, `*OPC?`, `SYST:ERR?`
- Trigger/sweep: `INIT;*WAI`, `INIT:CONT OFF`, `INIT:FORC STOP`
- Setups: `MMEM:LOAD:STAT 0,'C:\UPL\X.SAC'`
- Values: `SENS:DATA?`,`SENS2:DATA?`,`SENS3:DATA?`,`SENS4:DATA?` (ch1); `…:DATA2?` (ch2).
  Not-available reads return the SCPI sentinel `9.93e37`.
- **Internal loopback (CONFIRMED live 2026‑09‑22):** `INP:TYPE GEN2` routes analyzer input ← internal
  generator (only valid from a known/analog state — after `*RST`; rejected `-222` while in a digital
  config). `INP:TYPE?` reports e.g. `INT`.
- **Analyzer function select (CONFIRMED):** `SENS1:FUNCtion '<NAME>'` — the name MUST be a **quoted
  string** (`'RMS'`,`'THD'`,`'THDN'`,`'DFD'`…); unquoted → `-141 Invalid character data`.
- Self-test result: after `*RST; INP:TYPE GEN2; SOUR:FREQ 1000 HZ; SOUR:VOLT 1.0 V; INIT;*WAI`,
  read 0.999 V / 1000.08 Hz / peak 1.413 V.
- **`*OPT?` (2026‑09‑22)** → `B1(0.01),B29(2.16),B21,B22,B4,B5(1.62),B6,0,B10,0,B23,0` — all options confirmed.
- **Low Distortion Generator (B1):** `SOUR:LOWD ON|OFF` (CONFIRMED). `*RST` defaults it OFF (standard gen).
  Loopback 1 kHz/1 V THD+N: OFF −103.1 dB, ON −106.7 dB. **THD (harmonics only, B1 ON) = −122.1 dB**
  (THD+N is noise‑limited over full BW, not generator‑limited — B1 performs to spec).
  `LOWD` frequency precision = `Setting` FAST|PRECISION; LDG cal via OPTIONS `CAL LDG` (2 h warmup).
  Note: DC offset and Low Dist can't be enabled together.
- Bandwidth-limit for THD+N (SOLVED via Vol.2 manual §2.7/3.10.3, PARTIALLY verified live):
  Real syntax is **`SENSe[1]:FILTer<i>:<NAME>[:STATe] ON|OFF`** (i=1..3 = filter slot) for built-in
  named filters — confirmed working example from manual: `SENS:FILT:AWE ON`, `SENS:FILT2:UFIL5 ON`.
  NAME ∈ AWEighting, CCITt, CCIRweight, CCIUnweight, CMESsage, DEMPhasis, CARM, JITTer, WRUMble,
  URUMble, DCNoise, UFILter1..9 (+HPASs/LPASs/BPASs/BSTOp/NOTCh/TOCTave/OCTav/FILE as filter *types*).
  Separately, **`SENSe[1]:UFILter<n>:HPASs|LPASs|BPASs|BSTOp|NOTCh[:STATe] ON`** (n=1..9) defines a
  user filter's type; cutoff via `SENSe[1]:UFILter<n>:PASSb[:LOWer|:UPPer] <Hz>` (also `:CENTer`,
  `:WIDTh`, `:ATTenuation`, `:ORDer`, `:DELay?`).
  LIVE TEST 2026‑09‑22: `SENS1:UFILter1:LPASs ON` + `SENS1:UFILter1:PASSb 22000` — both accepted
  (`0,"No error"`) but THD+N barely changed (−106.56→−106.65 dB). Hypothesis: defining a UFILter
  does not itself route it into the active measurement chain — per the manual's own example
  (`SENS:FILT2:UFIL5 ON`), the filter likely also needs to be **assigned to a filter slot** via
  `SENS:FILT<i>:UFILter<n> ON` (i=slot 1‑3) to actually engage it. NOT YET CONFIRMED — try that
  assignment step next time, and/or just read §3.10.3/§2.7 in Vol.2 directly (page ~3.163 in PDF).
  Manuals: `R&S_UPL_Audio_Analyzer_Op_Vol_1.pdf` / `_Vol_2.pdf` one level up from this folder, at
  `C:\Users\Sy Ming\Downloads\R&S UPL\`. Vol 2 = remote/IEC‑bus command reference (confirmed).
  Extract text for searching with `pdftotext -layout <file> out.txt` (available in this env).
- Unrecognized *query* names cause a read timeout (no reply); unrecognized *set* commands just queue an
  error (safe). Check/drain with `SYST:ERR?` (FIFO, one entry per query; `0,"No error"` = empty).
- Trace: `TRAC:POIN? TRAC1`, `TRAC? TRAC1` (comma‑separated), x‑axis `SOUR:LIST:FREQ?`
- Source cfg (EXAM7): `SOUR:SWE:MODE AUTO`, `SOUR:FREQ:MODE SWE2`, `SOUR:FREQ:STAR/STOP`, `INP:TYPE`,
  `SENS:FILT:AWE`, `DISP:CONF`, `CALC:EQU:INV`, `SOUR:VOLT:EQU:STAT`
- File mgmt (MMEM children in EXE): `STORe`, `DATA`(`MMEM:DATA? 'file'`), `CATalog`, `DELete`,
  `CDIRectory`, `COPY`, `CHECk` (checksum, matched by `UPMD5.EXE`)
- Data format node: `FORMat` = `BIN | ASCii | EXPort`. Trace‑list store format REAL/ASCII/**EXPORT**;
  EXPORT = readable numbers in display units, Excel‑ready (no header/footer).
- **STILL UNCONFIRMED:** the exact SCPI to make the UPL *store a trace list to a file remotely*.
  `MMEM:STOR:LIST <type>,'file'` is confirmed for lists (equalization). To be probed live against
  the instrument (try candidates, check `SYST:ERR?` = `0,"No error"` + `MMEM:CAT?` for a new file).
- **CORRECTION (from App Note 1GA42_0E, 2026‑09‑22):** `upl_capture.py`'s `getfile` (built on
  `MMEM:DATA? 'file'` as a 488.2 block read) was written **by symmetry** with the confirmed
  PC→UPL upload direction (`RS232_BT.BAS`) and **was never actually tested against real hardware**.
  1GA42_0E explicitly states bulk file transfer **UPL→PC is NOT generally supported over the bus**
  — R&S built a dedicated workaround instead (below). Treat `getfile` as unverified/likely wrong
  until tested; the SNDFILE/SER_IN route is the R&S-documented path for pulling a file off the UPL.

## UPL→PC file transfer: the real R&S mechanism (App Note 1GA42_0E)

Source: `Application Notes/1GA42_0E_...RS-232-C Interface.pdf` (one dir up from this project).
Utilities `SNDFILE.BAS`, `SER_IN.EXE`, `DRV_INST.BAS` are already present in the firmware's
`DISK2/USER/` (so should already be at `C:\UPL\USER` on the real instrument). Requires **UPL‑B4**
and **UPL‑B10** (user has both).

**Wire protocol (read directly from `SNDFILE.BAS`, firmware 3.06):** UPL's COM2 opens at
**115200 baud ("115000"), no parity, 8 data, 1 stop, RTS/CTS handshake**. UPL reads the source
file in 1024‑byte chunks and writes raw bytes to the port — **no length header, no end marker**.
The receiver must detect completion by **idle timeout** after the last byte (this is exactly what
`SER_IN.EXE`'s "Timeout" parameter, default 100 ms, is for).

**`SER_IN.EXE` is a 16‑bit DOS program and will NOT run on this 64‑bit Windows PC** (no NTVDM).
Reimplemented as **`ser_in.py`** in this folder (pyserial, idle‑timeout capture) — see its
docstring for full usage. Quick version:
```
# 1. On UPL: Display panel -> Info Text -> type the source path, e.g. C:\UPL\MYTRACE.EXP
# 2. On PC, start the receiver FIRST (must be listening before the send is triggered):
python ser_in.py --port COM2 out\MYTRACE.EXP
# 3. On UPL: OPTIONS panel -> select SNDFILE to start the transfer.
# 4. ser_in.py stops itself on idle timeout and reports the byte count.
```

**Remote/IEC trigger sequence per the app note** (not yet tried live):
```
MMEM:STOR:INFO 'C:\UPL\MYTRACE.EXP'          ; sets the file to send
SYST:PROG:EXEC 'C:\UPL\USER\SNDFILE'          ; runs the macro (waits/checked via *OPC?)
MMEM:STOR:INFO?                               ; reply: "<n> bytes sent <file>" or "file not found"
```
**Important caveat, NOT yet resolved:** the app note's official remote procedure assumes **GPIB**
for the control channel, leaving RS232/COM2 entirely free for SNDFILE.BAS's own raw 115200‑baud
open of that same port. We only have RS232 — sending `SYST:PROG:EXEC` over the *same* COM2 that's
also our SCPI control channel may hit port contention (the UPL's RS232 SCPI handler and
`SNDFILE.BAS`'s own `OPEN "com2:..."` both wanting COM2). Untested. The **manual trigger path**
(front‑panel Info Text + OPTIONS→SNDFILE, PC listener via `ser_in.py`) sidesteps this entirely
and is the safer one to try first.

## Tools in this folder

### `upl_capture.py` — pull data off the UPL over RS232 (needs pyserial; installed)
Subcommands:
- `probe` — `*IDN?` to confirm remote/B4 is live.
- `read` — live values (rms/peak/freq/phase, both channels).
- `sweep -o f.csv` — capture current sweep trace to CSV.
- `autoexport [-o] [--setup] [--both] [--repeat N --interval S] [--opc]` — **trigger a fresh sweep
  and pull trace(s)+x‑axis to a timestamped CSV; no file created on the UPL.** (Primary tool.)
- `catalog [path]` — `MMEM:CAT?` list UPL files.
- `getfile "C:\UPL\X.EXP" -o local` — pull an existing UPL file (488.2 block).
- `raw "SCPI"` — send one command (query if it ends `?`).

Example: `python upl_capture.py --port COM7 probe` then `… --port COM7 autoexport --opc`.

**LINK VERIFIED 2026‑09‑22:** `probe` returned `ROHDE & SCHWARZ, UPL, 3.06, 0.33` — remote/B4
confirmed. Verified on both **COM7** (FTDI) and **COM2** (Prolific PL2303) at 19200 8/N/1 RTS/CTS;
Prolific gave 5/5 stable `*IDN?` across processes AFTER a reboot. NOTE: pre‑reboot the Prolific
(2008 driver) + hub ports caused intermittent "port de‑enumerates / R/W open fails (WinError 2)"
flakiness. If it recurs: reboot + direct laptop USB port + selective‑suspend off on the converter
and USB root hubs. FTDI/CP210x on a direct port is the more reliable choice.

### `audio_tests.py` — soundcard audio‑analyzer suite (numpy/scipy/sounddevice/soundfile; installed)
UPL‑style measurements: level/dBFS/DC, fundamental freq, **THD**, **THD+N**, **SNR/noise floor**,
**frequency response** (stepped sine → CSV), crosstalk. Works on a device, a WAV, or synthetically.
Subcommands: `devices`, `selftest`, `analyze <wav>`, `noise`, `tone`, `loopback`, `response`.
- **Analyzer self‑test PASSES** (recovers 997 Hz / −6 dBFS / THD −59.6 dB exactly) — math validated.
- This PC = laptop **Realtek** codec. Outputs OK; **inputs are mic‑only** (no line‑in) → for a
  laptop‑internal loopback you'd need an attenuator or a USB interface with line‑in.

## R&S factory Selftest program (added 2026‑09‑22) — major SCPI reference

`SELFTEST_Program.TXT` (user-supplied, `C:\Users\Sy Ming\Downloads\R&S UPL\`) is a genuine R&S
factory selftest, written in the UPL's own on-board BASIC (runs locally: `UPL OUT "cmd"` /
`UPL IN var$` address the instrument's own SCPI parser directly, no `IEC OUT <addr>,` needed).
Exercises generator ranges, low-dist gen accuracy, analyzer ranges (18mV–100V @ 1k/40Hz/15kHz),
inherent THD+N/DFD/noise floors, and digital audio — a goldmine of confirmed working SCPI:

- **`INST2 A22` / `INST2 A100`** — selects the **22 kHz vs 100 kHz analyzer bandwidth instrument**.
  `INST D48` / `INST2 D48` selects the **digital 48 kHz instrument** for digital-audio tests.
  (`INST2` = channel-2/second analyzer slot.)
  **LIVE TEST RESULT 2026‑09‑22 — resolved, with a correction:** `INST2?` showed the instrument was
  **already on A22** (the narrow/tight analyzer) the whole session — so the earlier ~−106 dB THD+N
  was NOT a wide-bandwidth artifact; it's the genuine noise floor of the UPL's *tightest standard*
  bandwidth mode, and it easily clears the R&S spec (≤−93 dB). Switching to `INST2 A100` resets the
  active measurement function AND breaks the loopback input routing (returned the "N/A" sentinel
  `9.93e37`) — A100 needs the fuller re-init sequence the selftest program uses (`INST2 A100; INP:SEL
  CH2I; INP:TYPE GEN2; SENS:VOLT:RANG:AUTO OFF; SENS:VOLT:RANG 3V` before it's usable again).
  **Practical rule confirmed: re-issue `SENS1:FUNCtion '<name>'` (and re-check input routing) after
  any `INST`/`INST2` change** — it does not preserve the prior function/routing.
  **Conclusion: no further "bandwidth fix" is needed for THD+N in A22 mode — −106 dB is the real,
  healthy number**, not a fixable measurement artifact. The `SENS:UFILter` avenue from earlier
  remains uninvestigated/parked, but is no longer necessary to explain the THD+N result.
- `DIAG:DEV SERN; DIAG:DEV:ADDR 0|1; DIAG:DEV:DATA?` — reads the unit's serial number (two halves,
  concatenated with `/`).
- `INP:SEL CH2I | BOTH` — select input source per channel. `INP:TYPE BAL|GEN2|INT` — balanced
  physical / internal-generator-loopback (confirmed, matches earlier use) / internal-digital.
  `OUTP:TYPE BAL`. `INP:IMP R300` — input impedance/termination select.
  `SOUR:VOLT 1e-20 V` — practical "mute" trick (near-zero instead of OUTP OFF).
- `CAL:ZERO:AUTO ONCE;*wai` — triggers an auto-zero calibration.
- `SENS:VOLT:RANG:AUTO OFF` / `SENS:VOLT:RANG <n> V` — manual analyzer range control (confirmed
  ranges: 18mV,30m,60m,100m,180m,300m,600m,1,1.8,3,6,10,18,30,60,100 V).
- `SENS2:FUNC 'OFF'` / `SENS3:FUNC 'OFF'` / `SENS3:FUNC 'FREQ'` / `SENS3:FUNC 'SFRE'` — the
  4 function slots (level/peak/freq/phase per earlier EXAM1 finding) are individually assignable;
  `'SFRE'` = sample-frequency measurement (digital).
  `SENS:FUNC 'THDN'`/`'DFD'`/`'RMS'` also confirmed ([1] index optional per SCPI convention).
- **Multitone generator:** `SOUR:FUNC MULT; SOUR:MULT:COUN 2; SOUR:FREQ2 <f>; SOUR:VOLT2 <v>` —
  independent 2nd-tone freq/level.
- **DFD (CCIF-style IMD) generator+measure:** `SOUR:FUNC DFD; SOUR:FREQ:MEAN <f>; SOUR:FREQ:DIFF
  <f>; SOUR:VOLT:TOT <v>; SENS:FUNC 'DFD'` — e.g. 10kHz mean / 200Hz diff for classic D2 IMD test.
  `SOUR:FUNC SIN` selects plain sine back.
- `SOUR:VOLT:LIM <v>` — generator voltage limit.
- **Digital audio:** `INST D48; INST2 D48; INP:TYPE INT; OUTP:AUD 24; INP:AUD 24` (word length);
  `INP:SAMP:FREQ:MODE AUTO`; `OUTP:SAMP:MODE F44` (44.1k) / presumably other Fxx modes for 48k etc.
- Trigger pattern used throughout: `init:cont off;*wai` immediately before each `sens:data?` read
  (repeated after changing a parameter) — observed to effectively retrigger each time; **not fully
  confirmed as the general mechanism**, but matches the codebase's own usage consistently. The
  previously-established `INIT;*WAI` (separate from `INIT:CONT OFF`) also still stands as correct.
- Typical inherent-performance tolerances used by R&S for a healthy UPL (context for judging our
  own readings): THD+N @ 1kHz, 2V, 22kHz analyzer ≤ −93 dB; same in 100kHz analyzer ≤ −84 dB;
  DFD D2 @ 10kHz/200Hz, 2V ≤ −110 dB; inherent noise (22kHz analyzer, 18mV range) ≤ 2 µV, (100kHz
  analyzer) ≤ 8 µV. Our own loopback THD+N (~−106 dB) and THD (−122 dB) are consistent with a
  healthy unit against these references.

## Current live wiring (as of 2026‑09‑23 — PC-side COM ports, may change if cables are swapped)

**Host PC ports vs. instrument's own port are different things — don't conflate them.** The UPL's
*own* rear-panel serial port is always called "COM2" (that's fixed, from its OPTIONS-panel remote
config). But which *PC* COM port that connects to depends on which USB-serial adapter is plugged
into it, and that has changed across this session:
- **UPL → this PC's COM7** (FTDI adapter). Baud **56000**, persisted through a UPL restart.
- **DCX2496 → this PC's COM2** (Prolific adapter).
- History: originally UPL was on the PC's COM2 (Prolific) and flaky; swapped so the more reliable
  FTDI serves the UPL (needs clean bidirectional SCPI) and the flakier Prolific serves the DCX2496
  (one-way fire-and-forget writes tolerate an occasional drop better). If ports get swapped again,
  re-probe both with `upl_capture.py ... probe` before assuming either mapping.
- Also learned: a UPL **power cycle** can trigger the same intermittent Prolific/FTDI "port
  de-enumerates" driver bug seen earlier (unrelated to the UPL itself) — if a port won't open, wait
  a few seconds and retry; it's a Windows driver quirk, not a wiring problem, UNLESS opens succeed
  but nothing replies, which is a real signal (see the DCX2496 RTS-gating bug below for an example
  of "sends fine, silently does nothing" being a real bug, not a driver flake).

## Behringer DCX2496 — serial control (researched + built 2026‑09‑22)

The DCX2496 (user's DUT) has its own RS232 "link" port, separate from the UPL. Behringer never
published this protocol, but it's been reverse-engineered by the DIY community. Full source doc
saved permanently: **`dcx2496_protocol.md`** (fetched from
`github.com/geftactics/UltradrivePi/blob/master/protocol.md`). Control module built and
**verified**: **`dcx2496.py`** — all 3 of the doc's worked examples reproduce byte-for-byte
(`set_gain('inA', 6.0)` → `F0 00 20 32 00 0E 20 01 01 02 01 52 F7`, etc. — confirmed via a fake-
serial unit test, no hardware needed to validate the encoding logic itself).

### Protocol summary
- **38400 baud, 8N1**, RTS used for RS485 bus gating (NOT 115200 — that figure from an initial web
  search was a different, unrelated project; 38400 is the validated value from the worked examples).
- Frame: **MIDI SysEx style** — `F0 00 20 32 <deviceID> 0E <function> <data...> F7` (deviceID
  00–0F for daisy-chained units). Function `3F` = remote-control enable (`04 00`=receive,
  `08 00`=transmit, `0C 00`=both). Function `20` = direct parameter change:
  `[N] × [channel, param, valuehi, valuelo]`, value = `(valuehi<<7)|valuelo` (14-bit, MIDI 7-bit-
  clean split).
- **Channels:** `00`=setup, `01-03`=in A/B/C, `04`=in SUM, `05-0A`=out 1-6.
- **Protocol is write-only as documented** — no confirmed readback command; track state yourself.
- Full parameter table (gain/mute/delay/EQ×9 bands+dynEQ/crossover HP+LP/limiter/polarity/phase/
  setup-channel routing) is in `dcx2496_protocol.md` verbatim; `dcx2496.py` implements a friendly
  Python API (`set_gain`, `set_mute`, `set_delay`, `set_polarity`, `set_phase`, `set_crossover`,
  `set_limiter`, `set_eq_band`, `set_eq_switch`) plus a CLI (`enable`, `gain`, `mute`, `xover`, `raw`).
- **One uncertain detail, flagged in the code:** the source doc's EQ-band parameter numbers
  (`13,14,15,16,17` for band 1 ... `3B,3C,3D,3E,3F` for band 9) step by 4 in the doc's own listing,
  but 5 params are listed per band (freq/Q/gain/filter/slope) — `dcx2496.py` uses a step of 5
  (`EQ_BAND1_BASE=0x13`, `base=0x13+(band-1)*5`) since that's what makes 9 bands fit without
  overlap, but **this specific field has NOT been verified against a live unit** — verify band 2+
  on the front panel before trusting it. Gain/mute/polarity/phase ARE directly doc-verified.

### LIVE-VERIFIED 2026‑09‑23: link works out of the box — no RTS bug after all

First live test appeared to show no effect (`enable` + `gain out1 -6.0` sent cleanly, no visible
front-panel change). Suspected the protocol doc's "RTS gating on RS485" note meant RTS needed to
be explicitly asserted, and patched `dcx2496.py` to set `self.ser.rts = True; self.ser.dtr = True`
after opening. **Retested and it worked. BUT then disproved the RTS theory**: sent the identical
frames a third time with RTS/DTR deliberately left unset (pyserial defaults), and it *still*
worked — because **pyserial on Windows already defaults both RTS and DTR to True on open**
(confirmed live: `s.rts` / `s.dtr` read back `True` immediately after a plain `serial.Serial()`
call, no explicit setting). So the explicit RTS/DTR lines added to `DCX2496.__init__` are a no-op
in practice (harmless to keep, not load-bearing). **The real explanation for the first "no effect"
observation: the user was simply looking at the wrong front-panel page** — not a code or protocol
bug at all. The module, protocol doc, and encoding were correct from the start.

### Verified working sequence
```
python dcx2496.py --port COM<n> enable
python dcx2496.py --port COM<n> gain out1 -6.0     # then LOOK at the DCX2496 front panel (OUTPUT 1)
```
Gain/mute/polarity/phase now considered live-trustworthy (real hardware confirmation, twice).
EQ-band param-numbering (step-of-5 guess, see above) still NOT verified against hardware — test
that specifically before relying on `set_eq_band` for anything beyond band 1.

### FIRST REAL AUTOMATED CROSSOVER MEASUREMENT — success, 2026‑09‑23

Full closed-loop pipeline proven live: DCX2496 (COM2) crossover set via serial → UPL (COM7,
115200 baud) generator-through-DUT frequency sweep → plotted. Physical patch: **UPL generator
output → DCX2496 input A; DCX2496 output 1 → UPL analyzer input** (both XLR balanced). UPL config
for a REAL external sweep (not internal loopback): `OUTP:TYPE BAL; SOUR:FUNC SIN; SOUR:LOWD OFF;
SOUR:VOLT 1.0 V; INP:TYPE BAL; INP:SEL CH2I; SENS:VOLT:RANG:AUTO ON; SENS1:FUNCtion 'RMS';
SENS3:FUNC 'FREQ'` — then per point: `SOUR:FREQ <f> HZ;*wai` → settle ~0.15s → `init:cont
off;*wai` → read `sens:data?` (level) + `sens3:data?` (freq).

**Debugging notes (both real, both fixed live):**
1. First sweep came back suspiciously perfect flat 1.000V at every frequency, 20Hz-20kHz — this
   was because the UPL was **still parked in leftover digital-instrument state** (`INST?`/`INST2?`
   = `D48`, `INP:TYPE?` = `INT`) from the very end of the earlier `upl_selftest.py` run (its
   digital-audio section switches to `INST D48`/`INST2 D48` and never switches back). Several
   config commands were silently rejected as a result (`INP:TYPE BAL` etc.). **Fix: `*RST`** (user
   gave blanket permission to reset the UPL whenever needed for this session) — restored a sane
   analog default (`INST=A25`, `INST2=A22`, `INP:TYPE=BAL`). **Lesson: always check `INST?`/
   `INST2?`/`INP:TYPE?` before trusting a "no error" config sequence** — commands can silently no-op
   or get rejected depending on prior instrument-type state, and a flat/implausible result is the
   tell to check this, not just error codes.
2. Second sweep (after the *RST fix) came back essentially all noise-floor (~26-30µV) with the
   frequency counter locked onto random noise (not tracking the set frequency at all). **Root
   cause: the DCX2496's output 1 was muted** (leftover from earlier in the session, or its prior
   state). **Fix: `dcx.set_mute("out1", False)`** (or `dcx2496.py --port COM2 mute out1 off`).
   Obvious in hindsight but a good general lesson: when a real DUT measurement shows pure noise
   with no signal tracking, check mute/output-enable state on the DUT before suspecting the
   analyzer or the link.

**Results, once both were fixed:**
- With the DCX2496's pre-existing (unrelated, not set by us) lowpass still active on output 1, the
  measured response was a clean **bandpass** peaking ~700-900Hz — low-frequency slope from 106Hz to
  216.5Hz (~1 octave) measured **≈24.6 dB/octave**, matching the commanded `lr24` (Linkwitz-Riley
  24dB/oct) spec almost exactly. High side rolloff was from that pre-existing LP filter, not
  something we configured.
- Disabled the LP (`set_crossover("out1", lp_type="off")`, i.e. raw frame param `0x44`=0) to
  isolate a **pure highpass**: flat passband above ~1.5kHz, clean 24dB/oct rolloff below the 500Hz
  cutoff — textbook LR24 shape.
- Then swept the **HP cutoff itself** across 100/300/1000/3000 Hz (LP still off, still `lr24`):
  four independent measured curves, each one's knee landing exactly at its commanded frequency,
  same slope shape throughout, fully unattended between points. This is the automated "set DCX
  parameter → UPL sweep → log → repeat" loop working end-to-end, exactly as designed.
- **Practical validation of the whole DCX2496 reverse-engineered protocol + `dcx2496.py`**: gain,
  mute, and crossover (HP type+freq, LP type) are now all live-hardware-confirmed, not just
  doc-verified. Only EQ-band numbering remains unverified.
- Scripts used: `scratchpad/dcx_xover_sweep.py` (single sweep) and `scratchpad/dcx_multi_sweep.py`
  (the two-test combined run) — both ephemeral/not in this repo; the reusable logic (upl_configure/
  upl_sweep pattern + DCX2496 class usage) is straightforward to regenerate from this description
  if a permanent version is wanted later.

### EQ-band unknown RESOLVED, 2026‑09‑23 — step-of-5 addressing confirmed, plus a real gotcha found

Built `dcx_sweep.py` (permanent tool; see below) and used it to test EQ band 2 specifically (the
previously-unverified part). **Band 1 boost (1kHz, Q=2, +12dB, bandpass) measured +11.9dB at
985Hz — spot on.** **Band 2 boost (5kHz, same settings) measured ZERO effect** on the first try —
completely flat, band 2's parameters appeared to do nothing despite being sent with no SCPI/DCX
errors. Root cause found and fixed: **param `0x07` ("eq number" in the source doc, semantics
undocumented) gates how many of the 9 bands are actually active** — band 1 works regardless, but
band 2+ are silently ignored unless this count is raised. Setting it to 9 (`dcx.set_param(ch,
0x07, 9)`) before the band-2 write fixed it immediately: **+11.8dB at 4849Hz, matching the
requested +12dB @ 5000Hz.** **`dcx2496.py`'s `set_eq_band()` now automatically sends `eq number=9`
as its first frame on every call**, so this trap can't recur. Step-of-5 per-band addressing
(`0x13,0x18,0x1D,...` for bands 1-9) is now fully confirmed on real hardware, not just arithmetic.
**The DCX2496 protocol/module has no more unverified pieces** — gain, mute, crossover (HP/LP
type+freq), and EQ bands are all live-confirmed.

### UPL native sweep engine — tried, works partially, parked

User asked whether the sweep scripts use the UPL's own hardware sweep (`SOUR:SWE:MODE AUTO;
SOUR:FREQ:MODE SWE2; SOUR:FREQ:STAR/STOP; INIT;*WAI; TRAC? TRAC1`, per `EXAM2.BAS`/`EXAM7.BAS`) or
just step `SOUR:FREQ` manually in a host-side loop. **Answer: manual stepping** (`dcx_sweep.py`'s
`run_sweep()`) — confirmed the native path was never used for the DCX tests.
**Tried switching to native sweep — partial success, parked as a follow-up:**
- Config + trigger all worked cleanly (`SOUR:SWE:MODE AUTO`, `SOUR:FREQ:MODE SWE2`,
  `SOUR:FREQ:STAR/STOP`, `SOUR:SWE:FREQ:POIN 40`, `INIT;*WAI`) — a real 40-point sweep completed
  in **16.7s** (`*OPC?` blocks until done — needs a LONG timeout, 90s+, default 12s is nowhere
  near enough and times out mid-sweep).
- `SOUR:LIST:FREQ?` correctly returned the 40-point log-spaced frequency axis.
- **But `TRAC:POIN? TRAC1` / `TRAC? TRAC1` returned `0` / "No Values"** — the trace itself was
  never populated with the swept level data, even after trying `DISP:TRAC:OPER CURV` (from
  `EXAM7.BAS`). Needs more display/trace configuration than tried so far (possibly `DISP:CONF`,
  a specific `DISP:MODE`, or the trace needs to be explicitly told which function to record) —
  **not resolved, parked**. Manual stepping remains the proven, working default; worth revisiting
  if per-sweep round-trip time becomes a real bottleneck later.
- **Cleanup gotcha:** switching to `SOUR:FREQ:MODE SWE2` changes what plain `SOUR:FREQ <f> HZ`
  commands do — **must explicitly send `SOUR:FREQ:MODE FIX` (and `SOUR:SWE:MODE OFF`) to return
  to normal fixed-frequency generator behavior** before resuming manual-step sweeps, or they'll
  silently misbehave. Done at the end of this investigation; if native sweep is revisited, remember
  this restore step afterward too.

### DCX2496 THD+N characterization, 2026‑09‑23 — "is it as bad as they say?"

Flat passthrough on output 1 (EQ off, crossover off, gain 0dB), B1 low-distortion generator,
`SENS1:FUNCtion 'THDN'`, external balanced path (`INP:TYPE BAL`, `INP:SEL CH2I`). Script:
`scratchpad/dcx_thdn.py` (ephemeral; reuses the `dcx2496`/`upl_capture` classes directly rather
than `dcx_sweep.py`'s `Sweeper`, since it needed a level sweep too, not just frequency).

**vs frequency (1.0V RMS ≈ +2.2dBu):** flat ~−88 to −89dB (0.0035-0.004%) below 1kHz; degrades
above 1kHz to a worst case of **−78.4dB (0.012%) at 6015.8Hz**; improves again above 8kHz (partly
a measurement artifact — higher harmonics of the highest test tones fall outside the 20kHz
audio-band integration window and stop being counted, not necessarily genuine DUT improvement).

**vs level @ 1kHz:** classic converter-system shape — noise-floor-limited at low level (**−63.05dB
at 0.05V/−23.8dBu**), improving to a sweet spot **−87.09dB around 1.0V/+2.2dBu**, then degrading
again toward headroom limits (**−80.16 to −80.53dB by +17 to +19dBu**). Practical takeaway: the
DCX2496's cleanest operating point is around unity/+2dBu, not driven hot or run quiet.

**Context or it's meaningless:** the UPL's own residual floor is −103 to −106dB (see internal
loopback section) — 15-25dB below everything measured here, so the DUT (not the test setup) is
confirmed as the limiting factor throughout.

**CORRECTION/refinement — THD vs THD+N separated, 2026‑09‑23:** user correctly flagged that the
above was all `SENS1:FUNCtion 'THDN'` (distortion+noise combined), and asked to confirm against
the UPL's own much-lower pure-THD figure (−122dB). Re-ran the frequency sweep reading BOTH
`'THDN'` and `'THD'` (harmonics only) at each point. Result reveals two genuinely different
behaviors that the combined THD+N number was hiding:
- **Below ~1kHz: NOISE dominates, not distortion.** THD (harmonics only) is 12-18dB *better* than
  THD+N there (e.g. 66.5Hz: THDN −89.1dB vs THD −103.1dB). True harmonic distortion below 1kHz is
  actually −100 to −107dB — respectable, not far off the UPL's own −122dB reference. The DCX's
  fairly high, roughly frequency-independent NOISE floor is what was making THD+N look mediocre
  down there, not nonlinearity.
- **Above ~2kHz: the two curves converge — real harmonic distortion rises and takes over.** By
  6015.8Hz, THD (−79.78dB) and THD+N (−79.37dB) are nearly identical (only 0.4dB apart) — meaning
  the earlier "worst case ~−78 to −79dB at 6kHz" finding IS genuine harmonic distortion, not noise,
  and is the more meaningful "bad" number for this unit.
- Sentinel gotcha recurred at 14.8kHz/20kHz: THD read the `-240dB` "N/A" sentinel (2nd harmonic
  above analyzer BW) — same pattern as the internal-loopback sweep; excluded from the chart/verdict.

**Revised verdict:** the DCX2496's converter/DSP chain has a **mediocre-but-constant noise floor**
(harmless in isolation, ~−100 to −107dB true distortion below 1kHz) but **genuinely rising harmonic
distortion above ~2kHz**, peaking around −80dB (0.01%) near 6kHz — that upper-midrange/treble
nonlinearity is the more legitimate "it's not great" finding, not the low-frequency number. Overall
still "solid budget PA/live-sound workhorse, not audiophile gear," but now with the *right* reason
identified (real HF distortion, not just a noisy low end).

### Full characterization gauntlet, 2026‑09‑23 — gain, filter-type comparison, limiter

Script: `scratchpad/dcx_gauntlet.py`. Output 1 only (still only 2 cables patched: UPL gen -> DCX
input A, DCX out1 -> UPL analyzer in; crosstalk/other-outputs deferred until more XLR cables).

**A. Gain accuracy** (1kHz, 1.0V in, DCX gain stepped -15 to +15dB): **error is a constant +0.41
to +0.42dB across the ENTIRE range** — excellent linearity, no compression/drift with setting, just
a small fixed calibration offset (likely a 1.0V-vs-DCX's-own-unity-reference mismatch, not a flaw).

**B. Filter-type comparison** (500Hz HP cutoff, LP off, 5 types: but12/but24/bes24/lr24/but48):
every type's measured shape matched its textbook definition — but12 shallowest (2nd order);
but24 and lr24 similar steepness but **but24 visibly peaks near cutoff while lr24 stays smooth**
(correct Butterworth-vs-LR distinction); bes24 (Bessel) has the most gradual knee of the steep
filters, still rising well above 2kHz (correct — Bessel trades sharp cutoff for phase linearity);
but48 has a dramatically narrow transition band (329Hz barely audible, 548Hz nearly full level) —
consistent with 8th-order steepness. **Real independent confirmation the DCX's `FILTER_TYPES`
table (both the names AND `dcx2496.py`'s index mapping) is correct, not just internally consistent.**

**C. Limiter behavior** (1kHz, threshold set to internal -10dB via `set_limiter`, input ramped
0.05V-7V): clean linear tracking (same +0.42dB offset as test A) up to ~3V input, then a **sharp
hard-knee limit** — output pins at ~3.06V regardless of input up to 7V, no overshoot. Textbook
limiter behavior, functioning correctly. (Absolute correspondence between the DCX's internal
"-10dB" threshold scale and our measured ~3V knee wasn't independently calibrated — the SHAPE of
the response is what was verified, not an absolute threshold-to-volts conversion.)

**Overall verdict across the full DCX2496 characterization this session:** the
**control/DSP-parameter side is excellent** — accurate gain law, correctly-shaped filters of every
type tested, a clean well-behaved limiter, precise crossover cutoff points (earlier LR24 slope
test). The **one real, repeatable weakness found is analog-path harmonic distortion rising in the
upper-mid/treble** (~0.01% / -80dB near 6kHz, see THD-vs-THDN section above) — everything else
about this unit's actual signal-processing correctness held up well under real measurement.

Deferred (needs more XLR cables, per user): crosstalk/isolation between outputs, and repeating any
of the above on outputs 2-6 to map the full crossover topology.

### Balanced vs single-ended comparison, 2026‑09‑23

Script: `scratchpad/dcx_balanced_test.py <mode>`. UPL analyzer input is a single XLR jack (per
Vol.2 manual §2.6.2) — there's no separate unbalanced connector; unbalanced operation means only
pin2(hot) is effectively driven, with `INPut[1|2]:LOW FLOat|GROund` controlling whether the outer
conductor ties to chassis ground. Chain tested: **balanced** = DCX2496 out1 XLR → UPL XLR analyzer
input direct. **single-ended** = DCX2496 out1 XLR → XLR-to-RCA adapter → RCA-to-XLR adapter → UPL
XLR analyzer input (same `INP:TYPE BAL` SCPI setting both times — it's the only input-type option;
the difference is entirely in what's driving pins 2/3 upstream of that jack).
(User initially plugged the adapter chain into the wrong UPL input — first single-ended run showed
~7.86µV/-1.1dB THD+N, the same "nothing reaching the analyzer" signature as the earlier muted-DCX
bug; re-plugged correctly and got real data.)

**Results, matched 1kHz/1.0V conditions:**
| Metric | Balanced | Single-ended | Diff |
|---|---|---|---|
| Level | 1.0492V (+0.42dB) | 0.9987V (-0.01dB) | only ~0.43dB |
| THD+N | -86.13dB | -86.08dB | negligible (0.05dB) |
| Noise, INP:LOW FLOat | 39.0µV | 36.8µV | negligible |
| Noise, INP:LOW GROund | 38.6µV | 45.8µV | **+1.9dB worse, real** |
| Freq response shape | flat, gentle HF/LF rolloff | same shape, ~0.4dB lower | level-only offset |

**Interpretation:**
1. **No ~6dB differential-vs-single-ended level gap** — meaning the DCX2496's "balanced" output
   puts full-level signal on the hot leg alone (electronically/impedance-balanced design), not a
   true differential driver splitting the signal across both legs. Going single-ended costs ~0.4dB.
2. **No THD+N penalty** from single-ended + two cheap adapters — a non-event distortion-wise.
3. **The one real, physically-meaningful difference: ground-loop sensitivity.** Balanced is
   completely insensitive to `INP:LOW` (38.6 vs 39.0µV — noise-level scatter). Single-ended is NOT
   — grounding the shield reference adds a real +1.9dB of noise (textbook ground-loop mechanism).
   This is the one place "balanced is better" earns it on this unit — not headroom, not distortion,
   but immunity to shield-reference grounding, which matters far more on long/noisy real-world runs
   than on a short clean bench cable.

Cleanup after this test: DCX out1 left flat/neutral (EQ off, crossover off, gain 0dB, limiter off,
matching prior sessions' end state), UPL generator muted (`sour:volt 0 V`), `INP:LOW` restored to
`FLOat`. Physical cabling left as balanced-direct (adapters removed) at session end.

### Why this matters for the UPL project
Enables **closed-loop automated testing**: drive the DCX2496's crossover/EQ/gain from this same PC
while the UPL measures the result — e.g. step through several `set_crossover(...)` points and run
a UPL frequency-response sweep at each to verify actual filter slopes match claimed order/type.

## Full factory selftest, replicated via remote SCPI, with real values (2026‑09‑22)

Replicated `SELFTEST_Program.TXT` (R&S factory selftest, user-supplied, at
`C:\Users\Sy Ming\Downloads\R&S UPL\SELFTEST_Program.TXT` — untouched, never modified) command-for-
command via remote SCPI from this PC — the front-panel version only shows pass/fail; this captures
every underlying number. **Permanent tool: `upl_selftest.py`** (in this project folder, alongside
`upl_capture.py`/`ser_in.py`/`audio_tests.py` — the original two prototype scripts lived only in the
ephemeral scratchpad and were superseded/discarded).

### Running it
```
python upl_selftest.py --port COM2                     # default baud 56000, auto-named report file
python upl_selftest.py --port COM2 --baud 19200 -o results/run1.txt
```
- Prints every section live to the console AND writes the identical full report to a text file
  (default `upl_selftest_<timestamp>.txt` in the current folder, or pass `-o <path>`).
- Exit code 0 = all readings within tolerance, 1 = at least one out-of-tolerance reading (see the
  `OUT OF TOL` lines in the summary at the end for which).
- Runs `*RST` at the start (same as the real selftest) — clears whatever setup is currently on the
  UPL's screen. Reload your working setup afterward if needed.
- `--settle` (default 0.4s) adds an extra pause after each frequency change before the first
  measurement — added after the first full run flagged a false "out of tolerance" at 15kHz/18mV
  that was actually the `9.93e37` "N/A" sentinel from reading too early; increase this value if
  spurious N/A readings appear in a run.
- Takes a few minutes end-to-end (121 readings, most sections single-point, section 3 alone is 48).

**Remote baud rate — CORRECTED 2026‑09‑23.** Originally thought capped at 56000 per the Vol.2
manual's `SYSTem:COMMunicate:SERial2:FEED:BAUD` table (§2.15.1/§3.10.8.6) — **that table was wrong
or incomplete**. User found **115200 listed directly in the OPTIONS panel** on the real instrument,
switched to it there, and it's **confirmed live**: `probe` at 115200 baud on COM7 replied cleanly
(`ROHDE & SCHWARZ, UPL, 3.06, 0.33`). So 115200 works for the general SCPI link too, not just
`SNDFILE.BAS`'s dedicated dump channel. **New recommended default baud: 115200** (fastest verified;
set via the OPTIONS panel — the remote SCPI baud-set command may also accept it despite the
manual's printed table, untested remotely, but the front-panel route is confirmed working).

**B21 identified (from user-supplied brochure, `R&S_UPL_Audio_Analyzer__Data_and_Spec_Sheets.pdf`,
one dir up):** **UPL‑B21 = Digital Audio Protocol** — in-depth AES3/S-PDIF protocol analysis and
*generation*, extending options B2/B29. Confirmed from clear prose (not the brochure's ordering
table, whose columns are scrambled/row-shifted by PDF extraction — labels and part numbers don't
line up; don't trust that table for anything not already cross-confirmed elsewhere). This is
exactly what the `PROTB/PROTC/PROTP_DD.SAC` setups from the 1GA36 library (see Application Notes
catalog below) are for — user has both the B21 software and those ready-made setups.
Also reconfirmed from the brochure's prose: **UPL‑B22 = Jitter and Interface Test** (matches prior
finding). Updated full option list: **B1, B2, B4, B5, B6, B10, B21, B22, B23, B29** (B23 not
mentioned in this particular brochure printing, but independently confirmed earlier from the
firmware's own help text).

**Result: 121/121 readings within R&S factory tolerance** (full resolution — all 3 frequencies ×
16 analyzer-range points = 48, plus generator range, low-dist gen accuracy, THD+N/DFD/noise
inherent-performance checks, and digital audio). Unit: **serial number 100330/6**, firmware 3.06,
`*OPT?` = `B1(0.01),B29(2.16),B21,B22,B4,B5(1.62),B6,B10,B22,B23` (note: **B21** also appears in
`*OPT?` and wasn't previously cataloged — not yet identified, check the manual/front panel).

| Test | Result | Spec | Margin |
|---|---|---|---|
| Generator accuracy, 30mV–20V | −0.12% to −0.35% | ±1.6–2% | comfortable |
| B1 low-dist gen, level/freq, 150Hz–25kHz | ≤0.21% / ≤0.03% | 1.6–2.7% / 0.8% | wide |
| Analyzer ranges, 18mV–18V × {1k,40,15k}Hz + 30/60/100V ext (48 pts) | −0.06% to −0.42% | ±1.5–3.0% | wide |
| Inherent THD+N @1kHz/2V, A22 | −103.0 to −103.6 dB | ≤−93 dB | ~10 dB |
| THD+N −60dB linearity (2-tone) | −60.14/−60.17 dB | ±0.5 dB | good |
| Inherent THD+N @1kHz/2V, A100 | −97.7 to −97.9 dB | ≤−84 dB | ~14 dB |
| Inherent D2 (DFD) @10kHz/200Hz/2V | −120.5 to −131.3 dB | ≤−110 dB | wide |
| Inherent noise, A22 | 1.5–1.6 µV | ≤2 µV | tight-ish but PASS |
| Inherent noise, A100 | 4.3–5.2 µV | ≤8 µV | comfortable |
| Digital audio (B29) level/freq | −0.002% / exact | 0.1% / 0.01% | excellent |

**Conclusion: healthy, well-calibrated instrument across every domain tested** — analog gen/analyzer
accuracy, B1 low-distortion performance, THD+N/DFD/noise floors (both A22 and A100), and digital I/O.
One apparent fail (15kHz/18mV analyzer range returned the `9.93e37` "N/A" sentinel) was a script
settling-time artifact, not a real fault — re-verified clean (0.017998V vs 0.018V, −0.02%) with a
longer settle after the frequency change.

**New SCPI/technique notes from this run:**
- `INST2 A100` vs `A22` inherent-noise comparison now directly measured: **A100 noise ≈3× higher**
  than A22 (4.3–5.2 µV vs 1.5–1.6 µV) — consistent with its wider bandwidth, as expected.
- Reconfirms: after switching `INST`/`INST2`, must re-issue `INP:SEL`, `INP:TYPE`, `SENS:VOLT:RANG`,
  and the function selects — nothing survives the switch (matches the earlier finding).
- The 30V/60V/100V "extended range" checks in the analyzer-range section do NOT change the
  generator voltage — they re-measure the SAME last-set level (18V) on progressively wider analyzer
  ranges, checking range-switching accuracy rather than each range's full-scale capability.
- `9.93000001414e+37` (with variants) is the general "value not available" sentinel across SENS
  reads — always check for it before trusting a numeric parse, not just on the specific queries
  noted earlier.

## Application Notes catalog (digested 2026‑09‑22)

Folder: `Application Notes/` (one dir up from this project, alongside the manuals). 14 PDFs +
bundled DOS example programs. Most PDFs are usage/install docs for their bundled compiled `.exe`
programs (source not printed in the PDF), so SCPI yield from text-grepping them was modest —
cataloged here by topic so they're easy to pull up again if a specific need matches:

- **1GA42_0E** — UPL→PC file transfer via RS232. **Fully digested above** (SNDFILE/SER_IN/ser_in.py).
- **1GA36_1L** — Collection of ready-made `.SAC` setup files, incl. **jitter** (`JITAM/JITSP/JITSU/
  JITWA_DD.SAC`) and **protocol** (`PROTB/PROTC/PROTP_DD.SAC`) setups — directly relevant to B22/B23,
  not yet loaded/tried live. Path: `Application Notes/1GA36_1L_Collection_Of_Setups.../
  Rohde&Schwarz_Library/`.
- **1GA15_1L** — Protocol Analysis at Digital Interfaces (AES3/S-PDIF). Background/theory on the
  AES3 subframe format (channel status bit, user bit, validity/parity) — pairs with the PROT*_DD.SAC
  setups and B23. No new SCPI extracted.
- **1GA12_1L** — External sweep / adaptive measurement using the UPL's **Settling function**, for
  DUTs with extreme transients (e.g. AGC circuits, compressors). Relevant if DCX2496 dynamics
  processing needs settling-aware sweeps.
- **1GA32_1L** — Measurement of transient responses in AGC circuits — companion to 1GA12, directly
  relevant to testing the **DCX2496's dynamics/limiter** behavior.
- **1GA33_1L** — Limit checking (front-panel driven: LIM UPPER/LOWER/LOW&UP, fixed VALUE or FILE
  tolerance curve, absolute or relative units). No new SCPI found; feature is mostly UI-driven but
  pairs naturally with **B10 automatic sequence control** for pass/fail production-style testing.
- **1GA30_0E** — Measurements on A/D converters — directly relevant to the **SPDIF DAC** test plan
  (methodology mirrors what we'd do for the DAC's ADC-adjacent specs).
- **1GA21_1E**, **1GA24_1E (tuner)**, **1ga16_1l/1GA24 (loudspeaker)**, **1GA34_1L (hearing aids)**,
  **1ga39_0e (GSM phones)**, **1GA43_0E (FM tuners)**, **1ga31_1l (clicks on audio lines)** — each a
  turnkey DOS BASIC application + PDF for a specific DUT class; not directly relevant to the current
  DUT list (DCX/SPDIF DAC/turntable) but the **loudspeaker** and **clicks** ones could be reused if
  testing a speaker driver or hunting glitches later.
- **7BM44_0E** — Audio-to-video delay measurement (broadcast use case, needs an SFF/SAF video
  generator + oscilloscope). One reusable hard fact: **the UPL's analog output has a ~690 µs delay
  relative to its digital output** (same function/settings) — worth knowing for any digital-vs-analog
  latency comparison (e.g. DCX digital-in→analog-out timing). Confirms `UPL OUT "INIT:CONT OFF"`
  usage and that BASIC can bit-bang the parallel port directly (`OUT 632,1` — port 0x278/LPT1).
- **RCS0702-0032** — Amplifier test methodology per **IEC 60268‑3** (note: for the **UPV**, a later
  R&S analyzer, but the test-item checklist transfers directly). Useful as a **structured test plan**
  when characterizing an amp/DCX output stage: min source e.m.f., output voltage/power (distortion-
  limited), overload e.m.f., gain (incl. volume-control attenuation law), gain-frequency & phase-
  frequency response, THD vs freq/level, nth-order harmonic/modulation/DFD/DIM distortion, noise,
  crosstalk/separation. Good checklist to structure a future DCX or amp test session around.
- Minor confirmed syntax notes: `MMEM:CDIR '<path>'` (or unquoted) changes the UPL's working
  directory for an app's data files; **`UPL OUT` and `UPD OUT` are documented as synonymous**
  (UPD is the UPL's sibling instrument; example BASIC often uses `UPD OUT` even when targeting UPL).

## Manuals (added 2026‑09‑22)

User placed the official operating manuals **one directory up** from this project folder:
`C:\Users\Sy Ming\Downloads\R&S UPL\R&S_UPL_Audio_Analyzer_Op_Vol_1.pdf` and `..._Vol_2.pdf`.
**Vol 2 = the IEC‑bus/remote SCPI command reference** — use it to verify command syntax instead
of blind live probing. Working directory was moved up to `C:\Users\Sy Ming\Downloads\R&S UPL`
(via change_directory) so both the manuals and `UPL_3.06/` (tools, CLAUDE.md) are reachable.

## Internal loopback self-test results (2026‑09‑22, all via upl_capture.py's UPL class over COM2)

Confirmed the UPL loops to itself: `INP:TYPE GEN2` routes analyzer input ← internal generator.
- Basic check: `*RST; INP:TYPE GEN2; SOUR:FREQ 1000 HZ; SOUR:VOLT 1.0 V; INIT;*WAI` →
  0.999 V / 1000.08 Hz / peak 1.413 V — all correct.
- `*OPT?` confirmed all options installed (see above).
- **B1 Low-Dist generator THD (harmonics only) = −122.1 dB**; THD+N (noise-inclusive, full BW)
  only −106 to −107 dB — noise-floor-limited, not generator-limited (see bandwidth-limit note above
  for the still-open follow-up to tighten this).
- **Swept THD/THD+N vs frequency, 20 Hz–20 kHz, 24 log-spaced points**, B1 ON, 1 V, internal
  loopback. Script: `scratchpad/upl_thd_sweep.py` (pattern: for each freq, set `SOUR:FREQ`, small
  settle, `SENS1:FUNCtion 'THDN'`→trigger→read `SENS:DATA?`+`SENS3:DATA?`, then `'THD'`→same).
  CSV written to scratchpad (not in this repo — regenerate by rerunning the pattern above).
  Result: THD+N flat ~−105 to −106.5 dB across the band; THD (harmonics only) −114 to −125 dB,
  i.e. ~15 dB better — confirms B1 is genuinely low-distortion once noise is excluded.
  **Gotcha:** at 14.8 kHz and 20 kHz, THD read back as a sentinel `-240 dB` (2nd harmonic falls
  above the analyzer's measurement bandwidth → not measurable) — treat `-240` (or similarly
  implausible clamp values) as "N/A", not a real number, when parsing UPL results generally.
  Plotted as a Chart.js line chart (title `upl_b1_thd_sweep`) — THD+N vs THD, log-x frequency axis.
- **SCPI gotcha confirmed:** numeric query replies carry a trailing unit string, e.g.
  `-106.44 DB`, `1000.08 HZ` — strip everything after the first whitespace before `float()`.
- Instrument was left in this loopback config (Low Dist ON, 1 kHz/1V, THDN function, INP:TYPE
  GEN2) at the end of this session — restore the user's real setup before/instead of a DUT
  measurement next time (`*RST` was run earlier in the session, wiping the prior on-screen config).

## Current plan / next steps (where we left off, 2026‑09‑22)

Chosen setup: **laptop = signal generator, UPL = analyzer.**
- Patch **laptop headphone jack (output device index 3, "Speakers (Realtek Audio)")** → **UPL
  analyzer input**. Fix Windows volume, disable audio enhancements, generate ~−6 dBFS.
- Connect **USB‑serial → UPL COM2** (remote mode on); tell Claude the **COM port**.
- Then Claude can: verify `probe`, run a coordinated **frequency sweep** (play tone on laptop →
  read level+THD+N from UPL at each step → plot), and **probe the remote trace‑store command**
  live (non‑destructive: create `ZTEST*.EXP`, check `SYST:ERR?`/`MMEM:CAT?`, then `getfile`).
- Optional: pre‑stage a combined "generate‑on‑laptop + read‑UPL" sweep driver.

### Guardrails for live instrument work
Show every SCPI sent + its reply. No `*RST`, no deleting/overwriting the user's files or setup, no
touching calibration, without asking. A sweep trigger (`INIT`) changes measurement state — confirm first.
Don't play tones out the speakers unannounced.
