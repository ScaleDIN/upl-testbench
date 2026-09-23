# SERPA and PERIF2 — functional reverse engineering (first pass, 2026‑09‑23)

Black-box model of the two R&S custom chips on the **Digital Board 1078.2708**, from:

- **[S]** the Service Manual Vol. 2 schematics (Drive: *Service Manual/UPL/Bart's Version/
  R&S_UPL_Audio_Analyzer_Serv_Vol_2.pdf.pdf*, PDF pages 11–40 = Digital Unit sheets 1–18);
- **[S2]** the separate schematic set *Schaltplan_ocr.pdf* (Drive folder `1EirqBKxammtfQwbRM_yZUtozm_zU9UU6`),
  an earlier revision of the same board (plotted 27.10.95, 18 sheets). Its PDF page 17 is
  **"KEYBOARD DECODER", the PERIF2 sheet**, which is missing from the Vol. 2 scan. Its page 1
  has the front-panel connectors;
- **[F]** disassembly of `DISK1/UPL.LZH → UPL_UI.EXE` (v3.06) and `TOOLS.LZH → CONTRAST.EXE`;
- **[P]** the user's board photo (chip markings);
- **[I]** marks an inference that neither source states outright.

Both chips are mask-programmed gate arrays. This describes **what they do at their pins and
registers**, not their gates. It is enough to write an emulator, to design an FPGA/CPLD
replacement, or to probe a live unit safely. It is not a netlist.

File offsets like `0x25e06` are offsets into `UPL_UI.EXE`, the numbering capstone uses
(`image offset + 0x9200` header).

---

## 1. Identification

| | SERPA | PERIF2 |
|---|---|---|
| Marking [P] | VLSI Technology · `VY17136-2` · `R&S SERPA 1030.8570` · date 9701 | LSI Logic · `L5A8612` · `R&S PERIF2 0009.0432` · `NNI 9727` · Korea |
| Schematic part no. [S] | `SERPA 8002-7106` (the OCR's "-713"/"-716" were misreads of this) | `L5A8612 PERIF2`, ref **D24** [S2] |
| Package | 68-pin PLCC (VDD 1,18,35,53,62 · GND 9,17,27,36,52,61,68) [S] | 68-pin PLCC (VDD 17,36,53,68 · GND 1,18,35,52) [S2] |
| Instances | **4**: D1, D39, D40, D41 [S] | 1 (D24) |

**Correction to `CLAUDE.md`:** there are four SERPAs, not "D1–D5", and all four are the same
part, 8002-7106. The chip in the photo, next to silkscreen *D1*, is the ISA host interface.

---

## 2. SERPA = "SERial ↔ PArallel" bridge (confirmed by the pinout)

One die with **two bus personalities selected by pin 45 `MODE`**:

- **ISA mode** (MODE tied to GND): a 16-bit ISA I/O slave.
- **DSP mode**: a 32-bit TMS320C3x bus slave.

The serial side is the same in both modes: two transmit channels, two receive channels, and a
shared bit clock. It matches the TMS320C3x serial-port format (CLKX/FSX/DX, CLKR/FSR/DR).

### 2.1 Pinout (PLCC-68) [S — identical on all four instances]

| Pin | DSP-mode name | ISA-mode use (D1) |
|---|---|---|
| 39,38,37,34,33,32,31,30,29,28,26,25,24,23,22,21 | D0–D15 | ISA data (via 74HCT245 D2/D3 → ID-bus ID0–15) |
| 20 | D16 | **SA1** (selects the 16-bit half of a 32-bit register) |
| 19 | D17 | **DI** ← IAIDI (serial config bus, data in) |
| 16 | D18 | **DACK** ← DACK6 |
| 15 | D19 | **CLOCK** → IAICLK (serial config bus clock) |
| 14 | D20 | **DO** → IAIDO |
| 13 | D21 | **WRITE** → IAIWR |
| 12 | D22 | **READ** → IAIRD |
| 11 | D23 | **WR1EX** → EXCSW1 (external write strobe 1) |
| 10 | D24 | **RD1EX** → EXCSR1 (external read strobe 1) |
| 8 | D25 | **WR0EX** → IWR0 (external write strobe 0) |
| 7 | D26 | **RD0EX** → RDOEX (external read strobe 0) |
| 6 | D27 | **INT0** ↔ SDA (I²C data sense) [S, as drawn] |
| 5 | D28 | **INT1** ← GINT |
| 4 | D29 | **INT2** ← PERIF_INT (PERIF2's interrupt comes in here) |
| 3 | D30 | **XIO** → OUTEN (output enable of the control-register latches) |
| 2 | D31 | **DIR** → direction of the ISA data transceivers |
| 43 / 42 / 41 | WR (R/W) / STRB / CS | IOWR / IORD / CS |
| 67 / 66 / 65 | DA0 / DA1 / DA2 | **wired to SA11 / SA12 / SA13** (pin labels say SA2–4; the wiring says 11–13) |
| 59 / 57 | CLKX / LR | bit-clock out → CLKR of both DSPs / word clock |
| 64 / 60 | DX0 / FSX0 | → DSP-A serial RX (ADR0/AFSR0) |
| 63 / 58 | DX1 / FSX1 | → DSP-B serial RX (BDR0/BFSR0) |
| 51 / 49 / 50 | CLKR0 / FSR0 / DR0 | ← DSP-A serial TX (ACLKX0/AFSX0/ADX0) |
| 48 / 46 / 47 | CLKR1 / FSR1 / DR1 | ← DSP-B serial TX (BCLKX0/BFSX0/BDX0) |
| 56 / 55 / 54 | FREQ1 / FREQ2 / FREQ3 | **clock inputs**, not outputs: on D1, **FREQ2 ← ISA OSC (14.318 MHz)**; unconnected on D39/D40/D41, which take their bit clock from the serial side. [I: word 3 low bits pick the clock source/divider] |
| 44 | INT | → ISA **IRQ10** and **DRQ6** (via 74HCT125 D7-B/C), plus ATINT |
| 45 | MODE | **GND on D1** (ISA mode) |
| 40 | RESET | ← RESETDRV (D1) / ARESET or BRESET (DSP-side) |

### 2.2 Where the four SERPAs sit [S]

| Ref | Sheet | Bus side | Address | Serial side |
|---|---|---|---|---|
| **D1** | 16 AT_INTERFACE | ISA | I/O **390h** (74HCT688 strap compares SA2–SA9) | Host ↔ serial port 0 of **both** DSPs (boot load and command/data link); IAI config bus; external register strobes |
| **D39** "GEN_SERPA" | 15 DSP | DSP-A bus | DSP-A **C00008–C0000F** (I/O) | Generator output: GLR/GDATA, TX1DATA; receives BLFS/BLDATA from DSP-B |
| **D41** "ANA_SERPA" | 15 DSP | DSP-A bus | DSP-A **C00000–C00007** ("LINK") | Analyzer input: ASCLK/ALR/ASDATA, digital RX0/RX1; B5 link out; LINKDATA/LINKFS to DSP-B |
| **D40** "DSP-B SERPA" | 14 DSP | DSP-B bus | DSP-B **A00000** ("LINK", BCS1) | LINKFS/LINKDATA in, BLDATA/BLFS out, UFS in (UFSCLK/UFSTRT/UFSDATA); clock ICLOCK |

So the digital audio path is: ADC or digital receiver → ANA-SERPA (D41) → DSP-A → link →
DSP-B SERPA (D40) → DSP-B (FFT) → link back → GEN-SERPA (D39) → DAC or digital transmitter.
The host PC talks to both DSPs through D1.

### 2.3 ISA-mode register map (D1, base 390h) — [F] unless noted

Register *n* sits at **`0x390 + 0x800·n`** (low word) and **`+2`** (high word, SA1=1).
Addresses 390h–39Fh alias. PERIF2 has the same layout at `0x4390` (SA14=1) [S+F]. All
accesses use Borland `inport`/`outport` (16-bit) at image offsets `0x210b`/`0x2410`. The
firmware keeps a RAM shadow of every write-only register, in data segment `0x2E75`.

| n | Port | R/W | Meaning | Evidence |
|---|---|---|---|---|
| 0 | `0x0390` / `0x0392` | R/W | **32-bit data word to/from DSP-A** serial channel 0 (write low then high; read low then high) | `0x261ad`, `0x26201`: `si=0` → 0x390/0x392 |
| 1 | `0x0B90` / `0x0B92` | R/W | **32-bit data word to/from DSP-B** serial channel 1 | same functions, `si=1` |
| 2 | `0x1390` | W | Channel/interrupt/DMA control (shadow `[8]`/`[9]`). Low byte: **bit 2 = RX0 (DSP-A) enable, bit 3 = RX1 (DSP-B) enable, bit 5 = DMA source (0 = DSP-A, 1 = DSP-B)**. High byte bits 0–2: interrupt enables, saved and cleared for the duration of a DMA transfer, then restored. Written 0 before unhooking the IRQ. | `0x262cc`, `0x26c96` |
| 2 | `0x1390` | R | **Status**: bit 0 = DSP-A word ready, bit 1 = DSP-B word ready, bit 4 = ready/done (polled with timeout) | `0x26293`, `0x263d2`, `0x25ea9` |
| 3 | `0x1B90` | W | IAI serial-config-bus setup (shadow `[0xa]`; bits 0–2 = 1, bit 3, bits 4–5 = mode) [I: clock/format] | `0x26806` |
| 3 | `0x1B92` | R/W | **IAI serial config bus data** — shifts a word to or from the board picked by SERSEL (AES / B5 / ANA / GEN) | `0x26a8d` (after `0x25fab` selects the target) |
| 4 | `0x2390` | W | Serial format, TX (shadow `[0xc]`): bits 1:0 = word length/8 − 1 (8/16/24/32 bits) | `0x266e8(8,…)` |
| 4 | `0x2392` | W | **Interrupt acknowledge** (the IRQ10 ISR writes 0, then EOIs both 8259s) | ISR at `0x25e61` |
| 5 | `0x2B92` | W | **External control register** (two 74HCT574 via WR0EX; see §2.4) | ~20 writers, shadow `[0xe]` |
| 5 | `0x2B92` | R | **External status mux** (74HCT245 D8 via RD0EX; see §2.5) | `0x260ce`, `0x26a07`, `0x26a48` |
| 6 | `0x3390` | W | Serial format, RX0 (shadow `[0x10]`): bits 1:0 word length; bits 9:5 frame length − 1 (or − 2 when bit 4 = 1); bit 11 = special mode (forces `0x3A0`) | `0x266e8(0xc,…)`, `0x26768` |
| 6 | `0x3392` | R/W | **Setup-RAM data port** (EXCSR1/EXCSW1 → battery-backed SRAM with auto-increment address counter; see §2.6) | `0x2642b…0x266a4` |
| 7 | `0x3B90` | W | Serial format, RX1 (shadow `[0x12]`), same layout as reg 6 | `0x266e8(0xe,…)` |
| 7 | `0x3B92` | W | Misc control (shadow `[0x14]`, bit 1 set during init) | `0x26852` |

Interrupts: SERPA INT (pin 44) → **IRQ10** (vector `0x72`, hooked at `0x25c37`/`0x26c88`).
PERIF2's interrupt reaches the PC *through* SERPA's INT2 input, so both chips share IRQ10.

### 2.4 External control register, write `0x2B92` [S sheet 17 + F]

| Bit | Signal | Function |
|---|---|---|
| 0 | SCL | I²C clock to the **X24164 EEPROM** (bit-banged) |
| 1 | SDA out | I²C data out (via 74HCT125 D7-D) |
| 2 | SDA drive enable | 1 = release SDA (so it can be read back on status bit 7) |
| 3 | BOOT | DSP boot-mode select (with 74HCT02 D6-D → BOOT/`BOOT̄`) |
| 4 | BRESET | DSP-B reset |
| 5 | ARESET | DSP-A reset |
| 6 | CNTRAM | Load the setup-RAM address counter from the next data write |
| 7 | SELCH | Channel select [I: analyzer input channel] |
| 8–9 | SERSEL0/1 | Target of the IAI config bus (74HCT138 D9 → AES / B5 / ANA / GEN strobes) |
| 10 | SADR16 | Setup-RAM address bit 16 (only matters for the unfitted 128K×8 SRAMs) |
| 11 | SELICLK | Input-clock mux (74ACT257 D49 → ICLOCK: analog ASCLK vs digital RXCLK) |
| 12 | SELOCLK | Output-clock mux (74ACT257 D76: GBCLK vs TXCLK) |
| 13–14 | — | Pulled up to the unfitted header X40 (spare) |
| 15 | WREN_U | Write-enable/unlock (routed via 74ACT257 D76 → WREN) |

Firmware default in the shadow is `0x0030`, i.e. ARESET and BRESET high at start-up.

### 2.5 External status mux, read `0x2B92` [S sheet 17]

| Bit | Source |
|---|---|
| 0 | GND |
| 1 | Jumper X40-7 (pull-up) |
| 2 | **KEYVERS** — front-panel keyboard version strap |
| 3 | **AESTEST** — AES/digital option board present (pull-up; the board pulls it low) [I] |
| 4 | **KNOBAX** — rotary-knob variant (also on X40-5) |
| 5 | **ATEST** — analyzer board present [I] |
| 6 | GINT — generator-board interrupt/status line |
| 7 | **SDA** (I²C read-back) |

### 2.6 Setup RAM (another per-unit data store) [S sheet 18 + F]

Two **TC55257 32K×8 SRAMs** (D13/D14) form a 32K×16 RAM, reached only through register
`0x3392`. The address comes from four 74HCT191 counters (D17–D20). They load from the data bus
when CNTRAM (control bit 6) is set, and **auto-increment** on every access. Routine `0x25e06`
sets CNTRAM, writes the start address to `0x3392`, then clears CNTRAM. After that, successive
reads and writes of `0x3392` stream data. Records carry an **XOR checksum**: see the
`xor [bp-2],ax` chains at `0x2642b` and `0x264e1`.

The RAM is powered from **VRAM**: a BC858/BC868 switch (V1/V2) plus a **3.4 V battery G2**,
with a warning on the sheet not to short C161. So **this RAM holds per-unit state across power
cycles**, most likely the saved instrument setup. `CLAUDE.md` currently says the X24164 is
"the only chip with unique per-unit data". That is true for calibration, but this battery-backed
setup RAM is a second store, and its battery is a wear item.

### 2.7 DSP-mode side (D39/D40/D41)

In DSP mode the register file appears as **8 consecutive 32-bit words** (DA0–2 = DSP A0–A2).
It is **the same register file as the host side**: host register *n* at `0x390 + 0x800·n`
corresponds to DSP word *n*. The ISA front-end only adds the SA1 low/high split and uses the
spare register 5 for the external strobes.

Source: TMS320C3x disassembly of `DSP.LZH → A.OUT` (DSP-A; TI COFF with 319 symbols, including
the equate **`S_ANA_BASE = 0xC00000`**) and `B.OUT` (DSP-B; no symbols, but it has a pointer
table listing `0xA00000–0xA00007`, skipping 5). Neither disassembler ships in Python, so a
small decoder was written for this (general-format ops, direct/indirect/immediate addressing,
tracking DP). The DSPs reach SERPA through an address register loaded from a pointer constant,
then `*+AR6(n)`.

| Word | R/W | Meaning | Evidence |
|---|---|---|---|
| 0 | W | **TX channel 0 data** (→ DX0/FSX0) | GEN mode 1 patches its ISR to `STI R0,*+AR6(8)` (GEN base + 0) |
| 0 | R | **RX channel 0 data** (← DR0) | `ANA_IN` / `ANA_IN_RESET` flush reads |
| 1 | W | **TX channel 1 data** (→ DX1/FSX1) | GEN mode 2 → `*+AR6(9)`; the `B5_TEST` ISR writes word 1 |
| 1 | R | **RX channel 1 data** (← DR1) | ANA mode 3; DSP-B reads |
| 2 | W | **Channel enable**: bit 0 = TX0, bit 1 = TX1, bit 2 = RX0, bit 3 = RX1 | GEN writes 1 or 2; ANA writes 6 or `0xA`; DSP-B writes 4 or 8; 0 = all off |
| 2 | R | **Ready status**, same bit layout | the `B5_TEST` ISR tests `word2 & 2` before writing word 1 |
| 3 | W | Clock/mode setup: **always 2** from the DSPs | all three DSP-side SERPAs at start-up |
| 4 | W | **TX format**: bits 1:0 = word length/8 − 1 (host code `0x266e8` uses the same rule); bits 2/3 track which TX channel is active [I] | GEN `0x47` (TX0) / `0x4B` (TX1); ANA `0x247`; DSP-B `0x47` |
| 5 | — | never touched by the DSPs | pointer table in B.OUT skips it |
| 6 | W | **RX0 format**: bits 1:0 = word length; bits 9:5 = bit-count field (see §2.3) | ANA `0x3F3` / `0x3B3`; DSP-B `0x1E9` (16-bit words) |
| 7 | W | **RX1 format** | ANA `0x3B3`; DSP-B `0x3C3` |

Address confirmation: `STARTUP_GEN` uses the **same** `0xC00000` pointer with offsets 8–12, so
GEN-SERPA (D39) sits at `0xC00008` and ANA-SERPA (D41) at `0xC00000`, exactly as the address
decoder on sheet 12 says. DSP-B's SERPA (D40) is at `0xA00000`.

Programmed values, by instance:

| Instance | w2 (enable) | w3 | w4 (TX fmt) | w6 (RX0 fmt) | w7 (RX1 fmt) |
|---|---|---|---|---|---|
| D41 ANA-SERPA (`STARTUP_ANA`) | 0 → 6 or `0xA` when running | 2 | `0x247` | `0x3F3` / `0x3B3` by input mode | `0x3B3` |
| D39 GEN-SERPA (`STARTUP_GEN`, `GEN_OUT`) | 0 → 1 (analog out) or 2 (digital TX1) | 2 | `0x47` / `0x4B` | — | — |
| D40 DSP-B SERPA (B.OUT `0x25c6`) | 4 or 8 | 2 | `0x47` | `0x1E9` | `0x3C3` |

The remaining unknowns are the exact meaning of the word 3 and word 4 upper bits, and the RX
"bit-count" field (0x3F3 doesn't decode cleanly under the host-side formula). These only matter
for a gate-exact replacement. A logic analyser on FSX/FSR while switching modes would settle them.

### 2.8 DMA — bulk DSP → PC transfers [F + S]

SERPA D1 drives **DRQ6/DACK6**, and the firmware uses **only ISA DMA channel 6**. The
channel-5 branch of the driver exists but is never called.

- **Driver `0x242d7(ch, off, seg, words)`** programs the 16-bit 8237 (ports `0xC8/0xCA`, page
  `0x89`, mask `0xD4`, mode `0xD6`, flip-flop `0xD8`). The mode is `ch−4 | 0x04`, i.e. **demand
  mode, device → memory (write), no auto-init**. Blocks are clipped at a 128 KB DMA page.
  Count = 2 × 32-bit words (two 16-bit bus cycles per DSP word).
- **Block read `0x26d75(dsp, …)`**:
  1. `0x262cc(dsp, 1)` sets SERPA word 2: RX-enable for that DSP plus the bit 5 DMA source,
     saves and clears the interrupt enables, and masks IRQ10 at the slave PIC (`0xA1`).
  2. Arms DMA channel 6.
  3. Sends the DSP a request through the normal command link (`0x26ef4`: an address/length
     word, then a zero).
  4. Polls the 8237 terminal-count bit (`0xD0` bit 2) up to 20 000 times, with up to 4
     retries; on failure it reports error `0x834`/`0x835`.
  5. `0x262cc(dsp, 2)` restores word 2 and unmasks IRQ10.

So SERPA turns each 32-bit word arriving on RX0 or RX1 into two DRQ6 cycles. This is how FFT
results and traces reach the PC.

### 2.9 Sample-rate measurement is *not* in SERPA [S + F]

The schematic label "F_CLK — zur Frequenzmessung" (sheet 15) belongs to discrete logic:

1. The audio word clock (ALR or RX1LR, chosen by 74ACT257 D48 under control bit 10, SADR16)
   is halved by D42-A (LR/2).
2. D75 (74HCT40103, preset 255) counts that down. Its terminal-count pulse opens NAND D43-D.
3. The open gate lets **15 MHz** (the DSP's H3 clock halved by D42-B) through as **F_CLK →
   DSP-A TCLK0**.
4. DSP-A reads its own timer-0 counter (`TIMER_ADR = 0x808020`, counter at `+4`) in the sample
   ISR and stores it in `FREQ_COUNTER_VAL`. The host turns that into the displayed sample rate.

SERPA's FREQ1–3 pins are clock inputs (§2.1), not part of this.

---

## 3. PERIF2 = front-panel peripheral controller

### 3.1 What it connects to [S — top-level sheet 1, AT_INTERFACE block pins]

`ROW0–7` (outputs) and `COL0–11` (inputs): the key matrix · `KNOBAX` / rotary encoder ·
`PIO0–7` · `KEYVERS`, `RMK1`, `RMK2` · `VEECTRL` (LCD contrast voltage) · `ICSPERIF` chip
select (decoded at **4390h** on sheet 16) · `PERIF_INT` → SERPA INT2 → IRQ10.

### 3.1a Pinout of D24 (PLCC-68) [S2 "KEYBOARD DECODER"]

| Pin(s) | Name | Connection |
|---|---|---|
| 27–34 | DATA 0–7 | ID0–ID7 (buffered ISA data) |
| 40, 41, 42, 43 | ADR 0–3 | **SA1, SA11, SA12, SA13**, which confirms the 16-register decode seen in firmware |
| 37 | CSB | ← ICSPERIF (I/O 4390h) |
| 38 / 39 | WRB / RDB | ← IOW / IOR |
| 58 | RESET | ← RESETDRV |
| 57 | CLK1 | ← ISA OSC (14.318 MHz) |
| 56 | CLK0 | not connected |
| 44 / 45 | INT1 / INT2 | → PERIF_INT → SERPA D1 INT2 → IRQ10. Drawn from the INT1/INT2 pair; it looks like INT1 drives it and INT2 is unused, but the scan is too coarse to be sure. |
| 26 | PARSER | **tied to GND** [I: selects the PARallel host bus rather than the SERial one] |
| 24, 25 | SHIFT, TEST | not connected |
| 61–67 | `SCI` `SDI` `RPB` `RTB` `TBUSY` `SDO` `SCO` (active-low) | **all unconnected**: an alternative serial host/keyboard interface that the UPL doesn't use [I] |
| 2–9 | ROW 0–7 | 10 k pull-ups to +5 V → keyboard connector **X2 pins 3–10** |
| 10–16, 19–23 | COL 0–11 | 10 k pull-downs; **COL0–7 → X2 pins 11–18**, COL8–11 unused on the UPL |
| 46–51 | PIO 0–5 | via **274 Ω** series resistors → **X2 pins 19–24** (front-panel keyboard board) [I: LED drive] |
| 54 | PIO 6 | → 74HCT04 inverter (D22-E) → **VEECTRL** (LCD contrast) |
| 55 | PIO 7 | PIO bus → LCD connector (appears with VEECTRL on the LCD-interface sheet, p. 0) |
| 59 / 60 | RMK1 / RMK2 | **rotary-encoder quadrature A/B**: 10 k pull-ups + 4.7 nF RC filters, from the "Impulsgeber" connector **X8** (new, "NEU") or **X19** (old, "ALT") |

Related straps from the same connector sheet: `KEYVERS` = X2 pin 25 (keyboard-board version),
and `KNOBAX` = X8 pin 10 (only on the new encoder connector, so it tells old knob from new).
Both are read through the SERPA status mux (`0x2B92` bits 2 and 4), not through PERIF2.

### 3.2 Register map [F]

Same stride as SERPA: register *n* at **`0x4390 + 0x800·(n>>1) + 2·(n&1)`**, 8-bit accesses.
Port table in data segment `0x2E5C` at offsets `0x0C–0x2A`; the same table appears in
`CONTRAST.EXE`.

**Reads** (PERIF interrupt handler at `0x24e82`, init at `0x25c5c`):

| Port | Meaning |
|---|---|
| `0x5B92` | **Interrupt status**: bit 0 = key event, bit 3 = encoder event (masks from segment `0x2E75` at 0x1E/0x21) |
| `0x4390` | **Key code**: bits 6:4 = row, bits 3:0 = column (both ≤ 8) → index into a 9×8 key table at DS:`0x60` |
| `0x6390` | Read, value discarded, then a short delay loop → [I] latches the encoder counter |
| `0x4392` / `0x4B90` | **Encoder count**, low / high byte → 16-bit count, biased `0x8000` (signed delta), optionally accelerated (`×9` past a threshold) |
| `0x5B90`, `0x5B92`, `0x6390` | Read once each at init to clear pending state |

**Writes**: one generic routine, `0x24955(n)`, assembles each register from shadow fields at
DS:`0x40–0x4F` and does `out`:

| n | Port | Value written | Function (see §3.2a) | Shadow default → **value after init** |
|---|---|---|---|---|
| 0 | `0x4390` | `[42]<<7 \| [41]<<4 \| [40]` | Scan tick: bits 3:0 mantissa m₀ (2–15), bits 6:4 decade e₀ (0–4), **bit 7 auto-repeat enable** | `0xC2` → **`0xC7`** |
| 1 | `0x4392` | `0x80 \| [44]<<4 \| [43]` | Auto-repeat **rate** divider: bits 3:0 m₁ (2–15), bits 6:4 e₁ (0–2), bit 7 always 1 | `0x94` → **`0x8B`** |
| 2 | `0x4B90` | `[45]` | Auto-repeat **delay**, in repeat periods (2–31) | `0x04` → **`0x05`** |
| 3 | `0x4B92` | `0x30 \| [46]` | Encoder: bits 3:0 = acceleration factor (1 = off, 2–15), bits 5:4 always 1 | `0x30` → **`0x39`** |
| 4 | `0x5390` | `[48]` | Encoder acceleration window, in units of 4096/(OSC/2) ≈ 0.572 ms (2–255) | `0x02` → **`0x24`** |
| 5 | `0x5392` | `[47]` | Encoder sample/debounce period, same unit (2–255) | `0x02` → **`0x12`** |
| 6 | `0x5B90` | `[49]` | Never changed by the firmware [I: PIO direction, 0xFF = all outputs] | `0xFF` |
| 7 | `0x5B92` | `[4A]` — **PIO output port** (bit *n* = pin PIO*n*): bits 0–5 → front panel via X2 19–24; bit 6 → VEECTRL; bit 7 → LCD connector. Firmware sets and clears single bits via `0x2583c`/`0x25869`, and bits 4/5 as a pair via `0x25896`. | `0xFF` |
| 8 | `0x6390` | `[4B]` | `0x00` |
| 9 | `0x6392` | `[4C]` | `0x00` |
| 10 | `0x6B90` | `0xFF` constant | — |
| 11, 12 | `0x6B92`, `0x7390` | rejected (−2): not writable | — |
| 13 | `0x7392` | `0` | — |
| 14 | `0x7B90` | `[4D] \| [4E]<<3 \| [4F]<<7` — **interrupt enable**: bit 0 = key IRQ, bit 3 = encoder IRQ (the same bit positions as the status read at `0x5B92`), bit 7 = a separate flag toggled by `0x25656` (purpose unknown) | `0x09` |
| 15 | `0x7B92` | `0` | — |

*Correction to the first pass:* write `0x5B92` was first labelled an "interrupt mask". The
schematic shows that the PIO pins are the only general outputs, and firmware bits 6–7 of this
register are the contrast lines, so it is the PIO output latch. The *read* at the same address
is the interrupt status (different registers, same address).

Registers 8 and 9 (`0x6390`/`0x6392`) are written 0 at init and never changed. Register 10 is
always written `0xFF`, and 13/15 are always written 0. Nothing in the firmware reveals their
function.

### 3.2a How the settings are computed [F]

The PERIF2 setup code (`0x258f8`, `0x259b4`, init at `0x25ceb`) works in seconds and hertz
using Borland's floating-point emulator (`int 34h–3Dh`; decode by rewriting `CD 34+n` →
`9B D8+n`). All timing derives from the **ISA OSC (14 318 180 Hz, a literal in the data
segment) divided by 2**, which feeds CLK1. Divider fields use a **mantissa × 10^decade** format,
searched for the closest match by `0x24a6e`.

**Key scan and auto-repeat** (`0x258f8(tick, rate, delay)`; init passes 0.01 s, 9.0 Hz, 0.5 s):

| Stage | Formula | Init request | Programmed | Actual |
|---|---|---|---|---|
| Scan tick T₀ (reg 0) | 2/OSC · m₀ · 10^e₀ | 10 ms | m₀=7, e₀=4 → `0xC7` | **9.78 ms** |
| Repeat period T₁ (reg 1) | T₀ · m₁ · 10^e₁ | 9 Hz | m₁=11, e₁=0 → `0x8B` | **107.6 ms (9.30 Hz)** |
| Repeat delay (reg 2) | T₁ · m₂ | 0.5 s | m₂=5 → `0x05` | **0.538 s** |

Requesting a rate ≤ 0 clears reg 0 bit 7, which disables auto-repeat.

**Rotary encoder** (`0x259b4(accel, sample, window)`; init passes 9, 10 ms, 20 ms):

| Field | Formula | Init | Programmed |
|---|---|---|---|
| Sample/debounce period (reg 5) | n = round(t / 0.572 ms + 1), clamped 2–255 | 10 ms | `0x12` (9.73 ms) |
| Acceleration window (reg 4) | same | 20 ms | `0x24` (20.0 ms) |
| Acceleration factor (reg 3, low nibble) | clamped 1–15 | 9 | `0x39` |

The interrupt handler divides the raw encoder count by 2 and keeps the remainder, so there are
**2 counts per detent**. When acceleration is on (factor ≥ 2) and a single interrupt reports more
than 4 steps, it **multiplies by 9**. `0x25caa(on)` is the public on/off switch: it reprograms
the same registers with factor 9 or 1.

**Interrupts:** init enables key (bit 0) and encoder (bit 3) interrupts in reg 14 through
`0x256b7(0)` and `0x256b7(3)`. Shutdown (`0x25bfb`) clears them with `0x25710`, then restores
the original INT 72h vector.

**LCD contrast** (`CONTRAST.EXE`, "sets the contrast voltage for B/W LCDs"): PIO6 (inverted →
VEECTRL) and PIO7 drive a **64-step up/down digital potentiometer**, presumably on the LCD side.
Bit 6 is the direction and bit 7 the step pulse. It resets to mid-scale (`0x20`), and "value
0–100" maps onto steps 0–63.

### 3.3 Limits of the PERIF2 model

- The PERIF2 sheet is missing from the Vol. 2 scan (its sheet 19 of 19) but is present in
  *Schaltplan_ocr.pdf* as sheet 18 of an earlier revision. The two revisions agree on every
  signal they share, but the pinout above comes from the 1995 plot.
- The firmware only exercises the functions R&S used. Registers 11–12 are rejected by the
  driver but may exist in silicon.

---

## 4. Other findings from this pass

- **`0x2C0–0x2E1` is the GPIB controller, not R&S silicon.** It is the TNT4882C (sheet 9,
  "Base-Address 4882C: 2C0"), and firmware also uses its NI-style aliases `0x6E1`/`0xAE1`/
  `0x16E1`/`0x1AE1`.
- An **unfitted discrete LPT2** (0x278/0x27A, 74HCT688 strap) and a "SETUP RAM" option for
  128K×8 parts (D15/D16, "N.B.") are on the board.
- `DISK1/TOOLS` contains `B8DAI.RBF`, an Altera raw bitstream, presumably for an option
  board. Neither custom chip is programmable.
- **Live probing:** `DIAG:DEV` has `REG` and `PIN` selectors (see `CLAUDE.md`). With the map
  above, read-only reads of *status* registers are the only things worth trying: `0x2B92`
  (status mux), `0x1390`, `0x5B92`. **Never** read `0x3392` casually: every access advances the
  setup-RAM address counter. **Never** read `0x0390`/`0x0B90`: they pop words from the DSP link.

## 5. Next steps, in order of value

1. SERPA is done as far as the firmware goes (host + DSP sides, DMA, §2.3–2.9). What's left
   needs hardware: the word 3/4 upper bits and the RX bit-count field (logic analyser on
   FSX/FSR/CLKX), the IAI config-bus word format, what the INT0/INT1 inputs (SDA, GINT) do
   inside the chip, and the UFS source on DSP-B.
2. PERIF2 is done as far as the firmware goes. Registers 6 and 8–10 and reg 14 bit 7 can only
   be named by experiment (a replacement design could simply latch them).
3. Record the setup-RAM battery (G2, 3.4 V) as a maintenance item and back up the RAM
   contents over RS-232 if `DIAG:DEV` can reach it.
