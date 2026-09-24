# DUT reference specs

Optional. `spdif_dac_test.py --dut-spec <name>` loads `<name>.json` from this folder (or any
path ending in `.json`) and prints each published figure under the matching result. The test
itself never depends on these — it is the same for every DAC.

Every key is optional; values are free text, printed as-is:

| Key | Printed under |
|---|---|
| `name`, `notes` | header / not printed (`notes` is for the reader of the file) |
| `fullscale`, `dc` | `check` |
| `fr20k` | `fr` — the one numeric key: `{"base": dB, "high": dB}`, response at 20 kHz for ≤ 48 kHz and for 88.2/96 kHz |
| `thdn`, `snr`, `dr` | `thdn` |
| `imd` | `imd` |
| `xtalk` | `xtalk` |
| `zout` | `zout`, `stability` |
| `linearity` | `linearity` |
