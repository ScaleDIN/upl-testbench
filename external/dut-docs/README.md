# Documentation for the devices under test

Put third-party documentation for the tested devices here (git-ignored), one subfolder per
device. Nothing in the code reads these; they're the sources behind the drivers and spec files.

| Subfolder (suggested) | Files | Behind |
|---|---|---|
| `nad-m51/` | NAD RS‑232 protocol docs: `nad_rs232_2.02.pdf`, `rs232_M51_commands.pdf`, `M51_remote_codes.pdf` | `nad_m51.py`, [M51_README.md](../../M51_README.md) |
| `elektor-dac2000/` | Elektor Electronics articles "Audio DAC 2000" (T. Giesberts): 11/1999, 12/1999, 1/2000 (e99b058, e99c078, e001012) | `measurements/dut_specs/elektor-dac2000.json` |
| `umik-1/` | the miniDSP UMIK‑1's per-serial calibration files (`<serial>.txt`, `<serial>_90deg.txt`) | acoustic measurements with `audio_tests.py` |
| `dcx2496/` | nothing needed: the reverse-engineered protocol is in the repo as `dcx2496_protocol.md` | `dcx2496.py`, [DCX2496_README.md](../../DCX2496_README.md) |

**Where to get them:** NAD publishes its RS‑232 protocol documents on its support site; the
Elektor articles are in Elektor's archive.

Adding a device: a subfolder here for its documents, a spec file in `measurements/dut_specs/` if
it has published figures, and a guide next to the other `*_README.md` files.
