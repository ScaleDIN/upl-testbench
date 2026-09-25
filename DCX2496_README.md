# Behringer DCX2496 crossover/EQ

Closed-loop testing of the Behringer DCX2496: this PC sets the crossover, EQ and gain over the
DCX's RS‑232 link, and the UPL measures the result. For plain analog measurements (THD+N, noise,
response) of any device, see the general tests in [README.md](README.md#tests-for-any-device);
this file covers what the DCX's remote control adds.

## Control library (`dcx2496.py`)

| | |
|---|---|
| Link | the DCX's RS‑232 "link" port, **38400 8N1** |
| Protocol | MIDI-SysEx-style, unofficial, reverse-engineered: full description in `dcx2496_protocol.md` |
| Verified live | gain, mute, polarity, phase, crossover (HP/LP type and frequency), EQ bands 1–9 |

The protocol is write-only: there is no readback, so the scripts can't restore what they change.

```bash
python dcx2496.py --port COM2 enable                  # enable remote control first
python dcx2496.py --port COM2 gain out1 -6.0
python dcx2496.py --port COM2 xover out1 500 --type lr24
python dcx2496.py --port COM2 mute out1 off
python dcx2496.py --help                              # every subcommand
```

## Physical setup

For all the tests below: **UPL generator output → DCX2496 input A**; **DCX2496 output N → UPL
analyzer input 1** (both XLR balanced). The UPL is both generator and analyzer, with the DCX2496 in
between. A second output into analyzer input 2 is optional (`--dut-out out1,out2`).

## Measuring it (`measurements/analog_test.py --dut dcx`)

The DCX is measured by the general analog suite, which drives the DCX over `--dut-port` as well:
see [README.md, analog DUT characterization](README.md#analog-dut-characterization-preamps-and-friends-measurementsanalog_testpy)
for every test. `--dut dcx` first sets the measured output(s) **flat: unmuted, EQ off, crossover
off, limiter off, gain 0 dB**, and leaves them flat at the end. The protocol can't read the DCX's
settings back, so they are *not* restored: save a preset on the DCX first if you want it back.
One output (the default, `out1`) means a one-channel run (`--mono`).

```bash
# everything: gain, FR, THD+N and THD vs frequency and level (to clipping), noise and EIN,
# IMD, Zin/Zout, plus the DCX's own gain law, filter types and limiter
python measurements/analog_test.py --port COM7 --vin 1 --dut dcx --dut-port COM2 --label out1 all

# filter-type comparison at one cutoff (Butterworth / Bessel / Linkwitz-Riley)
python measurements/analog_test.py --port COM7 --vin 1 --dut dcx xover \
    --types but12,but24,bes24,lr24,but48 --freqs 500

# a family of cutoffs of one type, on one graph; --side lp for low-pass
python measurements/analog_test.py --port COM7 --vin 1 --dut dcx xover --types lr24 --freqs 100,300,1000,3000

# gain accuracy (-15..+15 dB) and the limiter
python measurements/analog_test.py --port COM7 --vin 1 --dut dcx gainlaw
python measurements/analog_test.py --port COM7 --vin 1 --dut dcx limiter --thresh -10

# the DCX exactly as it is set up (a real speaker preset): no writes at all
python measurements/analog_test.py --port COM7 --vin 1 --dut dcx --dut-asis fr
```

`xover` prints each curve's −3 dB and −6 dB frequencies and its stopband slope. Butterworth is
−3 dB at the cutoff, Linkwitz-Riley −6 dB, and the slope approaches 6 dB/octave per order (it
reads ~1 dB/octave short for LR, whose knee is softer). `--vin 1` matches the 2026‑09‑23 runs,
which used 1 V throughout.

These replace `dcx_sweep.py`, `dcx_thdn.py`, `dcx_thd_vs_thdn.py` and `dcx_gauntlet.py`
(removed 2026‑09‑25; they're in git history before that date).

**If a result looks wrong:** all noise with no frequency lock used to mean a muted DCX output.
`--dut dcx` now unmutes it, but under `--dut-asis` it is still possible. A flat, implausible
result means the UPL was left in a digital-instrument state; the script's `*RST` and the
`INST?` readback in its log cover that (see `CLAUDE.md`, "FIRST REAL AUTOMATED CROSSOVER MEASUREMENT").

## Balanced vs single-ended (`measurements/dcx_balanced_test.py`)

Run once per physical wiring state with a different mode label; `--compare` puts the earlier run
beside this one in the report.

```bash
python measurements/dcx_balanced_test.py balanced     --dcx-port COM2 --upl-port COM7
python measurements/dcx_balanced_test.py single_ended --dcx-port COM2 --upl-port COM7     --compare results/dcx_balanced_test/balanced_<timestamp>
```

`dcx_balanced_test.py` warns if a run's level is near the noise floor with THD+N near 0 dB. That
pattern means the signal isn't actually reaching the analyzer (check the physical adapter chain),
not a real balanced/unbalanced difference.

Results and their interpretation (THD vs THD+N, filter shapes, limiter, balanced vs single-ended)
are in `CLAUDE.md`, "Behringer DCX2496".
