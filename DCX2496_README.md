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

The protocol is write-only: there is no readback, so the scripts track state themselves.

```bash
python dcx2496.py --port COM2 enable                  # enable remote control first
python dcx2496.py --port COM2 gain out1 -6.0
python dcx2496.py --port COM2 xover out1 500 --type lr24
python dcx2496.py --port COM2 mute out1 off
python dcx2496.py --help                              # every subcommand
```

## Physical setup

For all the tests below: **UPL generator output → DCX2496 input A**; **DCX2496 output N → UPL
analyzer input** (both XLR balanced). The UPL is both generator and analyzer, with the DCX2496 in
between.

## Response sweeps (`dcx_sweep.py`)

Sets a DCX2496 crossover (and/or gain), runs a UPL level-vs-frequency sweep, and saves a CSV and a
graph. It handles one curve or a family of curves (e.g. several highpass cutoffs) in one run.

```bash
# one highpass curve, cutoff isolated (lowpass disabled)
python dcx_sweep.py --dcx-port COM2 --upl-port COM7 --out-ch out1 \
    --hp-freq 500 --hp-type lr24 --lp-type off --label hp500_lr24

# a family of cutoffs in one run (one CSV column and one curve per cutoff)
python dcx_sweep.py --dcx-port COM2 --upl-port COM7 --out-ch out1 \
    --hp-freq 100,300,1000,3000 --hp-type lr24 --lp-type off --label hp_family

# just re-measure whatever the DCX is currently configured to, no writes at all
python dcx_sweep.py --dcx-port COM2 --upl-port COM7 --out-ch out1 --no-configure --label asis
```

**Before trusting a result**, `dcx_sweep.py` warns if the UPL looks like it's in an unexpected
instrument state (`INST?`/`INST2?`/`INP:TYPE?`). A flat, implausible result across the whole sweep
usually means the UPL was left in a digital-instrument state by a previous test (fix: `*RST`). An
all-noise-floor result with no frequency lock usually means the DCX2496 output is muted (fix:
`dcx2496.py --port COM2 mute out1 off`). Both happened during development; see `CLAUDE.md`,
"FIRST REAL AUTOMATED CROSSOVER MEASUREMENT".

## Characterization scripts (`measurements/dcx_*.py`)

```bash
# THD+N vs frequency and vs level, flat passthrough
python measurements/dcx_thdn.py --dcx-port COM2 --upl-port COM7

# separates THD+N into pure THD (harmonics) vs noise contribution, vs frequency --
# use this instead of dcx_thdn.py if you want to know whether a bad number is really
# distortion or just the DCX's noise floor (see CLAUDE.md for what this revealed)
python measurements/dcx_thd_vs_thdn.py --dcx-port COM2 --upl-port COM7

# gain accuracy (+/-15dB), filter-type comparison (Butterworth/Bessel/Linkwitz-Riley
# at several orders), and limiter behavior, all in one run
python measurements/dcx_gauntlet.py --dcx-port COM2 --upl-port COM7

# balanced (XLR direct) vs single-ended (via XLR-to-RCA-to-XLR adapters) comparison --
# run once per physical wiring state with a different mode label; --compare puts the
# earlier run beside this one in the report
python measurements/dcx_balanced_test.py balanced     --dcx-port COM2 --upl-port COM7
python measurements/dcx_balanced_test.py single_ended --dcx-port COM2 --upl-port COM7 \
    --compare results/dcx_balanced_test/balanced_<timestamp>
```

Each DCX script's run folder is named after the output channel (`out1_<timestamp>`) unless you
give `--label`.

`dcx_balanced_test.py` warns if a run's level is near the noise floor with THD+N near 0 dB. That
pattern means the signal isn't actually reaching the analyzer (check the physical adapter chain),
not a real balanced/unbalanced difference.

Results and their interpretation (THD vs THD+N, filter shapes, limiter, balanced vs single-ended)
are in `CLAUDE.md`, "Behringer DCX2496".
