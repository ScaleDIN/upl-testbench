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
| 56 / 55 / 54 | FREQ1 / FREQ2 / FREQ3 | frequency-measurement outputs (FREQ2 used on D1) |
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
| 2 | `0x1390` | W | Interrupt/channel enable (shadow `[8]`; bits 2 and 3 are per-channel enables); written 0 before unhooking the IRQ | `0x2633x`, `0x263a3`, `0x26c96` |
| 2 | `0x1390` | R | **Status**: bit 4 = channel ready/done (polled with timeout) | `0x25ea9` |
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

In DSP mode the register file appears as 8 words at the listed DSP addresses (DA0–2 = DSP
A0–A2, 32-bit data). The DSP firmware `A.OUT`/`B.OUT` (TI COFF) programs those registers.
**Not disassembled yet.** It is the natural next step, and the host-side layout above tells you
what to look for: the same data/format/status structure.

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

| n | Port | Value written | Power-on default |
|---|---|---|---|
| 0 | `0x4390` | `[42]<<7 \| [41]<<4 \| [40]` | `0xC2` |
| 1 | `0x4392` | `0x80 \| [44]<<4 \| [43]` | `0x94` |
| 2 | `0x4B90` | `[45]` | `0x04` |
| 3 | `0x4B92` | `0x30 \| [46]` | `0x30` |
| 4 | `0x5390` | `[48]` | `0x02` |
| 5 | `0x5392` | `[47]` | `0x02` |
| 6 | `0x5B90` | `[49]` | `0xFF` |
| 7 | `0x5B92` | `[4A]` — **PIO output port** (bit *n* = pin PIO*n*): bits 0–5 → front panel via X2 19–24; bit 6 → VEECTRL; bit 7 → LCD connector. Firmware sets and clears single bits via `0x2583c`/`0x25869`, and bits 4/5 as a pair via `0x25896`. | `0xFF` |
| 8 | `0x6390` | `[4B]` | `0x00` |
| 9 | `0x6392` | `[4C]` | `0x00` |
| 10 | `0x6B90` | `0xFF` constant | — |
| 11, 12 | `0x6B92`, `0x7390` | rejected (−2): not writable | — |
| 13 | `0x7392` | `0` | — |
| 14 | `0x7B90` | `[4D] \| [4E]<<3 \| [4F]<<7` | `0x09` |
| 15 | `0x7B92` | `0` | — |

*Correction to the first pass:* write `0x5B92` was first labelled an "interrupt mask". The
schematic shows that the PIO pins are the only general outputs, and firmware bits 6–7 of this
register are the contrast lines, so it is the PIO output latch. The *read* at the same address
is the interrupt status (different registers, same address).

The meanings of the n = 0–6 and 8–14 fields still need their callers traced. With the pinout
known, they must be scan/debounce timing, encoder mode, PIO direction and interrupt enables,
because PERIF2 has no other outputs. Only the key, encoder and PIO/contrast paths are pinned
down.

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

1. Disassemble `A.OUT`/`B.OUT` (TMS320C3x) for accesses to `0xC00000–0xC0000F` / `0xA00000`.
   That gives the DSP-mode register map and completes SERPA.
2. Trace the callers that set PERIF2 fields `[0x40–0x4F]` (`0x247bf` onward in the same
   module) to name the remaining PERIF2 registers.
3. Record the setup-RAM battery (G2, 3.4 V) as a maintenance item and back up the RAM
   contents over RS-232 if `DIAG:DEV` can reach it.
