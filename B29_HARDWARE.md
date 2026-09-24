# UPL-B29 vs UPL-B2 hardware (2026-09-24)

Low-priority reference notes; not needed for operating the instrument.

From the user's photos (Drive folders `1coAiqiv…` = B29
main board, `1Hiy6L5W…` = front I/O board) against the B2 parts list (Service Manual Vol.2
pp.278–291, "ED AES-BOARD", 10.03.97) and schematics (pp.233–269):
- **Front I/O board is the same part: `1078.4223.02`** on both (label visible in IMG_0838).
  Its output stage matches Vol.2 p.247 on the photos: 2 × Mini-Circuits T1‑6T, CLC430 drivers,
  O1/O7 pads coaxed to the BNC. The user has redrawn this board (Protel schematic, CAM, layout
  in that folder).
- **Main board differs:** B29 = PCB `1078.4246.02` "included in 1078.4300.02" (sticker
  `1078.4300.02 / 100136`); B2 = AES main board 1078.4200 in 1078.4100. Same architecture,
  newer silicon; B29 date codes are 2003 (AD9850 "0342", CS8403A "…0316").

  | Function (B2 ref) | B2 | B29 |
  |---|---|---|
  | AES transmitters (D42, D43) | Crystal CS8401A | **CS8403A‑CS** ×2 (later, faster CS840x) |
  | DDS sync generator (D2) | AD7008 | **AD9850BRS** |
  | AES receivers (D4, D5) | Crystal CS8411 | 2 Cirrus 28‑pin in the same spot, markings lost to glare |
  | Master clock (D20) | one Fujitsu FAR‑M2SC VCXO | **three metal-can oscillators**: 24.576 MHz (CTI), 22.5792 MHz, one ≈49.152 MHz (partly legible) |
  | PLL synth (D34, D35) | TLC2932 | TLC2932 (TSSOP "2932") — same |
  | Unchanged | DAC8143, REF01, DG413, 74HC logic | same parts seen |

  Reading: fixed 44.1k/48k-family crystals (22.5792 / 24.576 MHz, plus a 2× for 96k) and
  faster transmitters are what the 96 kHz upgrade needed; the rest carried over. The receiver
  part and the third oscillator's exact value still need a glare-free photo.
- **Side finding:** the user's Feb 2022 selftest photo (IMG_3743) lists options
  `B1(0.01),B29(2.16),0,0,B4,B5(1.62),B6,0,B10,0,0,0` — **no B21, B22 or B23**. Today's `*OPT?`
  has all three, so they were enabled after Feb 2022.

Open: receiver chip part number and the third oscillator's exact frequency — needs a
glare-free photo (user will supply).
