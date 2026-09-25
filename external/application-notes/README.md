# R&S application notes

Put the R&S UPL/UPD application notes here (git-ignored), one folder or PDF per note, named as
downloaded. Nothing in the code reads them. They matter because many of the `.exe` files bundled with
them are **self-extracting ZIPs holding R&S's own BASIC programs and `.SAC` setups**, which are
the best source of confirmed-working SCPI (`unzip -o <note>.exe -d out/`). `CLAUDE.md`,
"Application Notes catalog", covers what each one contains.

| Note | Topic | Why it's useful here |
|---|---|---|
| 1GA42_0E | Transferring files from a UPL to a PC via RS‑232 | `SNDFILE.BAS`/`SER_IN.EXE`, behind `ser_in.py` / `tools/sndfile_batch.py` |
| 1ga16_1l | Loudspeaker measurements (UPL/UPD) | **richest source**: sweep setup, `DISP:TRAC:FEED`, trace readout and store, cursor readout |
| 1GA21_1E | CD players with the UPA‑CD | `CDTEST.BAS` + the `CDA_*.SAC` setups: track-to-setup map for `upacd_test.py` |
| 1GA24_1E | Tuners (with SMT) | `TUNTEST.BAS`, trace store |
| 1GA30_0E | A/D converters | `Adctest.bas`: DAC/ADC methodology |
| 1GA33_1L | Limit checking | `LIMIT.BAS` |
| 1GA36_1L | Collection of setups | jitter (`JIT*_DD.SAC`) and protocol (`PROT*_DD.SAC`) setups for B21/B22 |
| 1GA12_1L, 1GA32_1L | Settling function; transient response of AGC circuits | dynamics/limiter testing |
| 1GA15_1L | Protocol analysis at digital interfaces | AES3 / S/PDIF background |
| 1GA34_1L, 1ga39_0e, 1GA43_0E, 1ga31_1l, 1GA24 (loudspeaker) | hearing aids, GSM phones, FM tuners, clicks on audio lines, loudspeakers | turnkey programs for other DUT classes |
| 7BM44_0E | Audio-to-video delay | the UPL's analog output lags its digital output by ~690 µs |
| RCS0702-0032 | Amplifier tests to IEC 60268‑3 (UPV) | test-plan checklist |
| FM Tuner Test Program | `TUNER.LZH` | cursor readout, trace freeze |

**Where to get them:** R&S's website (application note search, by number); `.LZH` archives inside
them open with `python tools/lzh_extract.py`.
