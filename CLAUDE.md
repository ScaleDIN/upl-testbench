# R&S UPL — analysis, modernization, and data‑egress project

Working notes for the Rohde & Schwarz UPL audio analyzer. Captures what we found in the
v3.06 firmware install media and the plan/tools for (a) keeping the instrument alive long‑term
and (b) getting measurement data off it easily. Last updated 2026‑09‑24.

**For "how do I actually run the tools/tests," see `README.md` (general) and
`SELFTEST_README.md` (standalone, for `upl_selftest.py`) — both added 2026‑09‑23. This file
(`CLAUDE.md`) is the working log/narrative: what was tried, what broke, what was found, and why
things are built the way they are. The READMEs are the quick-start; this is the deep reference.

**Correction, 2026‑09‑23:** several scripts described below as "ephemeral"/"not in this repo"
(in the AppData temp scratchpad) have since been cleaned up and promoted into this project's own
permanent folder (with `argparse` CLIs replacing their original hardcoded
COM2/COM7/temp-path values) — `dcx_thdn.py`, `dcx_thd_vs_thdn.py`, `dcx_gauntlet.py`,
`dcx_balanced_test.py`. They're real, runnable, documented in `README.md` now. That folder was
first called `scratchpad/`; on 2026‑09‑24 it was split into **`measurements/`** (DUT
characterization scripts) and **`tools/`** (`upl_backup.py`, `sndfile_batch.py`,
`lzh_extract.py`), because the old name made them look temporary. Also discovered/
catalogued in this pass: a substantial **NAD M51 DAC** control module + test suite
(`nad_m51.py` + `measurements/m51_*.py`) that was built earlier in the project but not previously
described in this log in detail — see `README.md` for what each one does and how to run it.

## Results folders and reports (2026‑09‑24)

Every measurement script now writes **one folder per run**, `results/<test>/<label>_<YYYYMMDD-HHMMSS>/`,
holding `report.html` (run details, tables, matplotlib graphs embedded as PNG, one self-contained
file), the raw CSV/JSON unchanged, `plots/*.png`, `summary.txt` (the console output, tee'd) and
`run.json`. `results/index.html` lists every run with a one-line headline. All of it is
`report.py` (`Run` context manager + `add_output_args`); `--label`/`--outdir` are the same on every
script, `-o FILE` (where it exists) now means "just the CSV, no folder" (`-o -` = stdout), and
`--dry-run` runs get a `dryrun_` label. Anchored to the project folder, so the working directory no
longer matters; previously most scripts dropped fixed-name files into the current folder and
overwrote them on the next run. Scripts converted: `dac_test.py` (per-test graphs), the four
`dcx_*` measurement scripts, `dcx_sweep.py`, `filter_test.py`, `upacd_test.py`, `upl_selftest.py`,
`upl_capture.py` (`sweep nsweep fft autoexport diagdump`), `audio_tests.py response`.
`dcx_balanced_test.py` gained `--compare <earlier run>` for the two-wiring comparison it was
built for. A run that raises still writes its folder, marked partial. Verified offline only:
dry runs of everything that has `--dry-run`, and fake-data runs of the rest; `seqcheck` still passes.

**Old loose results were re-filed the same way** (moved byte-identical, MD5-checked; folder stamp =
the file's own mtime) and given reports: the 2026‑09‑22 M51 runs under `results/m51_fr/`,
`m51_gain_sweep/`, `m51_clip_onset/`, `m51_freq_stability/`, `m51_jitter_fft/`; the 2026‑09‑24
filter test under `results/filter_test/loopback_20260924-004233/`; the diagdump under
`results/diagdump/full_20260923-225942/`. The instrument backups `results/CAL`, `DISK`, `REF`
were left where they are.

**Bug found in `upl_selftest.py` while doing this:** `rec()` never checked limit-type readings
(set value `None`: inherent THD+N, DFD, noise) against their limit. Only an n/a reading could
fail, so the "N/M within tolerance" summary could count an over-limit reading as a pass. The
per-section console line did its own PASS/FAIL comparison, so the 2026‑09‑22 run's printed
results were right, and those readings were all well inside their limits anyway. Fixed:
`ok = meas <= limit`.

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
- **Board history, from Service Manual Vol.2 (2026‑09‑23, shared Drive archive).** The parts list
  of the UPL mainframe (1078.2008) shows the *earlier* generations:
  **MOD 02 (monochrome LCD) — 386DX40 mainboard, Shuttle 327**; **MOD 05 (colour LCD) — 486 AT
  board, ABIT AH4T**. Models 06/66 are the Pentium (586) units (Vol.1's 16‑bit-WAV note). This
  finally explains all three branches of `AUTOEXEC.UPL`'s CPU mapping — `SX386` is for the MOD 02
  386 boards, `UM486` for MOD 05, `UM586` for 06/66 — which the firmware analysis alone couldn't.
  Same list: **Hitachi DK222A‑54, 2.5″ 540 MB IDE hard disk**, **Sony MPF520 3.5″ floppy**.
  **This unit — CONFIRMED from a photo of the board (2026‑09‑23):** a **Kontron** module carrying
  a **National Geode GX1‑300B‑85‑2.0** (300 MHz, on-chip x87 FPU) — the "Kontron Geode GX1 module"
  original fit listed above. Firmware takes the `UM586` branch. Not one of the 386/486 early units.
  (The user had first said "a MediaGX at 300 MHz, I think" — right family: MediaGX became the GX1.)

  | Part | Marking | Role |
  |---|---|---|
  | CPU | Geode GX1‑300B‑85‑2.0, ©2000 NSC, V2S0A404AB A3 | 300 MHz x86 with integrated FPU and graphics core |
  | Companion | Geode CS5530A‑UCE | video output, IDE, audio, PCI→ISA bridge |
  | Super I/O | Winbond W83977F‑A | FDC, serial/parallel, keyboard controller |
  | BIOS flash | ST M29F040B (512 KB) | BIOS |
  | Label | **Kontron 18003‑1280‑30‑1RS1**, S/N **YO4680032** | module part number |
  | Sockets | SO‑DIMM (RAM); **CompactFlash** — empty in the photo | |
  | Date codes | ST flash "0433", IDT logic "K0435M" | module built ~2004 |

  **Form factor: ETX — CONFIRMED from a second photo (underside + carrier, 2026‑09‑23).** Two
  independent pieces of evidence: the module's underside has the standard ETX layout of **four
  board-to-board connectors**, two at each end; and the carrier board is silkscreened
  **`2094.0954.00 ETX-MODULE`** — an R&S-format part number, so R&S designed the carrier.
  Mating connectors **X30 and X40** are visible on the carrier (the other two are out of frame).
  In the ETX standard the four connectors split roughly as: X1 PCI/USB/audio, **X2 ISA**,
  X3 VGA/LCD/serial/parallel/floppy/keyboard, X4 IDE/Ethernet/power control. The dedicated ISA
  connector is why ETX suits the UPL, and why ISA-capable later ETX modules exist.

  Also seen in the second photo:
  - **CMOS/RTC battery: a Renata CR2477N lithium coin cell, on the carrier** (bottom left, in a
    holder). This is the battery whose failure would reset the BIOS setup — see point 3 below.
    It looks replaceable, but record the BIOS screens *before* touching it, and measure it; a
    long-life cell, but ~20 years old.
  - **Module underside:** Davicom **DM9102AE** 10/100 Ethernet controller (date 0417), a
    **Xilinx** CPLD (most likely the ISA-bus glue logic), board ID "MODUL122".
  - The carrier does bring the Ethernet out to an RJ45 (X106), but **it's internal only** — no
    rear-panel access — so in normal use it's not a data-egress route. See "The R&S carrier board"
    below for the one-off, lid-off exception.

  **The R&S carrier board (2094.0954.00), from a full photo:**

  | Ref | What | Notes |
  |---|---|---|
  | left edge | **full ISA card-edge connector** | the carrier *is* an ISA card in the UPL backplane |
  | X10, X20, X30, X40 | the four ETX mating sockets | |
  | X3 | round DIN socket | most likely the keyboard |
  | **X106** | **RJ45 jack** (integrated magnetics) | Ethernet from the module's DM9102AE — see below |
  | X120 | 34-pin header silkscreened FLOPPY | fed from the module's Super I/O, but **not what the UPL uses** — the drive runs off the digital board's FDC37C665 (below) |
  | X130 | small white header near X120 | power-style header, possibly floppy power; label not legible |
  | — | Renata CR2477N 3 V lithium, in a holder | CMOS/RTC battery |
  | S1 | small blue switch next to the battery | **function unknown — could be reset or CMOS-clear; don't operate before the BIOS photos** |
  | label | R&S barcode sticker on the ISA edge | number looks like `1031.0409.02`, not reliably legible — read it off directly |

  **The architecture notes stand: video, IDE and floppy are all on the mainframe side.** (A
  same-day commit claimed otherwise from the "FLOPPY" silkscreen on X120; that was a misreading,
  corrected by the user.) The floppy controller is an **SMC FDC37C665 on the Digital Board
  1078.2708** — Service Manual Vol.2 parts list, same list as the TMS320C31 DSPs, the TNT4882C
  IEEE‑488 controller and the MAX239 RS‑232 transceiver — and the user confirms it from the board
  and the schematics. The carrier's reverse side is blank; it holds no controller. X120 is a header
  the module *could* drive, left unused. The carrier also has no IDE or VGA header, consistent
  with the mainframe's own IDE and Cirrus VGA cards. So in BIOS terms: the module's own **FDC,
  IDE and video should all be disabled** (the FDC37C665 sits at the standard 3F0 floppy
  address, so an enabled module FDC would collide with it).

  **Boot disk (answers longevity point 4, provisionally):** the module's CF socket is empty and
  the carrier has no IDE header, so the unit almost certainly boots from the mainframe's IDE disk.
  Confirm from the BIOS boot-device settings when photographing them.

  **Ethernet: X106 is internal only** (user, 2026‑09‑23) — it faces into the chassis, with no
  rear-panel access. So it is **not** a data path in normal use. The one conceivable use is a
  one-off with the lid off: exit to DOS (SYSTEM / Ctrl‑F9), load a DOS packet driver for the
  DM9102AE, and pull a full disk backup over FTP (e.g. mTCP) far faster than SNDFILE at
  115 kbaud. Entirely unverified (link, driver availability, fitting alongside HIMEM/EMM386), and
  anything installed on the UPL disk goes on *after* the disk image is taken. Low priority —
  removing the disk and imaging it directly is simpler.

  **What this changes for the longevity plan:**
  1. **Exact spare to hunt for:** Kontron **18003‑1280‑30‑1RS1**. A same-part NOS or pulled module
     is the zero-engineering option (plan step 2), better than "a Geode GX1 module" in general.
  2. **ETX is confirmed, so a different ISA-capable ETX module on the *existing R&S carrier*
     (2094.0954.00) is now the preferred fallback over the Vortex86 ISA SBC** — the carrier and all
     its UPL-side wiring stay untouched. Per candidate module, still to verify: that it implements
     the X2 ISA bus, boots DOS, and meets the UPL's ISA timing; that its onboard video, IDE **and
     floppy controller** can all be disabled to coexist with the mainframe's (the floppy is on the
     digital board's FDC37C665 at 3F0); and the keyboard (X3 DIN).
  3. **The BIOS setup is state worth recording.** The module has its *own* video, IDE and floppy
     controllers (CS5530A, W83977F), while this file's architecture notes put the UPL's video, IDE
     and FDC on the mainframe. If those onboard devices are disabled in CMOS setup, a flat CMOS
     battery or a setup reset could re-enable them and collide with the mainframe's. **Photograph
     every BIOS setup screen** alongside the disk image in plan step 1. (Whether they're disabled
     in CMOS or by hardware strapping isn't known yet.) The battery in question is now identified:
     the Renata CR2477N on the carrier.
  4. **The CompactFlash socket:** empty in this photo. Check whether the UPL boots from a CF card
     here or from the mainframe's IDE disk — it decides what "image the boot disk" means. The
     shared Drive archive has a "CompactFlash Card" photo folder suggesting another owner moved to
     CF; the on-module socket would make that straightforward.
- **R&S's own statement on repairability** (Service Manual Vol.2 contents page): *"All modules not
  listed above are no R&S developments but parts from subsuppliers… repair down to component level
  is not possible. In the case of complaint, the complete module has to be replaced."* The CPU
  board, hard disk, floppy and LCD are all in that category. This supports the plan below: treat
  the CPU board as a swappable commodity part, and treat the *disk contents* as the thing to protect.
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
  Cirrus VGA (A000/B800, 3C0–3DF), IDE (1F0/170) and FDC (3F0 — the SMC FDC37C665 on the
  Digital Board 1078.2708, confirmed from the service manual). This is the only real constraint.
  (Briefly edited on 2026‑09‑23 to say the floppy came from the CPU board; that was a misreading
  of the carrier's unused X120 header, and has been reverted.)
- Must tolerate/ignore **−15V on B7** (the UPL busses −15V onto the standard −12V pin).
- Best candidate: an **ICOP/DMP Vortex86 ISA SBC** (native DOS, real ISA, VGA/IO disable‑able).
  Zero‑risk alt: NOS **AI5VG+** or sibling Socket‑7 half‑size card.
- **FPU: not required, but choose a board that has one** (checked 2026‑09‑23). `UPL_UI.EXE` is
  built with Borland's FPU *emulator*. The binary holds **~25,760 `INT 34h–3Dh` emulator hooks**
  (background for unused vectors: 0–1) and only 138 raw `FWAIT`+ESC pairs. The runtime patches
  those hooks into real x87 instructions when an FPU is present and emulates them in software when
  not — which is how the MOD 02 386DX40 units ran the same code. Our MediaGX has an on-chip FPU.
  So a **Vortex86SX (no FPU) would run the firmware but emulate floating point**, and with ~25k FP
  sites in the control/UI code that's a real slowdown. It would affect speed, not results: the
  heavy DSP maths is on the TMS320C3x cards either way. **Prefer a Vortex86 variant with an FPU
  (DX, MX)** so the swap behaves like the current board.
- **Clock: ~300 MHz is proven safe on this unit.** The "moderate clock, beware DOS delay loops"
  concern above now has a data point: at least up to the MediaGX's ~300 MHz there's no problem.
  Much faster boards remain untested.

### Custom silicon and stored state — what dies how (Service Manual Vol.2, 2026‑09‑23)

Question asked: if an ASIC dies, is there proprietary firmware inside? Answer from the Service
Manual Vol.2 parts lists (text layer of scanned pages, so OCR-noisy — see caveats), plus the
firmware binary:

| Part | Board | Kind | Holds code/data? | If it dies |
|---|---|---|---|---|
| **SERPA, `8002-7106`** (made by **VLSI**, chip marked `VY17136-2`, R&S stock 1030.8570.00) | Digital 1078.2708 | custom **gate array** | **No** — logic fixed in the metal at manufacture | Irreplaceable except from a donor. **Exactly 4 instances, all the same part** (schematic read 2026-09-23): D1 = ISA host interface at I/O 390h, D39 = `GEN_SERPA`, D41 = `ANA_SERPA`, D40 = `DSP-B SERPA`. It *is* a serial↔parallel bridge (ISA or TMS320C3x bus ↔ C3x-format serial ports). Full pin/register model: **`SERPA_PERIF.md`**. |
| **PERIF2, `L5A8612`** (LSI Logic, R&S 0009.0432) | Digital 1078.2708 | custom **ASIC**, "KEYBOARD INTERF." | **No** | Donor only. Key matrix, rotary encoder, LCD-contrast pot, IRQ via SERPA; I/O 4390h. Pinout + register model in **`SERPA_PERIF.md`**. Its sheet is missing from the Vol.2 scan but present as "KEYBOARD DECODER" (ref D24) in Drive *Schaltplan_ocr.pdf*. |
| **Battery-backed setup RAM** (2× TC55257, battery G2 3.4 V) | Digital 1078.2708 | standard SRAM | **Yes — per-unit setup state** | Contents lost if G2 dies; reached only via SERPA port 0x3392 (auto-increment counter). See `SERPA_PERIF.md` §2.6. |
| **Xicor `X24164`**, 2K × 8 serial EEPROM | Digital 1078.2708 | standard part | **Yes — the only chip on the R&S boards with unique per-unit data** | The chip is trivially replaceable; its *contents* are not. See below. |
| TMS320C31 DSP × 2 | Digital | standard TI | No on-board code: `A.OUT`/`B.OUT` are loaded from disk at boot (see architecture notes) | Obsolete but standard. |
| Cirrus `GD6205` LCD/VGA, NI `TNT4882C` GPIB, SMC `FDC37C665` FDC, `MAX239` RS-232 | Digital | standard | No | Obsolete standard parts; used/NOS. |

**No EPROM, PROM, flash, PAL or GAL appears in any R&S board's parts list.** Every piece of
firmware — `UPL_UI.EXE`, the DSP images — lives on the hard disk, so the disk image covers it.
The custom chips carry no firmware at all: there is nothing inside them to back up or reverse
engineer, and nothing that would stop a donor chip working. Their risk is purely *supply*.

**Practical consequence: a donor Digital Board 1078.2708 is the single most valuable spare.**
It covers every SERPA position, PERIF2, and all the obsolete standard parts in one go. **But** the
donor's X24164 holds the *donor's* identity/calibration, so a board swap means carrying this unit's
EEPROM contents across — which is why backing those contents up now matters.

**Resolved 2026-09-23** (schematic page images + chip photo): the part number is `8002-7106`
on every sheet, and there are four instances (D1, D39, D40, D41). The earlier "D1–D5" and
"-713/-716" readings were OCR noise. The X24164 is the only store of *calibration*, but the
battery-backed setup RAM (above) also holds per-unit state.

#### Reading the EEPROM over RS-232 — a strong lead, unverified

R&S's own selftest reads the serial number with the undocumented `DIAG:DEV` command:
```
DIAG:DEV SERN ; DIAG:DEV:ADDR 0 ; DIAG:DEV:DATA? ; DIAG:DEV:ADDR 1 ; DIAG:DEV:DATA?
```
`DIAG:DEV` is not in the Vol.2 manual (only a password-protected DIAGNOSTIC menu is mentioned).
In `UPL_UI.EXE`'s command-keyword table, `SERNumber` sits in a run of what look like the other
selectable devices:
```
DSPA  DSPB  RX1  RX2  TX1  TX2  SERNumber  INSTkey  CLDG  CAGEn  CANLr0  CDPHase
RTEMperature  REG  PIN  ENPin  CALDcout
```
Reading: `CAGEn` / `CANLr0` / `CLDG` / `CDPHase` = calibration tables (generator, analyzer,
low-distortion generator, phase); `INSTkey` = this unit's own installed option key;
`RTEMperature` = a temperature sensor; `DSPA/DSPB`, `RX/TX` = DSP and serial-link access. **If
right, the same read sequence with those selectors would back up the per-unit state over RS-232,
without opening the case.** Inferred from the table's layout, not confirmed — only `SERN` has
been seen in use.

Rules if this gets tried:
- **Read only.** Only ever `DIAG:DEV:DATA?` (with the `?`). Never send `DIAG:DEV:DATA <value>`:
  a write path almost certainly exists and could corrupt calibration.
- **Skip `REG`, `PIN`, `ENPin`, `CALDcout`, `DSPA/B`, `RX/TX`** — they sound like live hardware
  pokes; selecting them may have side effects.
- Start with `SERN` (proven), then `CAGEn`, `CANLr0`, `CLDG`, `CDPHase`, `INSTkey`. Check
  `SYST:ERR?` after every step; walk `ADDR` upward until it errors to find each table's size.
- Compare against `SETUP/CAL_*.SET` on the disk: calibration may be held in both places, in which
  case the disk image already covers it and the EEPROM dump is belt and braces.

**Implemented as `upl_capture.py diagdump` (2026‑09‑23, not yet run against hardware).** The
rules above are enforced in code, not left to the operator:
- Every `DIAG:DEV:DATA` goes through `_diag_query()`, which raises on anything not ending in `?`
  — a write can't be sent even by mistake.
- Selectors are an allow-list (`SERN CAGEn CANLr0 CLDG CDPHase INSTkey RTEMperature`); the risky
  ones (`REG PIN ENPin CALDcout DSPA DSPB RX1 RX2 TX1 TX2`) are refused **before any command is
  sent**, even when mixed with allowed ones.
- `SYST:ERR?` after every select, every `ADDR`, and every read. A table ends at the first error,
  at a read timeout (the port is then drained so a late reply can't shift later values), or at
  `--max-addr` (default 2048, the X24164's size).
- A selector the instrument rejects is recorded as rejected and skipped; the others still run.
- Values are stored **raw** — their format is unknown, so nothing is parsed. Output is
  `<name>.csv` (device, addr, raw_value, with `*IDN?` in the header) plus `<name>.json`
  (per-table word count and why it stopped).

`seqcheck` now asserts all of the above against a stub that simulates table ends, a rejected
selector and a mid-table timeout.

**First live run — go in this order:**
```
python upl_capture.py --port COM7 --label sern diagdump --devices SERN
```
The serial is known (**100330/6**), so this one run checks that the walk works, what `SYST:ERR?`
says at the end of a table, and what the raw values look like — all against a known answer.
Only then run the default list:
```
python upl_capture.py --port COM7 --label full diagdump
```

### Longevity action plan (priority order)
1. **Image the mainframe boot disk (raw) and archive the calibration data NOW** — the only
   irreplaceable state. (Board is replaceable; its stored state is not.) **Also photograph every
   BIOS setup screen** — see the board notes above for why. First find out whether the unit boots
   from the mainframe IDE disk or from the module's CompactFlash socket.
2. **Buy a NOS spare** — now specifically **Kontron 18003‑1280‑30‑1RS1** (this unit's exact
   module), or a donor UPL — zero‑engineering insurance.
3. **Qualify a fallback.** The module is confirmed ETX, so first try another ISA-capable ETX module
   on the existing R&S carrier (2094.0954.00). Keep one Vortex86 ISA SBC with an FPU (DX/MX),
   VGA/IDE/FDC disabled, as the second option if no suitable ETX module turns up.
4. **Measure the CMOS battery** (Renata CR2477N on the carrier) — after step 1's BIOS photos, not
   before.
5. **Try a read-only `DIAG:DEV` dump of the per-unit state** (serial, option key, calibration
   tables) over RS-232 — see "Reading the EEPROM over RS-232" above for the rules. If it works,
   it's the no-screwdriver backup of the one chip whose contents can't be replaced.
   **Done / superseded 2026‑09‑24:** `DIAG:DEV` gave serial + option key only (calibration
   selectors refused), but the calibration turned out to live in **disk files**, and every file on
   the disk was pulled over GPIB (`MMEM:DATA?`) — see "GPIB (Agilent/Keysight 82357B)". Step 1's
   *file-level* half is therefore done too; the raw image (boot sector, partition table) and the
   BIOS photos are still outstanding. Whether the X24164 EEPROM holds anything *not* in those
   files is still unknown.
6. **Keep an eye out for a donor Digital Board 1078.2708** — it covers every custom chip (the
   SERPA gate arrays and PERIF2) in one part.

## Installed options (confirmed by user, 2026‑09‑22) — ALL options fitted

Hardware:
- **UPL‑B1** — Low Distortion Generator (ultra‑low‑THD analog gen; measure the DUT, not the instrument).
- **UPL‑B29** — Digital Audio I/O, 96 kHz (AES3/EBU + SPDIF generate & analyze; 32/44.1/48/88.2/96 kHz,
  variable 35–106 kHz, high‑rate mode). (B2 = the base 55 kHz variant; user has the 96 kHz B29.)
  B29 vs B2 board-level differences (same front I/O board 1078.4223.02, newer main board): see
  **`B29_HARDWARE.md`**. Feb 2022 selftest photo showed no B21/B22/B23 — enabled since.
- (UPL‑B5 speaker/monitor — hardware; assume fitted per "all options".)

Software (user has ALL software options):
- **UPL‑B4** — Remote Control (SCPI over IEC/GPIB and RS232/COM2).
- **UPL‑B6** — Extended Analysis Functions.
- **UPL‑B10** — Automatic Sequence Control (on‑instrument test scripting / UPL‑BASIC sequencer).
- **UPL‑B21** — **Digital Audio Protocol** (in-depth AES3/S-PDIF protocol analysis + generation,
  extends B2/B29; confirmed via brochure, see below). Pairs with 1GA36's `PROT*_DD.SAC` setups.
- **UPL‑B22** — **Jitter and Interface Test** (runs on B29 digital hw; jitter‑sideband DAC demo
  IS available; confirmed via brochure).
- **UPL‑B23** — Coded Audio Signal **Generation**. **CORRECTED 2026‑09‑23:** this entry previously
  read "decode/analyze AC‑3 / MPEG / DTS bitstreams" — wrong on both counts. Vol.2 names it
  "UPL‑B23 (Coded Audio Signal Generation)" and puts every command under **`SOURce:CODedaudio`**
  (§3.10.1.5.14); `README.B23` agrees. It **generates** IEC 61937 bitstreams from a library of
  pre-coded WAV files — it does not decode or analyze them. **Formats: AC‑3 and DTS; no MPEG.**
  (A same-day follow-up correction: this line briefly said "AC‑3 only, no DTS", following the
  operating manual's "other formats are in preparation". The later R&S B23/UPZ datasheet, v02.00
  January 2004, from the shared Drive archive, says DTS *is* supported — 192 kbit/s stereo,
  754 kbit/s 5.1 and single-channel — plus special signals: AC‑3 dialog-normalization files and
  AC‑3/DTS full-scale files. The manual text simply predates it. **But the B23 library we actually
  have contains AC‑3 files only** (`CODED/AC3/48000/…`), so in practice this unit can generate DTS
  only if a DTS library is obtained, and even then whether 3.06 reads it is unverified.)
  Practical consequence: B23 is for testing a *decoder*
  (an AV receiver), not for testing the M51 or the DCX2496, neither of which decodes AC‑3. See the
  UPA-CD / B23 section below for the full command set and the data-library path question.

No option caveats — full capability across analog, digital (≤96 kHz), jitter, protocol, and
coded‑audio domains. (`*OPT?` on the instrument, 2026-09-22, also showed a bare "B21" among the
option tokens, which is now identified above — previously flagged as unknown.)

### User's DUTs and tailored tests
- **Behringer DCX2496** (DSP speaker management, XLR analog + AES/EBU): verify crossover filter
  slopes via UPL sweep, THD+N/noise/dynamic range of its converters, latency, channel matching,
  digital‑in→analog‑out (via B29).
- **SPDIF DAC = Elektor "Audio DAC 2000"** (T. Giesberts, Elektor Electronics 11/99, 12/99,
  1/2000; user has the article PDFs, e99b058 / e99c078 / e001012).
  Original: CS8414 → DF1704 8× filter → PCM1704 ×2 → OPA627 I/V (2k49 ‖ 47 pF) → 3rd-order
  passive filter (Butterworth 26 kHz, or Bessel 42 kHz at 88.2/96, relay Re2/Re3 per channel,
  selected by the GAL's DBW from the CS8414's rate detection) → OPA627 buffer → 100 Ω → mute
  relay Re1. De-emphasis driven by the received channel-status bit (DF1704 SF0/SF1 on DIP S3).
  **User's mods:** I/V op-amps → **AD797**; **AD1896 ASRC** added between receiver and DAC board.
  Consequences worth remembering: the AD797 (110 MHz) has a reputation for HF instability in I/V
  service — prime suspect for erratic/unequal channels, check with a scope; DBW/de-emphasis still
  follow the *input* rate, not the ASRC's output rate; the ASRC should make the jitter tests show
  near-total rejection; DF1704 max input rate is 96 kHz, so the ASRC output must be ≤ 96 kHz.
  Published spec: 2.1 V rms, −0.94 dB @20 kHz (−0.66 at 88.2/96), Zout 100 Ω, THD+N 0.001 %
  (48k/24-bit, B=80k), S/N ≥ 114 dBA, SMPTE IMD 0.0035 %, separation > 115 dB @1 kHz —
  kept in `measurements/dut_specs/elektor-dac2000.json` (`--dut-spec elektor-dac2000`) — the test
  script itself stays DAC-agnostic, per the user. (44.1/48/88.2/96 kHz): UPL generates SPDIF
  (B29) → DAC → UPL analog analyzer.
  **UPL digital output stage (Service Manual Vol.2 p.247, "Output Circuit, Front Panel
  1078.4223", 2026‑09‑24):** UNBAL = CLC430 op-amp → 100 nF → 1:1 Mini-Circuits T1‑6T transformer
  T2 → R82‖R83 (150‖150 = **75 Ω** series) → BNC, secondary floating (R283 ground link not fitted).
  BAL = transformer T3 → 2 × (110‖110) = 55 Ω per leg = **110 Ω** → XLR. So the BNC is a proper
  75 Ω S/PDIF source: coax DACs need no 110→75 Ω transformer (the README said otherwise until
  this date). Drawings are for the B2 (1078.4100); B2 and B29 share the same output board, 1078.4223.02 (user; confirmed from photos — see `B29_HARDWARE.md`).
  User reports (2026‑09‑24) that it "sounds great but measures strange": **frequency response
  all over the place and unequal between channels.** Test suite written for it:
  `measurements/spdif_dac_test.py` — **renamed `dac_test.py` on 2026‑09‑24, with a `--source pc`
  option for USB DACs (see below)** (see README) — FR as broadband *and* selective RMS, repeated,
  with an automatic diagnosis (L/R mismatch vs image/hum contamination vs non-repeatability vs
  NOS sinc droop), plus THD+N, images, IMD, crosstalk, Zout, polarity, **jitter transfer via B22**
  (the old "needs B22" note here was stale — B22 is fitted), and interface robustness. Not yet
  run live; diagnosis logic verified offline against a simulated faulty DAC.
- **Sony NW-A306** (Walkman DAP, added 2026‑09‑24): 3.5 mm headphone out only, S‑Master HX
  (class‑D‑style) output stage — so THD+N/noise need a routed ≤20 kHz LP, and A22-vs-A100 RMS shows
  the ultrasonic residue. **It has a USB‑DAC mode** (Sony help guide; Music player → USB DAC), so the
  PC can drive it like the M51; one review says USB input is 48 kHz max — unverified. Hi-res paths
  are then only reachable by copying files onto it and using `upacd_test.py --external`. Test
  plan: volume law/L‑R imbalance, max output at no load / 32 Ω / 16 Ω (resistor load box), Zout,
  FR, THD vs THD+N, noise (battery vs USB-connected — USB also grounds it to the laptop), crosstalk
  *under load* (shared TRS ground), IMD, linearity, J‑test. Turn off DSEE/ClearAudio+/EQ/AVLS.
  Test WAVs: `tools/testsignals.py` (generic, any DAC — see README). Nothing measured yet.
- **One DAC suite, two sources (2026‑09‑24).** `spdif_dac_test.py` → **`measurements/dac_test.py`**.
  `--source upl` (default) = the UPL's B29 generator into S/PDIF/AES, unchanged: an offline SCPI
  trace diff against the old script shows only redundant extra resets, and the `--dry-run` CSVs are
  identical. `--source pc --device N` = this PC synthesizes each tone and plays it bit-exact
  (int32 loop, PortAudio dither off, WASAPI exclusive) into a USB DAC. Differences the PC source
  forces: selective RMS uses `SENS:FREQ:MODE FIX` + `SENS:FREQ <f>` per tone (Vol.2 p.3.114; there's
  also `CH1`/`CH2`, tracking the measured input frequency — unused), aperture AUTO instead of GENT,
  THD/THD+N find the fundamental from the signal (`SENS:VOLT:FUND:MODE AUTO`, their default), but
  **DFD/MDIS take their frequencies from the UPL generator's settings** (m51_imd.py's finding), so
  the PC source also sets the matching `SOUR:FUNC DFD|MDIS` + frequencies there, muted at 1e-20 V.
- **M51 folded into `dac_test.py` (2026‑09‑24).** `--dut m51 [--dut-port COM2] [--volume dB]` logs
  the M51's source/volume in the report and, with `--volume`, sets it for the run and restores it.
  In the M51's **fixed-output** mode no `--volume` is needed — it's a plain DAC to the suite. New
  `volsweep` test = the old `m51_gain_sweep.py` (THD+N/THD/level vs DUT volume; not in `all`).
  The five `measurements/m51_*.py` scripts were **deleted** (recoverable from `aa6dfa1`): fr/thdn,
  imd/imdlevel, jtest/fft and volsweep cover them; `m51_freq_stability`'s counter-scatter jitter
  proxy was dropped in favour of `jtest`. `nad_m51.py` stays as the driver. Caveat: those scripts
  had been run live; their `dac_test.py` replacements have not. Tone frequencies are snapped to 1 Hz (0.1 Hz below 100 Hz) so the loop is
  seamless. `jitter`, `interface`, `polarity` are UPL-only. Multitone tones aren't on UPL FFT bins
  (no ATRack from outside), so the window's skirts set the between-tone floor. **Not run live.**
  `upacd_test.py` stays separate: it's for *fixed* recordings (disc tracks, generated files,
  `--external` players), where the PC doesn't control each tone.
- **`upacd_test.py linearity` fix (2026‑09‑24):** it measured *broadband* RMS and found steps by
  frequency lock, so the bottom steps read the noise floor or vanished. Now RMS selective (1 %
  band fixed at 1 kHz), steps located by time between the 2 kHz markers, referenced to the first
  step. Also fixed an unquoted `SENS3:FUNC FREQ` in its setup (quoted names only, else `-141`),
  and two `poll_upl` bugs the dry-run stub (bare numbers) hid: it `float()`ed replies that carry a
  unit (`0.999 V` → ValueError → *every* reading silently dropped on real hardware), and it
  discarded a reading whenever the frequency counter returned the sentinel, which is exactly
  the buried-step case. Now: first token parsed; no-lock keeps the level with frequency NaN.
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
- UPL **COM2**: **8 data, no parity, 1 stop, RTS/CTS handshake**.
  **Baud: use 115200** — confirmed live, and the default in every tool here. (This line used to say
  "2400–19200 (use 19200)", which was the range in `RS232_BT.BAS`; Vol.2 §3.17.1 prints
  2400–56000. Both are wrong/incomplete: **115200 is listed in the UPL's own OPTIONS panel and
  works** — see "Remote baud rate — CORRECTED" below. 19200 and 56000 also work, just slower.)
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
  `SENS:FILT<i>:UFILter<n> ON` (i=slot 1‑3) to actually engage it.
  **CONFIRMED 2026‑09‑23 — hypothesis was right.** The shipped firmware demo `DISK2/DEMOEXAM.LZH →
  DEMO.BAS` does exactly this: `SENS:FILT OFF` → `SENS:UFIL:PASS:LOW 3 KHZ` →
  `SENS:UFIL:PASS:UPP 4 KHZ` → **`SENS:FILT:UFIL1 ON`**. Defining a user filter does not engage it;
  the slot assignment is what routes it into the measurement chain. So the bandwidth-limited THD+N
  measurement needs the assignment line our 2026‑09‑22 test was missing.
  **VERIFIED LIVE 2026‑09‑24** (`measurements/filter_test.py`, B1 1 kHz 1 V loopback, THD+N):
  none −106.6 · 20 kHz LP −106.7 · 10 kHz −108.5 · 5 kHz −110.5 · 3 kHz −112.4 dB — about 1.9 dB
  per halving of bandwidth (white noise would give 3), so the loopback residual is LF-heavy.
  Working order: `SENS:FILT OFF` → `SENS:UFIL1:LPAS ON` → `SENS:UFIL1:PASS <Hz>` →
  `SENS:FILT1:UFIL1 ON`. **Gotcha: a 22 kHz LP is accepted when defined but rejected when routed**
  (`111,"Device dep error; Error in Filter specification"` — too close to the A22 band edge), and
  after that the filter refused further changes (`-222`). Keep LP cutoffs ≤ 20 kHz on A22.
  **Filters apply to the FFT too** (up to 3). White noise (`SOUR:FUNC RAND; SOUR:RAND:DOM TIME;
  SOUR:VOLT:TOT 1 V`) through `SENS:FILT1:AWE ON` reproduced the A-weighting curve (−17.7 dB near
  100 Hz, +1.8 at 2–3 kHz, −7.5 at 15–18 kHz vs unfiltered); a user bandpass
  (`SENS:UFIL2:BPAS ON; …:PASS:LOW 1000 HZ; …:PASS:UPP 5000 HZ; SENS:FILT1:UFIL2 ON`) was flat
  1–5 kHz and 50–65 dB down outside. `CALC:TRAN:FREQ:AVER 16` averaging accepted.
  Manuals: `R&S_UPL_Audio_Analyzer_Op_Vol_1.pdf` / `_Vol_2.pdf` one level up from this folder.
  Vol 2 = remote/IEC‑bus command reference (confirmed).
  Extract text for searching with `pdftotext -layout <file> out.txt` (available in this env).
- Unrecognized *query* names cause a read timeout (no reply); unrecognized *set* commands just queue an
  error (safe). Check/drain with `SYST:ERR?` (FIFO, one entry per query; `0,"No error"` = empty).
- Trace: `TRAC:POIN? TRAC1`, `TRAC? TRAC1` (comma‑separated), x‑axis `SOUR:LIST:FREQ?`
- Source cfg (EXAM7): `SOUR:SWE:MODE AUTO`, `SOUR:FREQ:MODE SWE2` (**note: for a normal X-axis
  frequency sweep you want `SWE1` — see "UPL native sweep engine" below**), `SOUR:FREQ:STAR/STOP`, `INP:TYPE`,
  `SENS:FILT:AWE`, `DISP:CONF`, `CALC:EQU:INV`, `SOUR:VOLT:EQU:STAT`
- File mgmt (MMEM children in EXE): `STORe`, `DATA`(`MMEM:DATA? 'file'`), `CATalog`, `DELete`,
  `CDIRectory`, `COPY`, `CHECk` (checksum, matched by `UPMD5.EXE`)
- Data format node: `FORMat` = `BIN | ASCii | EXPort`. Trace‑list store format REAL/ASCII/**EXPORT**;
  EXPORT = readable numbers in display units, Excel‑ready (no header/footer).
- **RESOLVED 2026‑09‑23 — store a trace to a file remotely** (was "STILL UNCONFIRMED"). Documented in
  Vol.2 §3.10.5.1.1 *Loading and Storing Traces and Lists*, and used verbatim by four independent R&S
  app-note programs (`IMPEDANC.ASC`/`SOUND.ASC` in 1ga16_1l, `CDTEST.BAS` 1GA21, `TUNTEST.BAS` 1GA24,
  `Adctest.bas` 1GA30):
  ```
  MMEM:STOR:FORM BIN | ASCii | EXPort      ; EXPort = plain text table, .EXP ext, no extra info
  MMEM:STOR:TRAC TRACe1,'C:\UPL\SWEEP.EXP' ; trace A buffer   (app notes also use short form TRAC / TR1A)
  MMEM:STOR:TRAC TRACe2,'...'              ; trace B buffer
  MMEM:STOR:TRAC TR1And2,'...'             ; both traces
  MMEM:STOR:LIST LIST1,'C:\UPL\SWEEPX.EXP' ; X-axis list   (LIST2 = Z axis, DWELl = dwell times)
  MMEM:STOR:LIST ERRors|LIMUpper|LIMLower,'...'   ; limit report / tolerance curves
  ```
  Caveat from the manual: EXPort files carry no header info, so the **UPL cannot read them back** —
  use ASCii/BIN if the file has to be re-loaded into the instrument, EXPort if it's going to the PC.
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
# 1. On UPL: FILE panel -> Info Text (under STORE INSTRUMENT STATE) -> full source path,
#    e.g. C:\UPL\MYTRACE.EXP   (1GA42 says "Display panel" -- wrong for firmware 3.06)
# 2. On PC, start the receiver FIRST (must be listening before the send is triggered):
python ser_in.py --port COM2 out\MYTRACE.EXP
# 3. On UPL: OPTIONS panel -> Exec Macro -> SELECT (file box of *.BAS) ->
#    C:\UPL\USER\SNDFILE.BAS -> ENTER. There is no menu item called "SNDFILE".
# 4. ser_in.py stops itself on idle timeout and reports the byte count.
```
**VERIFIED LIVE 2026‑09‑23** — see "Live bring-up results". The `COMX.SYS` driver was already
installed on this unit (SNDFILE opened COM2 fine), so **`DRV_INST.BAS` is not needed**. For the
record, DRV_INST is *not* a read-only check: if `CONFIG.SYS` has no `device…comx` line it appends
`devicehigh=c:\upl\driver\comx.sys` *before* asking "Reboot now <Y> or quit <Q>".

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

**Confirmed 2026‑09‑23 by decompressing `DISK2/USER.LZH`** with `tools/lzh_extract.py` (a
pure-Python `-lh5-` decoder written because `LHA.EXE` is 16-bit DOS and there's no `lha`/`7z` here;
`python tools/lzh_extract.py DISK2/USER.LZH` lists, `... USER.LZH SNDFILE.BAS` extracts).
`SNDFILE.BAS` contains the literal line:
```
OPEN "com2:115000,n,8,1,10000,10,v,m" ...
```
so the port really is hard-coded, and the port contention above is real, not hypothetical — the
macro opens COM2 itself while SCPI is also using COM2. 1GA42_0E says as much: *"The COM2 interface
from the UPL is used by default for data transfer. To change the interface used, edit the
SNDFILE.BAS (Basic) program."* So the fully-remote, RS232-only path is possible if SNDFILE.BAS is
edited to `com1:` on the instrument and a **second** serial cable is run from UPL COM1 to the PC.
`DRV_INST.BAS` (also decompressed) confirms this is viable: its own header reads *"Installation of
device driver comx.sys for **COM1 and COM2**"* — it appends `devicehigh=c:\upl\driver\comx.sys` to
`c:\config.sys` and reboots, and the driver covers both ports. Otherwise: manual trigger.
`USER.LZH` also holds `SELFTEST.BAS`, `DRV_INST.BAS`, `SER_IN.EXE`, `FLAT_GEN.BAS`, `IMPEDANC.BAS`.

## Tools in this folder

### `upl_capture.py` — pull data off the UPL over RS232 (needs pyserial; installed)
Subcommands:
- `probe` — `*IDN?` to confirm remote/B4 is live.
- `read` — live values (rms/peak/freq/phase, both channels).
- `sweep -o f.csv` — capture current sweep trace to CSV.
- `autoexport [-o] [--setup] [--both] [--repeat N --interval S] [--opc]` — **trigger a fresh sweep
  and pull trace(s)+x‑axis to a timestamped CSV; no file created on the UPL.** (Primary tool.)
- `catalog [path]` — `MMEM:CAT?` list UPL files.
- `getfile "C:\UPL\X.EXP" -o local` — pull an existing UPL file (488.2 block) and print the UPL's
  MD5 of it. **VERIFIED 2026‑09‑24 over both RS‑232 and GPIB** — 1GA42's "not supported" is wrong
  for 3.06. For many files, with MD5 checking and retries, use `tools/upl_backup.py`. See
  "GPIB (Agilent/Keysight 82357B)" for both.
- `raw "SCPI"` — send one command (query if it ends `?`).

Example: `python upl_capture.py --port COM7 probe` then `… --port COM7 autoexport --opc`.

**LINK VERIFIED 2026‑09‑22:** `probe` returned `ROHDE & SCHWARZ, UPL, 3.06, 0.33` — remote/B4
confirmed. Verified on both **COM7** (FTDI) and **COM2** (Prolific PL2303), 8/N/1 RTS/CTS — at
19200 *at the time*; the link has since been moved to **115200**, which is the current default
everywhere. Prolific gave 5/5 stable `*IDN?` across processes AFTER a reboot. NOTE: pre‑reboot the Prolific
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

`SELFTEST_Program.TXT` (user-supplied, one directory up from this project) is a genuine R&S
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
  remains untested *live*, but is no longer necessary to explain the THD+N result — and the missing
  piece was found documentarily on 2026‑09‑23: a user filter must be **assigned to a filter slot**
  (`SENS:FILT:UFIL1 ON`) to engage, which is why the earlier attempt did nothing. See the UFILter
  note in "SCPI vocabulary confirmed present".
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
- **As of the 2026‑09‑23 evening session: UPL → this PC's COM2 (Prolific)** — the FTDI was not
  plugged in at all (only COM2 enumerated). The DCX2496 had no link that session. The Prolific
  **doubles a byte** when the UPL drops CTS mid-line — see "Live bring-up results" below; `nsweep`
  now works around it, but prefer the FTDI for the UPL whenever it's available.
- Earlier: **UPL → this PC's COM7** (FTDI adapter). Baud **115200** (was 56000 earlier in the session;
  115200 was set on the OPTIONS panel and confirmed live, and persists through a UPL restart).
- Earlier: **DCX2496 → this PC's COM2** (Prolific adapter).
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
EQ-band param-numbering (step-of-5) **was** unverified at this point — **superseded: it was
confirmed live later the same day**, along with a gotcha (param `0x07` gates how many bands are
active; band 2+ are silently ignored unless it's raised). See "EQ-band unknown RESOLVED" below.

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

### UPL native sweep engine — parked 2026‑09‑23, root cause identified same day (see end of section)

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

**ROOT CAUSE FOUND 2026‑09‑23 (documentary, not yet re-tested live)** — from Vol.2 §3.10.10 /
§3.10.6 plus R&S's own app-note programs. Two concrete errors in the attempt above:

1. **`SOUR:FREQ:MODE SWE2` was the wrong sweep.** Vol.2 p.3.55: `SWEep1` = "frequency as **X axis**",
   `SWEep2` = "frequency as **Z axis**" (the nested/outer sweep dimension). With SWE2 the frequency
   went to the Z list, so the X/Y1 trace was never filled — hence `TRAC:POIN? TRAC1` → `0`. Every
   R&S example uses `SOUR:SWE:MODE AUTO;:SOUR:FREQ:MODE SWE1`.
2. **`DISP:TRAC:FEED` was never set.** Vol.2 §3.10.10 footnote 1 on `TRACe[:DATA] TRACe1` states the
   block data depends on `DISPlay:TRACe:FEED` *and* `SENSe1:FUNCtion`. The trace buffer is a display
   object: nothing is recorded into it until a source is fed to it.
   `DISP:TRAC[1|2]:FEED 'SENSe1:DATA1'|'SENSe1:DATA2'|'SENSe2:DATA1'|'SENSe2:DATA2'|'SENSe3:DATA1'|
   'SENSe3:DATA2'|'HOLD'|'FILE'|'DFILe'|'OFF'` — SENS1 = the function set by `SENS1:FUNC` (DATA1=CH1,
   DATA2=CH2), SENS2 = input RMS (for THD/THDN), SENS3 = frequency / phase / group delay.

Two lesser points from the same sources:
- `INIT:CONT OFF;*WAI` is itself the **single-sweep trigger** in R&S's examples, not just a mode
  switch; `INIT:CONT ON` = continuous. Plain `INIT;*WAI` also appears (Adctest.bas), so both work.
- X axis: `TRAC? LIST1` is the documented read (`LIST2` = Z axis). `SOUR:LIST:FREQ?` also returned
  the right axis in our live test; either is fine.

Working sequence per the manual's own frequency-sweep example (Vol.2 §3.15.9.1, p.3.305) plus the
block-data rules, to try next time:
```
FORM ASC                                   ; block data as comma-separated ASCII (power-on default)
*RST;*WAI
SENS1:FUNC 'RMS'                           ; whatever is being swept
DISP:TRAC:OPER CURV                        ; curve-plot display mode
DISP:TRAC:FEED 'SENS1:DATA1'               ; <-- the piece that was missing
DISP:TRAC:X:SPAC LOG
SOUR:SWE:MODE AUTO;:SOUR:FREQ:MODE SWE1    ; <-- SWE1, not SWE2
SOUR:FREQ:STAR 20 HZ; :SOUR:FREQ:STOP 20000 HZ
SOUR:SWE:FREQ:SPAC LOG;POIN 40
DISP:CONF AP                               ; analyzer panel + graphic window
INIT:CONT OFF;*WAI                         ; single sweep, blocks to completion (LONG timeout, 90s+)
TRAC:POIN? TRAC1                           ; point count
TRAC? TRAC1                                ; Y values (trace A)
TRAC? LIST1                                ; X values
```
**`FORM ASC` matters on RS232.** Vol.2 §3.5.4/§3.17.6: `FORM REAL` makes `TRAC?` reply a binary
488.2 block with *no delimiter* — over RS232 there is no EOI to end it, so the receiver must count
bytes from the `#<n><len>` header, and any 0x0A in the payload will break an LF-framed reader.
`FORMat[:DATA]` is not stored in the setup and resets to ASCII on power-up.

**IMPLEMENTED 2026‑09‑23 as `upl_capture.py nsweep` and `upl_capture.py storetrace`** — both written
from the documentation, **neither yet run against the instrument.** Supporting offline machinery:
- `--dry-run` on every subcommand → `DryRunUPL` stub, no serial port, prints the SCPI, canned replies.
- `upl_capture.py seqcheck` → asserts the emitted sequences match the documented ones (presence,
  ordering of FEED-before-trigger and STOR:FORM-before-STOR:TRAC, no `SWE2`, no `FORM REAL`).
- `parse_values()` → turns the `"No Values"` / empty-trace reply into a diagnostic naming the three
  likely causes instead of an opaque `float()` crash. Also now used by `sweep` and `autoexport`.

### FFT "zoom quirk" RESOLVED 2026‑09‑23 — it was the 1024-line block limit all along

`measurements/m51_jitter_fft.py` carried a hard-won note that only `CALC:TRAN:FREQ:ZOOM 1` gave a
trustworthy readout; that `ZOOM>1 + CENTer` left the peak "stuck at silence-floor level, no
consistent axis"; that `CALC:TRAN:FREQ:STARt?/STOP?` reported "a wider theoretical span than what
TRAC1 actually returns"; and that the usable range was "0 – ~6000 Hz". **All three symptoms are one
cause, and it is documented, not a firmware bug.**

**`TRAC?` returns at most 1024 values. Full stop.** (Vol.2 §3.15.11.2.1: *"TRAC? TRAC permits 1024
values to be read"*.) The FFT has far more lines than that — Vol.1 §2.6.5.12 p.2.221:
```
Zooming OFF, analog : size * 117/256        8192 -> 3744 lines
Zooming OFF, digital: size * 127/256        8192 -> 4064 lines
Zooming ON          : size * 117/256 * 2    8192 -> 7488 lines
```
(the FFT is complex after the zoom shift, which is why you never get size/2). So a single `TRAC?`
returns only the **first block**, silently, with no error:
- **Unzoomed:** block 0 = lines 0…1023 = 0 … 1024 × 5.859375 = **5999.9 Hz**. That is precisely the
  observed "0 – ~6000 Hz" ceiling. The remaining 3 blocks (out of 4) were never read.
- **Zoomed:** block 0 is the bottom eighth of the zoom span, nowhere near `CENTer` — the tone sits
  in a middle block, so block 0 is pure noise floor. That is precisely "peak stuck at silence-floor
  level". Zoom was never broken; we were reading the wrong eighth of it.
- **`STARt?`/`STOP?` were correct all along.** They describe the whole FFT; `TRAC?` was handing back
  one block of it. Not a quirk — the two were answering different questions.

Sanity check: 3744 × 5.859375 = 21937.5 Hz = the 21.938 kHz upper limit in Vol.1 Table 2-31. And
the manual's own worked example (Vol.2 §3.15.11.2.2) reads *"the 7488 lines of a 8k-zoom FFT with 8
blocks each (7 × 1024 and 1 × 320)"* — the same arithmetic.

**Fix:** `DISP:TRAC:IND <n>` selects which block the next `TRAC?` returns (index 0…7 for FFT blocks;
the same command selects trace index 0…17 when several traces are displayed). R&S's own loop:
```
FOR Blkidx=0 TO 7
  IEC OUT 20,"DISP:TRAC:IND"+STR$(Blkidx)
  IEC OUT 20,"TRAC? TRAC"      : ' Y values for this block
  IEC OUT 20,"TRAC? LIST1"     : ' X values for this block
NEXT Blkidx
```
Take the X axis from `TRAC? LIST1` **per block** rather than computing `bin × resolution` — LIST1 is
correct for zoomed FFTs too, where a block does not start at 0 Hz.

Two related facts worth keeping:
- **Over the bus you set the zoom FACTOR, never the SPAN** (Vol.2 p.3.134): *"Contrary to the manual
  mode, the zoom factor instead of the SPAN is entered … SPAN can only be read in but not entered"*.
  `CALC:TRAN:FREQ:SPAN?` is query-only. Zoom factors: 1,2,4,…,128 for A22/D48; only 1,2,4,8,16 for
  ANLG 110 kHz.
- With Zooming ON the real line count can be **lower** than the formula — an eccentric `CENTer` can
  push some lines into negative frequencies (Vol.1 §2.6.5.12 note). So treat the formula as an upper
  bound and page until a block comes back short.
- Noise-floor thinning, if the full spectrum is too much data: `DISP:TRAC:OPER FFTErrors` +
  `CALC:LIM:UPP:VAL 0.1V` makes `TRAC?` return only lines above the limit (Vol.2 §3.15.11.2.3).

**Implemented** in `upl_capture.py` as `read_fft()` / `fft_line_count()` and an `fft` subcommand;
`m51_jitter_fft.py` now uses `read_fft()` and gained `--zoom` / `--center`. `seqcheck` asserts the
paging emits `DISP:TRAC:IND 0..3` and recovers all 3744 lines from the stub instead of 1024.
**Verified live 2026‑09‑23 (evening)** — see "Live bring-up results" below. `m51_jitter_fft.py`
not yet re-run.

### Bring-up checklist for the next live session (nsweep / storetrace)

Do these in order; each step isolates one unverified assumption.

1. `python upl_capture.py seqcheck` — offline, should pass before anything is plugged in.
2. `python upl_capture.py --port COMn probe` — confirm the link (`ROHDE & SCHWARZ, UPL, 3.06, …`).
3. **Loopback first, no DUT:** `raw "*RST"`, then `raw "INP:TYPE GEN2"` (internal generator →
   analyzer, confirmed working 2026‑09‑22). A sweep here has a known-good answer: flat.
4. `python upl_capture.py --port COMn nsweep --points 10 --volt 1.0 -o /tmp/fr.csv`
   — small point count first, so a stall costs seconds not minutes. Expect ~flat ≈1.0 V.
   - If `TRAC:POIN? TRAC1` → `0`: FEED is *not* the suspect it was when this checklist was written —
     `SOUND.ASC` has the whole FEED→sweep→`TRAC?` chain, so the approach is sound and the fault is
     more likely a rejected command or a missing precondition. Probe `DISP:TRAC:FEED?` (reply comes
     back *with* quotes, e.g. `'SENS:DATA'`) and `DISP:TRAC:OPER?` to see what actually stuck, and
     check `SYST:ERR?` immediately after each config command to find which one was rejected.
   - If the sweep times out: raise `--sweep-timeout`; 40 points took ~17 s, so a slow function
     (THDN with long averaging) could take minutes.
5. Only then scale up: `--points 40`, a real DUT, `--both`.
6. `storetrace` second, since it depends on a populated trace:
   `nsweep` → `storetrace "C:\UPL\FR.EXP" --xaxis --verify` → check `MMEM:CAT?` shows both files
   with non-zero sizes. If `MMEM:STOR:TRAC` errors, try the app-note short forms (`TRAC`, `TR1A`)
   which is what R&S's own programs actually send, rather than the manual's `TRACe1`/`TR1And2`.
7. Then the transfer half: `ser_in.py` listening on the PC, Info Text + OPTIONS→SNDFILE on the UPL.
   Compare the received byte count against the `MMEM:STOR:INFO?` reply.
8. UPL‑B23 data library — cheap, do it while you're there:
   `MMEM:CAT? 'C:\CODED\AC3\48000'` **and** `MMEM:CAT? 'C:\UPL\AC3\48000'` (the README and the
   manual disagree on which path the firmware reads). If present, the smallest real test is
   `INST D48; SENS:DIG:FEED ADAT; OUTP:SAMP:MODE F48; SOUR:FUNC CODedaud; SOUR:COD:FORM AC3;
   SOUR:COD:CHAN CH2; SOUR:COD:FREQ F997` then `SYST:ERR?`.
9. FFT block paging: `upl_capture.py --port COMn fft --size 8192 -o /tmp/fft.csv`. Expect **3744**
   lines spanning 0–21.9 kHz across 4 blocks, not 1024 lines stopping at 6 kHz. Then re-run
   `m51_jitter_fft.py` and confirm a tone above 6 kHz (e.g. `--freq 10000`) now appears at all —
   under the old single-`TRAC?` readout it could not have. Then try `--zoom 8 --center 10000`.

**Remember the cleanup gotcha** — `nsweep` sends `SOUR:FREQ:MODE FIX` at the end by default
(`--no-restore` to skip). Without it, later plain `SOUR:FREQ <f> HZ` commands silently
misbehave, which would corrupt any subsequent `dcx_sweep.py` host-stepped run.
**CORRECTED 2026‑09‑23 (live):** this used to say "and `SOUR:SWE:MODE OFF`". There is no such
value — `SOUR:SWE:MODE` takes only `MANual | AUTO` (Vol.2 command table) and `OFF` is rejected
with `-141 Invalid character data`. `SOUR:FREQ:MODE FIX` alone ends the sweep (read back `FIX`
after an `nsweep`). Note `*RST` does **not** clear the error queue, so a stale `-141` surfaces
one run later — use `*CLS`.

### Live bring-up results, 2026‑09‑23 (evening) — nsweep, fft, storetrace, diagdump

Internal loopback (`*RST; INP:TYPE GEN2`), UPL on PC COM2 at 115200.

- **`nsweep` VERIFIED.** 10 pts in 4.9 s, 40 pts in 11.1 s (faster than the 16.7 s SWE2 attempt).
  0.998–0.999 V from 20 Hz to 20 kHz, flat to ±0.05 %, correct log X axis from `TRAC? LIST1`.
  `DISP:TRAC:FEED?` reads back `'SENS:DATA'` — quotes included, as SOUND.ASC implied. The SWE1 +
  FEED diagnosis was right. Three bugs found and fixed on the way:
  1. **Each sweep-parameter command (`SWE:MODE`, `FREQ:MODE`, `STAR`, `STOP`, `SPAC`, `POIN`) takes
     2–3 s to execute.** Back to back they need ~12 s, which timed out the following `SYST:ERR?`.
  2. **The Prolific PL2303 doubled a byte, every run, in the compound
     `SOUR:SWE:MODE AUTO;:SOUR:FREQ:MODE SWE1`** — the UPL received `FREQQ`, `MOODE` (`-113
     Undefined header`). Mechanism: it starts executing the slow first half, drops CTS mid-line,
     and the adapter repeats a byte on resume. Fix in `nsweep`: one command per line, `*OPC?` after
     each slow one. Zero errors after the fix. **General rule for this link: never send a compound
     command whose first half is slow, and sync with `*OPC?` before the next write.** Any other
     script sending slow commands back to back over the Prolific is exposed to the same thing.
  3. `SOUR:SWE:MODE OFF` in the restore — see the correction above.
- **`fft` VERIFIED — the 1024-line explanation was exactly right.** 8k unzoomed: **3744 lines,
  4 blocks** (1024/1024/1024/672), 0–21 931.6 Hz; a 10 kHz tone found at 9996–10002 Hz, 0.968 V,
  median line 0.36 µV (~−129 dB) — in block 1, which the old single `TRAC?` never returned.
  Zoom 8 @ 10 kHz: **7488 lines, 8 blocks (7 × 1024 + 320)**, exactly the manual's worked example,
  7257.8–12741.5 Hz, 0.73 Hz resolution, peak at 9997.8 Hz in block 3.
- **`storetrace` + SNDFILE — VERIFIED END TO END. The Gotek is no longer needed for traces.**
  `C:\UPL\ZFR40.EXP` (trace A, EXPort) and `C:\UPL\ZFR40X.EXP` (X list) stored with `0,"No error"`;
  the long manual forms (`TRACe1`) work, and a full path overrides Work Dir (files landed in
  `C:\UPL`, not the `C:\UPL\USER` work dir). The FILE panel's STORE TRACE/LIST fields then showed
  the last remote store (`X AXIS / EXPORT / ZFR40X.EXP`). SNDFILE sent **863 bytes**; all 40
  values match the SCPI `TRAC?` readout to within 0.00005 V. What the EXPort file looks like:
  ```
  #X / Hz   	Y / V    	
   20.0000 	 0.9981 	
   23.8755 	 0.9983 	      (tab-separated, header line, one row per point)
  ```
  So **an EXPort trace already contains the X axis** — `--xaxis` is redundant for EXPort. And
  EXPort carries **display precision only (4 significant digits)**, whereas `TRAC?` over SCPI gives
  6. For numbers, prefer `nsweep`'s direct readout; storetrace + SNDFILE is for when the file itself
  is wanted, or for traces too long to be worth the SCPI round trips. `ZFR40*.EXP` are test
  files, safe to delete.
- **Every SNDFILE run takes COM2 away from SCPI remote.** Afterwards the UPL answers nothing on
  COM2, even `*IDN?`, with CTS still asserted and a bare LF flush doing nothing — the macro opens
  COM2 through `COMX.SYS` and the remote handler doesn't get the port back. **Recovery: OPTIONS →
  Remote via → IEC → COM2.** Needed after *every* transfer.
- **`MMEM:STOR:INFO '<path>'` sets SNDFILE's Info Text remotely** (reads back exactly), so no typing
  on the panel. After a run, `MMEM:STOR:INFO?` returns `' <n> bytes sent <path>'` (truncated to
  ~40 chars) or `'file not found'`. SNDFILE.BAS itself: read Info Text → open file → if that fails
  write `'file not found'`, else send in 1024-byte chunks and write the byte count.
- **Double-run trap:** when the macro finishes, the cursor is still on OPTIONS → Exec Macro, and
  any ENTER/SELECT there starts SNDFILE again — which reads its own "n bytes sent" sentence as a
  file name, writes `'file not found'`, and grabs COM2 again. It caught us twice. **Cursor-up to
  "Remote via" before pressing anything.** With that, 8/8 runs were clean.
- **`tools/sndfile_batch.py` automates the PC side** of a multi-file pull: waits for the link,
  checks the previous file (UPL byte count, plus the `.CAL` header point count vs. data rows),
  sets the next Info Text, listens. Operator per file: LOCAL → Exec Macro → ENTER → cursor up →
  Remote IEC → COM2 → wait ~5 s. Appends to `<outdir>/manifest.csv`.
- **`C:\UPL\REF` BACKED UP, 2026‑09‑23, over RS‑232** → `results/REF/` (git-ignored), every file
  verified by the UPL's byte count and/or the header row count:
  | File | Bytes | Content |
  |---|---|---|
  | `FLAT_GEN.CAL` | 30778 | generator flatness, 1024 pts 2 Hz–21.6 kHz, 0.99901–1.00026 (<±0.01 dB) |
  | `FLAT1AC/1DC/2AC/2DC.CAL`, `FLAT_AC/DC.CAL` | ~10150 each | analyzer flatness, 430 pts each, 1 Hz–22.08 kHz |
  | `EANSTR.XMM` | 41954 | German UI string table ("String für UPD und UPL") — not calibration |
  | `GLEI_RAU.BPZ` | 141 | **binary** — and still byte-exact, so SNDFILE handles binary |
  | `GL_EPI.LOG` | 2 | — |
  `.CAL` format: 7 header lines (`213 2 10 1 <npts> 1 0`), `#----X----Y----`, then X/Y rows.
  The REF listing continued past `GL_EPI.LOG` off-screen — **remaining REF files not yet pulled**;
  `C:\UPL\SETUP\CAL_*.SET` (the other calibration store) also still to do.
- **The front-panel file box is the working substitute for `MMEM:CAT?`.** Any filename field →
  SELECT opens a browser (`*.*` from FILE→Copy SOURCE; `*.BAS` from OPTIONS→Exec Macro).
  `C:\UPL\USER` holds `DRV_INST SNDFILE FLAT_GEN IMPEDANC INIT SELFTEST USERMAC .BAS`.
- **`FLAT_GEN.CAL` IS PRESENT in `C:\UPL\REF`** — the generator flatness correction is active at
  boot, so every internal-generator measurement we've made (the DCX2496/M51 sweeps, this loopback)
  included it. Per Vol.1 §2.6.9 it contains the *analyzer's* inverted residual response too, so it
  is right for UPL-gen → DUT → UPL-analyzer, and wrong only if the generator drives an external
  analyzer. Same directory also holds the analyzer flatness files **`FLAT1AC.CAL FLAT1DC.CAL
  FLAT2AC.CAL FLAT2DC.CAL FLAT_AC.CAL FLAT_DC.CAL`** plus `EANSTR.XMM`, `GLEI_RAU.BPZ`,
  `GL_EPI.LOG` (list continues off-screen) — **per-unit calibration, back up `C:\UPL\REF` with the
  disk image.** It's also a candidate for a no-screwdriver backup now: SNDFILE each file.
- **`MMEM:CAT?` is BROKEN on this firmware — don't use it.** With a path argument → `-100 Command
  error`. Without one → returns 1024 comma-separated numbers: the last FFT/trace block buffer, not a
  directory listing. So `catalog` and `storetrace --verify` don't work as written. The one reliable
  existence check found so far is for **directories**: `MMEM:CDIR '<dir>'` then `SYST:ERR?`
  (`0` = exists, `-222 Data out of range` = doesn't). `MMEM:CDIR?` → `'C:\UPL\USER'` at power-up
  state — restore it after probing. No file-existence check yet.
- **B23 path discrepancy RESOLVED:** `C:\CODED\AC3\48000` exists, `C:\UPL\AC3\48000` does not
  (`-222`). The library is installed where `README.B23` says.
- **`*OPT?` literal reply:** `B1(0.01),B29(2.16),B21,B22,B4,B5(1.62),B6,0,B10,0,B23,0` — the form
  with empty slots is the real one; the other transcription in this file is wrong.
- **`diagdump` run.** Results in `results/diagdump/full_20260923-225942/diag.{csv,json}` (moved
  there 2026‑09‑24 from `results/diag_full_2026-09-23.*`) — **git-ignored** (serial +
  option key; the repo has a public GitHub remote). Keep a copy with the disk image.
  - `SERN`: **4 words, `100330`, `6`, `412`, `0`**, ends with `-222` at addr 4. Words 0–1 match the
    known serial 100330/6 — the walk works. Words 2–3 are new; meaning unknown (date code? model?).
  - `INSTkey`: **10 words**, ends with `-222` at addr 10. The option key.
  - **`CAGEn`, `CANLr0`, `CLDG`, `CDPHase`: all refused at the select with `-222 Data out of range`**
    — not `-113`, so the keywords exist but a bare `DIAG:DEV <sel>` isn't enough. Likely needs a
    table/range argument or an instrument state. Don't guess on the hardware: find the argument in
    `UPL_UI.EXE`'s parser first. Calibration is therefore **not** backed up yet; the disk image
    (`SETUP/CAL_*.SET`, `CAL_DIG.SAC`) remains the only copy we have.
  - `RTEMperature` is not in the default selector list; not read.

### GPIB (Agilent/Keysight 82357B), 2026‑09‑24 — the real data-egress answer

**`MMEM:DATA? '<path>'` over GPIB returns any file on the UPL's disk as a 488.2 block.** App Note
1GA42 says UPL→PC transfer isn't supported over the bus — **wrong for firmware 3.06 over GPIB.**
Verified: `GL_EPI.LOG`, `GLEI_RAU.BPZ` (binary), `FLAT1AC.CAL`, `FLAT_GEN.CAL`, `EANSTR.XMM` all
byte-identical to their SNDFILE copies. **~110–150 kB/s**, vs ~11 kB/s for SNDFILE at 115 kbaud,
with no macro, no panel steps and no COM2. **SNDFILE is retired.**

**It works over RS‑232 too (2026‑09‑24)** — the `#<n><len>` header frames the data, so no EOI is
needed. `upl_capture.py getfile` fetched `GL_EPI.LOG`, `GLEI_RAU.BPZ` (binary), `FLAT_GEN.CAL`
byte-identical; `tools/upl_backup.py --port COM2` then pulled all 7 calibration files,
first attempt, byte-identical to the GPIB copies. **~10 kB/s** (the 115 200‑baud ceiling): the
calibration set in ~10 s, the whole 40 MB disk in ~70 min. **Serial-only owners need neither
SNDFILE nor a GPIB adapter.**

**`MMEM:CHECK? '<path>'` returns the file's MD5**, computed on the instrument, as 32 hex digits —
verified against local MD5s. `upl_backup.py` checks every file against it and retries (up to
`--retries 3`) on a mismatch. That check is what caught everything below.

RS‑232 lessons, each learned the hard way the same day:
- **Never change the serial timeout while data is flowing.** pyserial on Windows applies a timeout
  change by re-sending the whole port configuration; doing it right after the `#` arrived made the
  PL2303 garble or drop a byte **every time — always exactly one byte short**, whatever the file
  size (`739/740`, `8656/8657`, `84439/84440`; once the length digits themselves, `b'8444f'`).
  `getfile` never did that and was always clean. Set it once, before the request.
- **Replies queue in the UPL across sessions.** With RTS/CTS, if the PC stops reading mid-reply the
  UPL just waits, and resumes sending the moment *any* program next opens the port — so the next
  run reads the tail of an old file as its answers (looked like total line garbage; was actually
  readable `R&S_EXAM.SPO` content). **Fix: open the port and read until ~5 s of silence** — that
  drained **1 018 635 bytes** in 102 s here — or power-cycle the UPL.
- **CD (carrier detect) off on the PC side = the cable isn't seated.** With the connector loose the
  UPL saw our bytes (frame errors at wrong bauds) but nothing came back; CTS/DSR still read True.
  Screw both ends in.
- `upl_backup.py` sends `INIT:FORC STOP` first, as `RS232_BT.BAS`/`getfile` do "for clean
  transfer" (`--keep-running` to skip). It did not turn out to be the cause of the corruption
  (the timeout reconfigure was), but it's R&S's own practice. **It halts the running measurement.**

Setup: Keysight IO Libraries Suite (2023 U1 worked; **needed a PC reboot** before VISA would load —
`VI_ERROR_LIBRARY_NFOUND` until then) + `pip install pyvisa`. UPL: OPTIONS → **Remote via → IEC**,
address **20**. Every tool takes `--port GPIB0::20::INSTR` (`upl_capture.connect()` picks serial
or GPIB from the name). **Correction 2026‑09‑24:** that wasn't true yet — `upacd_test.py`,
`upl_selftest.py`, `dcx_sweep.py` and the four `dcx_*` measurement scripts opened the serial class
directly. All now use `connect()`; `COM7` stays the default, and `pyvisa` is imported only for a
GPIB name, so serial-only setups need nothing extra. Both classes raise `TimeoutError` on a
missing reply, so the scripts' error handling is the same either way. None re-run live since.

Hard-won details:
- **No Device Clear on open.** A clear right after opening made the UPL lose the next command 2 in
  12 (the read then times out, leaving `-420 Query UNTERMINATED`); without it 0 in 12. `connect()`
  syncs with `*IDN?` instead, reading until the reply really is the IDN.
- **Exception: a write that times out on open** means the UPL is still sending a reply from a
  killed session → Device Clear, then retry. Built in.
- **Never kill a GPIB transfer mid-block.** Stopping `gpib_backup.py` (now `upl_backup.py`) partway through a file
  **hung UPL_UI** — serial poll still answered (STB 16/20, MAV set), but no read returned data and
  writes timed out; Device Clear and IFC didn't recover it. **Power cycle** did.
- **Read blocks to EOI, with the LF termchar OFF.** With it on, VISA ends each read at every 0x0A
  in the payload: text files came in one line per read, 26.7 kB/s. Off: 113–146 kB/s.
- A missing file → no reply (timeout) + `-200,"Execution error;Could not open file '<path>'"`;
  the link stays usable. So names can be probed with a short timeout.
- An occasional lone `-420` appears even from a bare VISA open/close with **no** command sent —
  the Keysight driver addressing the device. Cosmetic.
- **`MMEM:CAT?` is broken over GPIB too** (returns the last trace buffer), so file names come from
  a DOS `DIR C:\ /S /A > C:\DIRLIST.TXT` (quit to DOS, run it, restart UPL) fetched over GPIB.
- **SNDFILE via `SYST:PROG:EXEC` with Remote via IEC fails:** the manual's form needs the `.BAS`
  extension (`'C:\UPL\USER\SNDFILE.BAS'`; the app note omits it), and even then COM2 emitted 6 zero
  bytes and stalled → DOS "write fault" on screen, cleared by SNDFILE's own 10 s port timeout.
  COM2 seems only set up for SNDFILE when it's the remote port. Moot now. Completion of a macro
  is signalled by **bit 14 (RUN) of `STAT:OPER:COND?`**, not `*OPC?`.

**The calibration is in disk files — and backed up.** File names came from `UPL_UI.EXE`'s strings;
they mirror the refused `DIAG:DEV` selectors (`CAGEn`→`AGEN.CAL`, `CANLr0`→`ANLR0.CAL`,
`CLDG`→`LDG.CAL`). In `results/CAL/` (git-ignored):
`C:\UPL\REF\` `AGEN.CAL` 100 · `ANLR0.CAL` 740 · `LDG.CAL` 366 · `DC_OUT.CAL` 174 · `DIG.CAL` 258 ·
`PS.CFG` · `TRCCOL.CFG` · `GL_PRO.LOG`; `C:\UPL\SETUP\` `CAL_DIG.SAC` 8657 · `CAL_LDG.SET` 84440 ·
`UPL.SET` 89800 · `DEFAULT.SET` 89800. `LDG_ER.CAL` / `DIG_ER.CAL` (firmware also references them)
don't exist — by name, error logs from a failed calibration.

**The disk (from the DIR listing):** 2 667 entries / 2 586 files / **39.9 MB**, **2.04 GB free** — so
**not the original 540 MB Hitachi**; replaced (CF or newer drive). **MS‑DOS 6**, volume serial
`544F-BF04`. `DOS\`, `UPL\`, `CONFIG.SYS`, `AUTOEXEC.BAT` dated **Feb 2022** — reinstalled by a
previous owner; R&S originals (`AUTOEXEC.UPL`, `CONFIG.UPL`, `CONFIG.IEC`…) keep 2000–01 dates.
Biggest dirs: `C:\CODED\AC3\48000\{20_192,51_448}` (~1000 files each, the B23 library),
`C:\DOS` 123, `C:\UPL\REF` 75, `C:\UPL\USER` 66. `C:\LOGDSP.TXT` grows at each UPL start.
**Full file-level backup DONE → `results/DISK/`** via `tools/upl_backup.py --dirlist`
(then named `gpib_backup.py`):
all 2 586 listed files, 2 583 at exactly the listed size; the other 3 are logs rewritten at UPL
start (`C:\LOGDSP.TXT`, `C:\UPL\LOGDSP.TXT`) and `DIRLIST.TXT` itself. `manifest.csv` has SHA‑256s.
Not a substitute for a raw image (no boot sector, no partition table), but every file.
**Integrity check:** the instrument's `C:\CODED` vs the original B23 `CODED.zip` on the PC —
**2 002 files in both, all byte-identical.** Disk and GPIB path both sound.
**B23 finding:** the single-channel sets (`AC3\48000\{C,L,R,LS,RS,LFE}`, 3 files each, 18 total)
are in the archive but those directories are **empty on the instrument** — so
`SOUR:COD:CHAN CHL|CHC|CHR|CHLS|CHRS|CHLF` has no data here; 2/0 (`20_192`) and 5.1 (`51_448`)
are complete. Copy the 18 files over if single-channel is ever needed. A stray `LOGDSP.TXT` in
`51_448\` suggests the UPL writes its log into the current directory.

### DCX2496 THD+N characterization, 2026‑09‑23 — "is it as bad as they say?"

Flat passthrough on output 1 (EQ off, crossover off, gain 0dB), B1 low-distortion generator,
`SENS1:FUNCtion 'THDN'`, external balanced path (`INP:TYPE BAL`, `INP:SEL CH2I`). Script:
`measurements/dcx_thdn.py` (ephemeral; reuses the `dcx2496`/`upl_capture` classes directly rather
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

Script: `measurements/dcx_gauntlet.py`. Output 1 only (still only 2 cables patched: UPL gen -> DCX
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

Script: `measurements/dcx_balanced_test.py <mode>`. UPL analyzer input is a single XLR jack (per
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

Replicated `SELFTEST_Program.TXT` (R&S factory selftest, user-supplied, one directory up from
this project — untouched, never modified) command-for-command via remote SCPI from this PC —
the front-panel version only shows pass/fail; this captures
every underlying number. **Permanent tool: `upl_selftest.py`** (in this project folder, alongside
`upl_capture.py`/`ser_in.py`/`audio_tests.py` — the original two prototype scripts lived only in the
ephemeral scratchpad and were superseded/discarded).

### Running it
```
python upl_selftest.py --port COM7                     # default baud 115200
python upl_selftest.py --port COM7 --baud 19200 --label slow   # slower, if 115200 misbehaves
```
- Prints every section live to the console AND writes a results folder,
  `results/selftest/<label>_<timestamp>/`: `report.html`, `report.txt` (the text report),
  `readings.csv`. (Before 2026‑09‑24 it wrote `upl_selftest_<timestamp>.txt` in the current
  folder; see "Results folders and reports" below.)
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
`*OPT?` = `B1(0.01),B29(2.16),B21,B22,B4,B5(1.62),B6,B10,B22,B23`. (**B21 is identified** —
UPL‑B21 = Digital Audio Protocol; see the note further down. This line previously said "not yet
identified". Note also that this transcription and the one in the SCPI-vocabulary section
differ — that one reads `…B6,0,B10,0,B23,0`, i.e. with empty slots. Re-read `*OPT?` once at the
next live session and keep whichever is literal.)

| Test | Result | Spec | Margin |
|---|---|---|---|
| Generator accuracy, 30mV–20V | −0.12% to −0.35% | ±1.6–2% | comfortable |
| B1 low-dist gen, level/freq, 150Hz–25kHz | ≤0.21% / ≤0.03% | 1.6–2.7% / 0.8% | wide |
| Analyzer ranges, 18mV–18V × {1k,40,15k}Hz + 30/60/100V ext (48 pts) | −0.06% to −0.42% | ±1.5–3.0% | wide |
| Inherent THD+N @1kHz/2V, A22 | −103.0 to −103.6 dB | ≤−93 dB | ~10 dB |
| THD+N −60dB linearity (2-tone) | −60.14/−60.17 dB | ±0.5 dB | good |
| Inherent THD+N @1kHz/2V, A100 | −97.7 to −97.9 dB | ≤−84 dB | ~14 dB |
| Inherent D2 (DFD) @10kHz/200Hz/2V | −120.5 to −131.3 dB | ≤−110 dB | wide |
| Inherent noise, A22 | 1.5–1.6 µV | ≤2 µV | tight-ish but PASS — normal for the model; a second unit reads 1.4/1.6 µV (see "Shared Drive archive") |
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

## `FLAT_GEN.BAS` — generator flatness calibration (decompiled 2026‑09‑23)

No loose copy exists on this PC. It lives only inside `DISK2/USER.LZH`
(`python tools/lzh_extract.py DISK2/USER.LZH FLAT_GEN.BAS`), and ships to `C:\UPL\USER\` on
the instrument. Runs as a UPL‑B10 macro (we have B10). Companion setup `FLAT_GEN.SAC` is in the
same archive.

**What it is for.** It creates or deletes `C:\UPL\REF\FLAT_GEN.CAL`, the **generator frequency‑
response equalization file**. Vol.1 §2.6.9: the analyzer already has an rms frequency‑response
calibration, but for measurements using the *internal* generator the combined residual
generator+analyzer response can be flattened further by this instrument‑specific file. The file's
mere presence at boot enables the correction; deleting/renaming it and restarting disables it.

**Program flow** (SCPI in caps, DOS shell-outs in lower case):
```
                                  ; does C:\UPL\REF\FLAT_GEN.CAL exist? -> menu E / D / A
Disable_flatness:
  del \upl\ref\flat_gen.cal       ; DOS shell, not MMEM:DEL -- the file is read at boot
  SOUR:FUNC SIN
Execute_flatness:
  del \upl\ref\flat_gen.cal                      ; if one was already there
  MMEM:STOR:STAT 2,'\upl\user\upl.tmp'           ; snapshot COMPLETE instrument state (.SCO)
  MMEM:LOAD:STAT 0,'\upl\user\flat_gen.sac'      ; load the calibration setup
  INIT:CONT OFF;*WAI                             ; run the calibration sweep ("several minutes")
  MMEM:STOR:LIST EQU,'\upl\ref\flat_gen.cal'     ; store the result as the equalization list
  SOUR:SWE:MODE AUTO;:SOUR:FREQ:MODE SWE1        ; then an A/B check:
  DISP:TRAC:COUN 2
  INIT:CONT OFF;*WAI                             ;   trace 1 = uncalibrated
  SOUR:FUNC SIN
  INIT:CONT OFF;*WAI                             ;   trace 2 = calibrated
                                  ; "Flatness okay? 'D' to disable, any other key to accept"
  MMEM:LOAD:STAT 2,'\upl\user\upl.tmp'           ; restore the caller's state
  MMEM:DEL '\upl\user\upl.tmp'
```

**Why this matters to our measurements.** Every DCX2496 / M51 frequency‑response sweep we run with
the UPL as generator inherits whatever state this is in, and we have never checked it.
**Worth doing at the next live session: `MMEM:CAT? 'C:\UPL\REF'` and look for `FLAT_GEN.CAL`.**
Two caveats straight from Vol.1 §2.6.9 before enabling it:
- The .cal contains the **inverted residual analyzer response as well as the generator's**. If the
  generator is driven into an *external* analyzer, R&S says the correction can make the pure
  generator response *worse* — don't use it for that.
- It slows generator frequency setting (both frequency and level must be set per point); R&S puts
  the hit at under 10 % on a sweep.
- Enabling/disabling by hand needs a **restart** to take effect. The macro handles this itself.

**Does it exercise the native sweep we were trying to get working remotely? Partly — checked, not
assumed.** Grepping the decompiled source for each subsystem:
```
SWE   : SOUR:SWE:MODE AUTO;:SOUR:FREQ:MODE SWE1      <- yes, exactly our config
INIT  : init:cont off;*wai   (x3)                    <- yes, our trigger
TRAC  : DISP:TRAC:COUN 2                             <- trace COUNT only
FEED  : -- none --                                   <- does NOT set DISP:TRAC:FEED
SENS  : -- none --
CALC  : -- none --
FORM  : -- none --
```
So it independently corroborates the **SWE1** half (and this is R&S's own shipped firmware, not an
app note — a third independent confirmation), but it is **silent on the FEED half**. It also never
reads a trace over the bus at all: it gets its result out with `MMEM:STOR:LIST EQU,'file'`. Its
measurement and display configuration comes from `flat_gen.sac`, and that is an opaque binary setup
blob — checked, it holds file references and encoded panel state, not readable SCPI — so it cannot
tell us whether FEED is set there either.

> **CORRECTION 2026‑09‑23 (same day):** this section originally went on to say FEED "remains the one
> piece of the fix with no corroborating usage anywhere." **That was wrong** — FLAT_GEN.BAS lacks it,
> but other programs have the complete pattern. See "FEED → sweep → readout confirmed end-to-end"
> below.

**Useful consequence:** it demonstrates R&S's own preferred way to configure a measurement —
`MMEM:LOAD:STAT 0,'<name>.SAC'` rather than sending every panel setting — plus a result path that
sidesteps trace readout entirely. If `DISP:TRAC:FEED` turns out not to be sufficient at the
instrument, `nsweep --setup <file.SAC>` followed by `storetrace` is a fallback built only from
commands now confirmed in shipped firmware. `--setup` was added to `nsweep` for exactly this.

**New/confirmed SCPI from this program:**
- `MMEM:STOR:LIST EQU,'file'` — store equalization list. Vol.2 §3.10.5.1.3 documents the family:
  `CALC:EQU:FEED TRACe1|TRACe2` (which trace the amplitude data comes from),
  `CALC:EQU:NORMfreq <Hz>` (frequency normalized to), `CALC:EQU:INVert ON|OFF` (store inverted or
  not), `MMEM:STOR:FORM BIN|ASCii`. Read back with `MMEM:LOAD:LIST EQUalize,'file'` and applied via
  `SOUR:VOLT:EQU:STAT`.
- **`MMEM:STOR:STAT 2,'file'` / `MMEM:LOAD:STAT 2,'file'` as a scratch state snapshot/restore** —
  mode 2 = *complete* instrument setup (.SCO), vs mode 0 = current setup (.SAC). This is a much
  better guardrail than our scripts' habit of opening with `*RST`, which discards whatever the user
  had set up. **Adopted 2026‑09‑23** as `preserve_state` in `upl_capture.py`, available on `nsweep`
  and `fft` via `--preserve` (+ `--state-file`). Note it *brackets* `*RST` rather than replacing it:
  a known state is still wanted inside the block, the snapshot is what puts the user's setup back
  afterwards. Opt-in, because it writes a scratch file to the instrument's disk and, like the rest
  of 2026‑09‑23's work, has not met hardware yet. Restore is best-effort so it can't mask a real
  measurement error. `seqcheck` asserts the snapshot is the first command, that `*RST` never
  precedes it, that restore follows the measurement, and that nothing is written without the flag.
- `DISP:TRAC:COUN 2` — number of displayed traces; pairs with the `DISP:TRAC:IND 0..17` trace
  selection used for FFT block paging.
- `SOUR:FUNC SIN`, `MMEM:DEL '<file>'`.
- `INIT:CONT OFF;*WAI` as the single-sweep trigger — a third independent confirmation, now also
  from R&S's own shipped firmware rather than an app note.

## Shared Drive archive (reviewed 2026‑09‑23)

Google Drive folder `1gu6kGuI8oiFmsxlREX8HwBPrEix0Lwos`, **owned by another UPL owner**
(bartvandekeere@gmail.com), shared with the user. Read through the Drive connector. Most of what
this project already uses came from here (app notes, operating manual, 3.06 firmware, B23 library,
UPA-CD). New material, by value:

| Item | Drive location | Why it matters |
|---|---|---|
| **Service Manual Vol.2** (28 MB) | Documents/Service Manual/UPL/Bart's Version | Circuit diagrams, component plans and parts lists for the Digital Board, Analog Unit, Power Supply, B1, B2, B5, plus B4/B10/B21/B22 install instructions. Answers the CPU-board history — see the CPU-longevity section. |
| **UPL‑B23 + UPZ datasheet** (v02.00, Jan 2004) | Documents/Option Manual | DTS support, special signals, UPZ switcher. Corrected the B23 entry above. |
| **Second unit's selftest report** | Documents/Selftest Program/SELFTEST.TXT | A reference baseline from another UPL — see below. |
| **Service Manual UPL‑B1** | same folder as Vol.2 | Install sheet + B1 calibration procedure (below), then schematics/parts. |
| `B10 - BASIC/Example.txt` | Software | Third-party (BVKSound 2020) B10 loop: set level → `INIT:CONT OFF;*WAI` → `MMEM:STOR:TRAC TR1A,'A:OutputN.TRC'`. A sixth confirmation of the store path, writing straight to the floppy/Gotek drive. |
| Photos: *CompactFlash Card*, *USB Floppy Emulator*, *PC Motherboard*, *ISA Interconnect Board* (incl. a `PCB Design.png`), *Digital Board*, *LCD Backlight* | Pictures | Someone's restoration log — an HDD→CF swap and a custom ISA interconnect PCB are directly relevant to the longevity plan. **Mostly HEIC; the connector returns no content for them.** Worth opening in a browser. |

Folders that came back **empty through the connector**: `Software/EEPROM/UPL_EEPROM/849260-020`,
`Documents/Calibration Documents`, `Software/DISK IMAGES`, `UPZ Switcher`, `Temporary`. Either empty
or holding file types the connector doesn't list — check in a browser before concluding either.
The EEPROM folder is worth that check: the digital board carries a **Xicor X24164 serial EEPROM**
(Service Manual Vol.2 parts list), a plausible home for per-board calibration.

**Deliberately not examined:** a top-level `Keygen` folder. This unit already has every option it
needs fitted (`*OPT?`), so there's no reason to go near an option-unlock tool.

### Second-unit selftest baseline (serial 828288/2, 2025‑01‑05)

Same R&S selftest, different UPL — the first outside reference we've had for our 121/121 result.
That unit has a different option mix (`B1, B2, B21, B22, B4, B5, B6, B8, B10, B33, B23, B9` — B2
where ours has B29, plus B8/B9/B33).

| Test | Ours (100330/6) | Theirs (828288/2) | Limit |
|---|---|---|---|
| Inherent THD+N @1 kHz/2 V, A22 | −103.0 to −103.6 dB | −104.25 / −104.34 dB | ≤ −93 |
| Inherent THD+N @1 kHz, A100 | −97.7 to −97.9 dB | −97.21 / −97.54 dB | ≤ −84 |
| THD+N at −60 dB | −60.14 / −60.17 | −60.09 / −60.09 | ±0.5 dB |
| Inherent D2 | −120.5 to −131.3 dB | −130.41 / −134.13 dB | ≤ −110 |
| **Inherent noise, A22** | **1.5–1.6 µV** | **1.4 / 1.6 µV** | ≤ 2 µV |
| Inherent noise, A100 | 4.3–5.2 µV | 6.1 / 4.8 µV | ≤ 8 µV |
| Generator accuracy | −0.12 to −0.35 % | +0.02 to +0.17 % | ±1.6–2 % |
| Analyzer ranges @1 kHz | −0.06 to −0.42 % | −0.11 to +0.24 % | ±1.5 % |

The useful conclusion: **our A22 inherent noise, previously noted as "tight-ish", is normal for the
model** — a second unit lands in the same place. It isn't evidence of ageing. The two units are
otherwise equivalent within ~1 dB. Ours reads consistently slightly *low* on generator and analyzer
level while theirs reads slightly high; at 5–10 % of the tolerance that's not meaningful, but it's a
number to watch across future selftests.

### UPL‑B1 low-distortion generator — how it works, and the community KiCad redraw (2026‑09‑23)

Sources: R&S *Service Manual UPL‑B1* (board **1031.2699**, drawn 1993, originally for the UPD —
title block says "UPD‑B1"), and **github.com/bvksound/UPL-B1**, a KiCad 9 re-creation by BVKSound
(the same person behind the shared Drive archive and the B23 repack). The repo carries an
identical copy of the R&S manual (same 2,098,935-byte file).

**How it works** (from R&S's drawings; KiCad part names in brackets):
- **Oscillator core — a two-integrator loop.** Integrator 2 (**N42, HA‑5221**) → `SIN`;
  Integrator 1 (**N32, HA‑5221**) → `COS`; a summing amplifier (**N35**) inverts and closes the
  loop. Two 90° integrators plus an inversion give 360°, so it oscillates at f = 1/(2πRC) — and
  because an integrator loop needs no amplitude-dependent gain element in the signal path, the
  sine is intrinsically very clean. Loop amplitude ≈ **2.7 V rms**, **10 Hz – 110 kHz**.
- **Frequency: decades by capacitor, fine by DAC.** Each integrator has JFET-switched (2N5432)
  feedback capacitors — **560 pF / 2.2 nF / 33 nF / 330 nF**, 1 % film on the critical ones — for
  four ranges: 110–22 kHz, 22–1.8 kHz, 1.8 kHz–185 Hz, 185–10 Hz. Within a range, a **DAC8143
  12‑bit multiplying DAC** (D40, D30) with a JFET-switched 0.1 % resistor network sets the
  integrator's effective input resistance. A third DAC8143 (**D32**, "FREQ TUNE", V = 1.0…0.0)
  feeds a scaled `COS` into the loop summing amp.
- **Both integrators are tuned by identical words — by wiring.** The serial data link branches:
  D21's output feeds Integrator 2's DAC+register (D40→D41, whose serial outputs are left
  unconnected) *and* Integrator 1's (D30→D31→D32→…) in parallel. Every frequency word lands in
  both at once, so the two integrators always match, keeping `SIN`/`COS` in exact quadrature.
- **Level control — sampled, not rectified.** A temperature-compensated **1N827 (−6.2 V)**
  reference is summed with `COS` (N51). **N52, an LM211**, squares `SIN`; **D50 (74HC132)**
  turns its edges into track-and-hold pulses (V505–V508). Two T&H stages (V504/C504/N53,
  V510/C511/N55) sample that sum, a regulator integrator (N54) filters it, and an **MC1595
  four-quadrant multiplier (D51, with N56)** feeds the correction back into the loop. My reading
  (inferred from the topology, not stated by R&S): `SIN`'s zero crossings are exactly `COS`'s
  peaks, so sampling there measures peak amplitude with **no rectifier ripple**, and holding the
  value between samples means the loop gain isn't modulated within a cycle. That's how the B1
  reaches the **−122 dB THD** measured on this unit (2026‑09‑22).
- **Output:** a fourth DAC8143 (**D22**, with **N20**) gives 0 … −20 dB, a relay (**K2**) switches
  the path, out to `LOW DIST` on X1A pin 16.
- **Board ID:** **D23 (74HC165)**, a parallel-in shift register at the end of the chain, read back
  on `SDO`. Probably how the UPL detects the option is fitted (the install sheet says it's
  recognized automatically).

**Is the KiCad PDF correct? Checked 2026‑09‑23 — no electrical errors found in what was checked:**
- **Parts:** the full R&S XY list (306 entries, pp.18–20, transcribed from the scans) against the
  KiCad sources (309 parts): **302 match by designator.** The rest are explained: R&S's X1A/C/D =
  KiCad's single X1; R543/C523 (N52 supply filter) and X50–X52 (3‑pin solder bridges on the
  ALC's COS, SIN and control lines) **are in R&S's drawing** but not its XY list — R543/C523 are
  numbered after the XY list's last entries, so likely a later R&S modification; the bridges are
  PCB features, not components. Unresolved: R&S `HVC` (listed on sheet 6) has no KiCad
  counterpart; KiCad `X4` (a 6‑pin power/ENABLE header) wasn't found in R&S's list — not checked
  against the drawing.
- **Block diagram:** same blocks, designators and signal flow, including the branched data link.
- **Integrator 2 sheet, in full:** every value, tolerance, part type and pin number matches.
- **The spot the KiCad author flagged** ("the bodge is documented dodgey"): matches R&S.
  R512 2K21 is the LM211's open-collector pull-up; R522 22R1 + C508 10 µF filter D50's supply.
- **Cosmetic only:** the block diagram's note says "C551" where R&S has **C511** (the part itself
  is right); LM339 unit letters differ (R&S N41‑A = KiCad N41C, etc.) but **pin numbers are
  identical**; one `/WR` net is deliberately renamed (noted on the sheet).
- **Not verified at value/wiring level:** Integrator 1 & loop inverter, the output attenuator,
  and most of the ALC sheet (designators checked, circuits not).
- The repo's **README** is fluent but imprecise against the schematics: it calls the
  integrator DACs "fine tuning" (they're the main in-range control, alongside D32), says the
  integrator RC networks are relay-switched (they're JFET-switched; the only relay, K2, is in the
  output stage), and describes the output attenuator as relay resistor networks (it's the D22
  DAC). Trust the schematics over the README.

### UPL‑B1 calibration procedure (from the B1 service manual install sheet)

OPTIONS panel → **CALIBRATION GEN LOW DIST → ONCE**; runs automatically, no external instruments
(level measured against the universal generator, frequency by the UPL's counter). Conditions:
**no cables on the generator outputs or analyzer inputs**, ambient **23 ± 5 °C**, warm-up **1 hour**.
Earlier notes in this file say "2 h warm-up" for the same calibration with no recorded source — 2 h
is the safe choice until one or the other is confirmed.

### UPZ Audio Switcher

Also in the B23 datasheet: R&S's **UPZ** switcher (8 channels, cascade to 128 in and 128 out),
controlled **from the UPL panel over RS‑232‑C** or directly by any controller. Only relevant if a
multichannel DUT (an AV receiver for B23 testing) turns up, but it's the intended companion to B23.

## UPA-CD Audio Test Disc + UPL‑B23 coded audio (added by user 2026‑09‑23)

Two archives dropped in the parent folder, both unpacked and analysed. Neither is in git — they're
large and not ours to redistribute (add to `.gitignore` if they ever move into this folder).

### UPA-CD (Audio Test Disc UPA‑CD 852.8400.02)

`UPA-CD-…zip`, 809 MB. Contains **47 tracks as bit-exact CD rips** (`Wav Files/NN - Name.wav`,
**44.1 kHz / 16‑bit / stereo**, RIFF PCM), a scanned 16‑page `Booklet.pdf`, and a 529 MB
`UPA-CD_Original.zip`. The booklet has **no text layer** — it's scans. Rendered and read with
`pypdfium2` (installed into this env; `pdftotext` returns nothing, and there's no `pdftoppm`).

Disc layout, from the booklet:

| Tracks | Group | Covers |
|---|---|---|
| 1–9 | CD player / DAT recorder | S/N, dynamic range, D/A linearity, freq response, distortion, phase, crosstalk, IMD, output impedance |
| 10–19 | Tape deck | S/N, wow & flutter, freq response, distortion vs level, crosstalk, IMD, output impedance |
| 20–26 | Amplifier | S/N, freq response, distortion, phase, crosstalk, IMD, output impedance |
| 27–31 | Automatic line test sequences | 5 self-contained stereo/mono sequences, each starting with a signalling burst |
| 32–47 | Various | multifrequency, 1/3‑oct + white + pink noise, polarity, difference tones, square waves, bursts, half-waves |

Tracks worth knowing by number (level in dBFS, all L+R unless noted):
- **1** 1 kHz @ 0 dB — reference level and pitch · **2** silence — S/N · **3** 1 kHz @ −60 — dynamic range
- **4** D/A linearity staircase, 2 kHz @ 0 alternating with 1 kHz at −20/−30/−40/−50/−60/−70/−80.1/
  −85.2/−89.5/**−91.2 dB** — the bottom of the 16‑bit range
- **5** 0.02–20 kHz sweep @ 0 dB, L then R (72 s each) — frequency response
- **6** distortion + phase, 20 Hz…20 kHz stepped @ 0 dB · **7** crosstalk · **8** IMD 400 Hz + 7 kHz 4:1
- **13/14/15** sweeps at −10 / −20 / −30 dB · **16** distortion vs level, 400 Hz at −30…0 dB
- **32** multifrequency: 52.5 Hz, 315 Hz, 3.15 kHz, 6.3 kHz, 10.08 kHz, 12.6 kHz, −12 dB each,
  sum level RMS −4.2 dB — one-shot frequency response
- **33** 1/3‑octave noise, 40 Hz…16 kHz @ −20 — loudspeaker measurement
- **34–37** white/pink noise, uncorrelated + correlated · **38** polarity (speakers) · **47** half-waves
  440 Hz (polarity, lines)
- **39/40/41** difference tones 9+11 k, 13+14 k, **19+20 kHz** · **42** SMPTE IMD 60 Hz + 7 kHz 4:1
- **43/44** square waves 100 Hz / 1 kHz — step response · **45** bursts 0.4–300 ms — volume indicator
- **46** 1 kHz tone-burst −40/0 dB — compressor test

**Booklet warning, worth repeating:** *"This CD must be used with utmost care to avoid destruction of
amplifiers or loudspeakers. Many tracks are recorded at much higher levels than conventional program
sources."* Several tracks sit at 0 dBFS.

**Track → UPL setup map**, read out of `CDTEST.BAS` (app note 1GA21, already extracted). The program
prompts "Select track N and press <play>" and loads a matching `.SAC`:

| Track | Setup loaded | Measurement |
|---|---|---|
| 1 | `CDA_BAS.SAC` | reference level (also the base setup, re-loaded between tests) |
| — | `CDA_SNR.SAC` | S/N (track 2, silence) |
| 3 | `CDA_DYN.SAC` | dynamic range |
| 4 | (linearity) | D/A linearity |
| 5 | `CDA_FREQ.SAC` | frequency response |
| 6 | `CDA_THDN.SAC` | THD+N |
| 7 | | crosstalk |
| 8, 15 | | IMD / sweep at −30 dB |
| 41 | | difference tone 19+20 kHz |
| 42 | | SMPTE IMD |
| 47 | | polarity |

The full `CDA_*.SAC` set (12 files) is in `appnotes/1GA21_1E/CDPlayer/`.

**Why this matters here: no CD player needed.** The tracks are plain 44.1/16 WAVs, so the existing
laptop→USB→M51 chain replays them directly, with the UPL as analyzer and the `CDA_*.SAC` setups
giving R&S's own measurement configuration. That turns 1GA21 into a runnable procedure for the M51
without owning the physical disc or a transport.

**Implemented as `measurements/upacd_test.py` (2026‑09‑23, not yet run against hardware).** Plays a
track from this PC into any DUT while the UPL measures. The DUT is whatever sits between the sound
device and the analyzer input, so `--device` alone switches between the M51, the DCX chain, and
**the laptop's own output** — the last being a better test of the laptop codec than `audio_tests.py`
can manage, since that measures with the laptop's own ADC.

Design notes worth keeping:
- **Segmentation is frequency-based, not time-based.** Track 4 delimits each level step with a 3 s
  2 kHz marker at 0 dBFS, so the script polls RMS + `SENS3:DATA?` continuously and groups the
  stream by measured frequency. No dependence on absolute timing across USB buffering. Median per
  run, not mean, so one settling reading inside a run cannot move it; runs shorter than
  `--min-samples` are discarded as transients.
- **The 0 dBFS reference comes from the markers themselves**, so the result is independent of the
  DUT's absolute gain and of the UPL's input range setting.
- Steps below the DUT's noise floor produce no frequency lock and simply drop out — reported as a
  warning, because that *is* the measurement.
- `linearity` refuses to run without `--exclusive` (override: `--allow-shared`). Shared-mode
  resampling would give a plausible-looking but meaningless −91 dBFS number; better to refuse.
- Tracks are read straight out of the 809 MB zip, nothing unpacked.
- Offline-tested: settling samples dropped, ±3 % frequency jitter tolerated, short transients
  rejected, outlier-inside-a-run ignored, below-noise-floor steps dropping out, and a deliberate
  +0.40 dB error injected at −91.2 dB recovered exactly.

Cross-check that the rip matches the booklet: track 4 is 22.9 MB = 130 s at 44.1/16/stereo, and the
booklet's last step starts at 02:00 and runs 10 s. Consistent.

### UPL‑B23 "Coded Audio Signal Generation"

`UPL-B23 - …zip`, 15 MB: three floppy images + their extracted contents + `CODED.zip` (2030 files).
`README.B23` is original R&S; the `B23INST.BAT` files are a 2022 third-party repack ("BVKSound"),
not R&S's own installer — worth knowing before trusting them.

**What the data is.** Verified by parsing the WAV headers: 48 kHz / 16‑bit / stereo PCM containers
whose payload begins `72 f8 1f 4e` — **IEC 61937 burst preamble** (Pa=0xF872, Pb=0x4E1F), Pc=1
(AC‑3), followed by the AC‑3 sync word `0B77` byte-swapped. So these are Dolby Digital bitstreams
packed for S/PDIF, not audio.

**Filename convention** (decoded, then confirmed against the manual): `FFFFFLLL.WAV` = frequency in
Hz + level in dB below FS. `00042020.WAV` = 41.7 Hz at −20 dBFS.

**Structure, and why it's shaped that way** — file length is always a whole number of AC‑3 frames
(1536 samples), chosen so the tone loops seamlessly, which sets the frequency resolution:

| Band | Resolution | Frames/file | Samples |
|---|---|---|---|
| 5 Hz – 1 kHz | 5.21 Hz | 6 | 9216 |
| 1 – 3 kHz | 10.42 Hz | 3 | 4608 |
| 3 – 20 kHz | 31.25 Hz | 1 | 1536 |

(31.25 Hz is exactly the AC‑3 frame rate, 48000/1536.) Counted in `20_192/`: **928 files across the
full frequency grid, all at −20 dBFS** (the frequency-sweep set) plus **3 frequencies × 25 levels**
(0 to −120 dBFS in 5 dB steps — the level-sweep set) = 1000 files. That matches the manual exactly:
frequency variation and level variation are **mutually exclusive**, chosen by Vari Mode.

**SCPI (Vol.2 §3.10.1.5.14, p.3.93–3.95).** Preconditions — all must hold or the function is
unavailable: `INST D48` (digital generator), `SENS:DIG:FEED ADAT`, `OUTP:SAMP:MODE F48`.
```
SOUR:FUNC CODedaud
SOUR:COD:FORM AC3                       ; manual lists only AC3; the 2004 datasheet adds DTS, but
                                        ; our library has AC-3 files only, and the DTS parameter
                                        ; name is undocumented here -- don't guess it
SOUR:COD:CHAN CH2 | CH6                 ; 2/0 @192 kb/s | 5.1 @448 kb/s -- freq AND level variable
SOUR:COD:CHAN CHL|CHC|CHR|CHLS|CHRS|CHLF ; single channel @448 kb/s: 3 freqs only, fixed -20 dB
; frequency variation:
SOUR:FREQ:MODE FIX ; SOUR:FREQ <5.21 Hz..20 kHz>      ; level pinned at -20 dB
; level variation:
SOUR:VOLT:MODE FIX ; SOUR:COD:FREQ F042|F997|F15K     ; exactly 41.7 / 994.8 / 15000.0 Hz
SOUR:VOLT:TOT <0..-120 dBFS>
```
Off-grid frequency and level values are snapped to the nearest available file. Both are sweepable
with the ordinary generator sweep commands — so `nsweep` should drive this once it's verified.

**Open item — path discrepancy.** Vol.2 says the firmware counts WAV files in
`C:\UPL\AC3\48000\...`; `README.B23` and the installer both use **`C:\CODED\AC3\48000\`**. If the
files aren't where the firmware looks, frequency selection silently collapses to whatever it finds.
**Check on the instrument: `MMEM:CAT? 'C:\CODED\AC3\48000'` and `MMEM:CAT? 'C:\UPL\AC3\48000'`.**
B23 is fitted (`*OPT?` lists B23) but that says nothing about whether the data library was ever
installed.

### Bonus: the ARBITRARY generator eats WAV files

Vol.1 §2.5.4.10 — `SOUR:FUNC ARB` + `MMEM:LOAD:LIST ARBitrary,'<file>'` accepts five formats:
TTF and AWD (ASCII/designer output, max 16384 samples), **WAV (8- or 16-bit, _any length_;
16‑bit needs model 06/66, i.e. a Pentium CPU — ours is a ~300 MHz MediaGX, 586-class and the
later generation, so very likely yes**. The manual states the requirement by *model number*
rather than CPU, so the model plate is the definitive check. (An earlier version of this line
asserted Pentium-class from the firmware's supported-board list alone; the user has since
identified the CPU.) CPR
(compressed, for 486-era units), and **ACC — "a special compressed waveform format for WAV files
containing AC3 or MPEG data coded in line with IEC 61937", digital generator only.**

So there are two routes to coded audio: the structured B23 library, or an ACC-converted IEC 61937
WAV through ARBITRARY. And UPA-CD tracks could in principle be played from the UPL's own generator
as ARB WAVs — but note analog output requires 48 kHz (the tracks are 44.1) and a 3–30 MB track
would take ~45 min to push over RS232 at 115 kbaud. **Replaying from the laptop is the practical
path; ARB is for short custom waveforms.**

## Full BASIC-source sweep, 2026‑09‑23 — every `.BAS` in every archive

Inventory of all BASIC sources anywhere in this project (firmware `.LZH` + app-note self-extracting
ZIPs + their nested `.LZH`s), so nobody re-derives this list:

| Archive | Files | Status |
|---|---|---|
| `DISK2/IEC_EXAM.LZH` | `EXAM1‑7.BAS`, `RS232_BT.BAS` | digested 2026‑09‑22 |
| `DISK2/B10_EXAM.LZH` | `EXAM1‑7.BAS` | **nothing new** — byte-for-byte the same SCPI as IEC_EXAM, minus the `syst:err?` calls. Only `UPL OUT` vs `IEC OUT` differs. |
| `DISK2/DEMOEXAM.LZH` | `DEMO.BAS` (11.5 KB) | **new, productive** — see below |
| `DISK2/USER.LZH` | `SNDFILE`, `DRV_INST`, `FLAT_GEN`, `IMPEDANC`, `SELFTEST` | all digested |
| `DISK1/*.LZH` | — | no BASIC at all (drivers, refs, tools) |
| App notes 1ga16/1GA21/1GA24/1GA30/1GA33 | `SOUND`, `IMPEDANC`, `PHASE`, `THD`, `SPK_LIB`, `UTILITY`, `APPLICAT`, `SPEAKER`, `CDTEST`, `TUNTEST`, `SETUP`, `Adctest`, `LIMIT` | digested 2026‑09‑23 |
| `FM Tuner Test Program/TUNER.LZH` | `TUNER.BAS` (25.6 KB), `FASTDIST`, `MULTFREQ` | **new** — see below |
| `1ga36_1l.exe → MAKEDISK.LZH` | — | no BASIC (setup files only) |

### FEED → sweep → readout, confirmed end-to-end

`appnotes/1ga16_1l/SOUND.ASC` lines 20565‑20640 is our exact `nsweep` sequence, in R&S's own code:
```
DISP:TRAC:OPER CURV
DISP:TRAC:FEED 'SENS:DATA2'          <- the FEED
DISP:TRAC:X:AUTO OFF / :LEFT / :RIGH
DISP:CONF SP
INIT:CONT OFF; *wai                  <- single-sweep trigger
TRAC:POIN? TRAC1                     <- point count, used to DIM the arrays
TRAC? LIST1                          <- X axis
TRAC? TRAC1                          <- Y values
```
`DISP:TRAC:FEED` is used by **six** programs in total (`SOUND`, `PHASE`, `THD`, `CDTEST`, `TUNTEST`,
`Adctest`, plus `DEMO.BAS` and `TUNER.BAS` in the HOLD sense). The FEED half of the native-sweep fix
is therefore as well corroborated as the SWE1 half — it was only *FLAT_GEN.BAS* that was silent on it.

Also useful for bring-up: **`DISP:TRAC2:FEED?` is queryable**, and SOUND.ASC compares its reply
against the string `'SENS:DATA'` — i.e. the reply comes back *with the quotes included*. Worth
knowing before parsing it in the bring-up diagnostic.

### `DEMO.BAS` (shipped firmware) — resolves the UFILter routing question

**`SENS:FILT:UFIL1 ON` confirmed in shipped firmware**, in exactly the sequence the earlier
open question predicted:
```
SENS:FILT OFF                  ; clear the filter slots
SENS:UFIL:PASS:LOW 3 KHZ       ; define the user filter's passband
SENS:UFIL:PASS:UPP 4 KHZ
SENS:FILT:UFIL1 ON             ; <- ROUTE it into the measurement chain
```
This closes the `SENSe:FILTer<i>` item recorded under "SCPI vocabulary confirmed present": defining
a user filter does **not** engage it; assigning it to a filter slot does. That explains why the
2026‑09‑22 live test saw THD+N barely move after `SENS1:UFILter1:LPASs ON` + `PASSb 22000`.

Working **zoom-FFT** example, also from DEMO.BAS — note the order, ZOOM *then* CENT (`cmd_fft` was
changed to match):
```
CALC:TRAN:FREQ:ZOOM 8
CALC:TRAN:FREQ:CENT 5000 HZ
CALC:TRAN:FREQ:AVER 2
DISP:TRAC:X:LEFT 4.9 KHZ ; DISP:TRAC:X:RIGH 5.1 KHZ
```
Other finds: `DISP:ACT OFF` / `ON` (**deactivate display updates for measurement speed** — also used
by CDTEST and TUNER.BAS; worth trying in our sweep loops), `SENS:FUNC 'WAV'`, `SENS:FUNC:MMOD
STAN|DODD`, `MMEM:LOAD:LIST EQU,'file'` (the read side of FLAT_GEN's store), `MMEM:LOAD:PAC` for
AES3 protocol config, and `MMEM:LOAD:STAT 4,'x.PCX'` to throw an image on the screen.

### `TUNER.BAS` — trace-store and cursor readout

- **`MMEM:STOR:FORM EXP`** — the short form works (we send `EXPort`); plus `MMEM:STOR:TRAC TRAC,'…'`
  and `TR1A,'…'` again, now a fifth independent confirmation of the store path.
- `DISP:ACT OFF;:DISP:TRAC:FEED 'HOLD';:DISP:TRAC2:FEED 'SENS:DATA'` — freeze trace A as a
  reference while trace B keeps measuring live. Clean idiom for before/after comparisons.
- **Cursor readout as a cheap alternative to pulling a whole trace:**
  `DISP:TRAC:CURS:POS:MODE MAX1` (or `MIN1`, `IMAX1`, `VAL`) then `DISP:TRAC:CURS:DATA?` /
  `:DATA2?` returns just that point. For peak-finding (the jitter scripts, resonance hunting) this
  is far less wire traffic than `TRAC?` + argmax on the host. Also `DISP:TRAC:CURS:MODE N12`,
  `DISP:TRAC:X:LEFT?/:RIGH?`, `DISP:TRAC:Y:TOP?/:BOTT?`, `DISP:TRAC:Y:RLEV:MODE REF1000`.

## Application Notes catalog (digested 2026‑09‑22)

Folder: `Application Notes/` (one dir up from this project, alongside the manuals). 14 PDFs +
bundled DOS example programs. Most PDFs are usage/install docs for their bundled compiled `.exe`
programs (source not printed in the PDF), so SCPI yield from text-grepping them was modest —
cataloged here by topic so they're easy to pull up again if a specific need matches:

**CORRECTION 2026‑09‑23 — the app-note `.exe` files are self-extracting ZIPs, and they contain the
full BASIC source.** `unzip` opens them directly (the ones that don't are plain DOS binaries):
```
unzip -o "Application Notes/1ga16_1l_.../1ga16_1l.exe" -d out/     # SPEAKER/SOUND/IMPEDANC/PHASE/THD .BAS + .ASC
unzip -o "Application Notes/1GA21_1E_.../1GA21_1E.exe" -d out/     # CDPlayer/CDTEST.BAS + 12 .SAC setups
unzip -o "Application Notes/1GA24_1E_.../1GA24_1E.exe" -d out/     # Tuner/TUNTEST.BAS, SETUP.BAS + .SAC
unzip -o "Application Notes/1GA30_0E_.../1GA30_0E.exe" -d out/     # Adctest.bas + Ad_*.sac
unzip -o "Application Notes/1GA33_1L_.../1ga33_1l.exe" -d out/     # LIMIT.BAS
```
`.ASC` = plain-text BASIC listing; `.BAS` = tokenized (still ~90% readable — map non-printable
bytes to newlines in Python to dump the string literals). This is by far the richest confirmed-SCPI
source in the whole folder — **richer than the PDFs** — because it's working code R&S shipped.
It's what resolved `MMEM:STOR:TRAC`, `DISP:TRAC:FEED` and the SWE1/SWE2 question above.
`1ga16_1l.exe` (loudspeaker) is the most useful single file: complete sweep setup, trace readout,
trace-to-file store, limit checking, cursor readout, reference curves.
Two other archives nest further: `1ga36_1l.exe` → `MAKEDISK.LZH` (+ `LHA.EXE`), and
`FM Tuner Test Program/TUNER.LZH` — both LZH, same format as `DISK2/*.LZH`.

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
`R&S_UPL_Audio_Analyzer_Op_Vol_1.pdf` and `..._Vol_2.pdf`.
**Vol 2 = the IEC‑bus/remote SCPI command reference** — use it to verify command syntax instead
of blind live probing. Working directory was moved up to that parent folder
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
