# NAD M51 DAC

What the project adds for the NAD M51: remote control of its source and volume over RS‑232, so
the general DAC suite can log and set them. The measurements themselves are the general
[`dac_test.py`](README.md#dac-characterization-measurementsdac_testpy) suite: the M51 needs nothing
M51-specific to be measured.

## Control library (`nad_m51.py`)

| | |
|---|---|
| Link | the M51's RS‑232 port, **115200 8N1, no flow control** |
| Protocol | ASCII `Var=Value` / `Var?` |

```bash
python nad_m51.py --port COM2 volume         # query
python nad_m51.py --port COM2 volume -3      # set
python nad_m51.py --port COM2 source
python nad_m51.py --help                     # every subcommand
```

## Measuring it with `dac_test.py`

- **USB input:** laptop → USB → M51 → balanced out → UPL analyzer, with `--source pc`.
- **S/PDIF, optical and AES inputs:** fed from the UPL's digital output with `--source upl`
  (the default). The UPL's B29 drives BAL, UNBAL and optical at once, so optical needs no setting.

`--dut m51 [--dut-port COM2]` works with either source:

- **Fixed-output mode** (the M51's own setting): the M51 is a plain DAC to the suite. Run it like
  any other; add `--dut m51` only if you want its source and volume logged in the report.
- **Variable output:** `--dut m51 --volume 0` sets the volume for the run and restores it at the end.
- **`volsweep`**: THD+N/THD/level vs the M51's own volume, to find the best setting to leave it at
  when something downstream does the level control.

```bash
python measurements/dac_test.py --port COM7 --source pc --device N --fs 44100,96000,192000 \
    --settle 0.6 --label m51 all                                  # fixed-output mode
python measurements/dac_test.py --port COM7 --source pc --device N --fs 96000 \
    --dut m51 --volume 0 --label m51_0dB all                       # variable, run at 0 dB
python measurements/dac_test.py --port COM7 --source pc --device N --fs 48000 \
    --dut m51 volsweep --volumes -20,-10,-6,-3,0,3,6,10
python measurements/dac_test.py --port COM7 --fs 44100,48000,88200,96000 --label m51_optical all
```

**Status:** the full suite has run live over optical (`--source upl`, 2026‑09‑24/25, results in
`results/dac/optical_*`, `native_*`, `m51_*`). **Not yet run live:** `--source pc`, `--dut m51`,
`--volume` and `volsweep`.

**Worth knowing before measuring:** at 0 dB volume a 0 dBFS tone clips (under 1 dB of headroom),
and its THD+N also latches the UPL's THD+N floor about 6 dB high (`dac_test.py thdn` clears
that itself). At **−1 dB volume** the clipping is gone. The M51's volume is digital, ahead of a
fixed output-stage noise floor, so each dB of attenuation costs a dB of dynamic range. Full
results and the reasoning are in `CLAUDE.md`, "NAD M51 over optical".

## History

The five `measurements/m51_*.py` scripts were retired on 2026‑09‑24: frequency response → `fr` +
`thdn`, IMD → `imd` + `imdlevel`, FFT sidebands → `jtest` + `fft`, gain sweep → `volsweep`, and
the frequency-counter jitter proxy → `jtest`, the proper test. They're in git history (`aa6dfa1`)
if ever needed.
