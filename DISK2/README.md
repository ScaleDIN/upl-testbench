# UPL firmware 3.06: install disk 2 (examples and user programs)

Git-ignored except this README. Produced by R&S's `UPL_306.EXE` together with `DISK1/`: see
[`../DISK1/README.md`](../DISK1/README.md) for how to get both.

Expected contents, and what this project uses from them:

| File | Contents | Used for |
|---|---|---|
| `USER.LZH` | `SNDFILE.BAS`, `SER_IN.EXE`, `DRV_INST.BAS`, `SELFTEST.BAS`, `FLAT_GEN.BAS`, `IMPEDANC.BAS`… (→ `C:\UPL\USER` on the instrument) | `ser_in.py` / `tools/sndfile_batch.py` (SNDFILE protocol), the selftest, flatness calibration |
| `IEC_EXAM.LZH` | `EXAM1–7.BAS`, `RS232_BT.BAS`: remote-control examples | the RS‑232 protocol and basic SCPI in `upl_capture.py` |
| `B10_EXAM.LZH` | the same examples for the on-board BASIC (UPL‑B10) | — |
| `DEMOEXAM.LZH` | `DEMO.BAS` | user-filter routing, zoom FFT |
| `SETUP.LZH`, `SET_EXAM.LZH`, `LOG.LZH`, `LABEL.LZH` | example setups, logs | — |
| `X_DATA.EXE`, `SETINST.BAT`, `LHA.EXE` | example-data self-extractor, installer | — |

List or extract a member: `python tools/lzh_extract.py DISK2/USER.LZH [MEMBER]`.
