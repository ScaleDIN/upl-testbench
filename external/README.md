# External files (not in git)

This project uses a number of files that aren't ours to redistribute: R&S firmware, manuals,
application notes, test-disc and option data, and third-party DUT documentation. They are
**git-ignored**. Each folder below holds only a README saying what goes in it, where it came
from, and what uses it. Put your own copies there.

**Where most of it can be found:** R&S's website still has the firmware, operating manuals and
application notes. Much of the rest (service manuals, UPA‑CD rips, the B23 library) has been
shared by UPL owners in the diyAudio thread
[*Rohde & Schwarz R&S UPL audio analyzer renovation*](https://www.diyaudio.com/community/threads/rohde-schwarz-r-s-upl-audio-analyzer-renovation.353461/).

| Folder | What goes there | Required? |
|---|---|---|
| [`upa-cd/`](upa-cd/) | the R&S Audio Test Disc UPA‑CD as WAV files, zipped | **required** for `measurements/upacd_test.py` disc-track tests (it reads tracks straight out of the zip); its `--wav` mode doesn't need it |
| [`manuals/`](manuals/) | UPL operating manuals Vol.1/Vol.2, data sheet, service manuals | optional, strongly recommended: Vol.2 is the SCPI reference |
| [`application-notes/`](application-notes/) | R&S UPL/UPD application notes (1GAxx), with their example programs | optional: working SCPI in R&S's own BASIC programs |
| [`selftest-program/`](selftest-program/) | `SELFTEST_Program.TXT`, R&S's factory selftest in UPL BASIC | optional: the source `upl_selftest.py` was built from (not read at run time) |
| [`b23-coded-audio/`](b23-coded-audio/) | the UPL‑B23 coded-audio data library (AC‑3 files) | optional: only to install B23's library on a UPL |
| [`dut-docs/`](dut-docs/) | documentation for the devices tested here (NAD M51 RS‑232 protocol, Elektor DAC 2000 articles…) | optional: reference for the equipment guides |

No code reads anything here except `upacd_test.py` (the UPA‑CD zip).

Two other locations hold external files too:

- **`../DISK1/`, `../DISK2/`, `../UPL_306.EXE`** (optional): the UPL firmware 3.06 install media, kept at the
  project root because the docs and `tools/lzh_extract.py` examples refer to those paths. See
  [`../DISK1/README.md`](../DISK1/README.md).
- **`../testsignals/`**: generated, not downloaded. `python tools/testsignals.py` rebuilds it.

Software to install, not stored anywhere here:

| What | Required? |
|---|---|
| Keysight IO Libraries Suite (tested: 2023 U1; the "Instrument Control Bundle" installer includes it) + `pip install pyvisa` | only for GPIB (via an Agilent/Keysight 82357B) |
| the DAC's own USB audio driver, if it needs one (e.g. NAD's USB Audio driver for the M51) | only for `dac_test.py --source pc` with such a DAC |
| Python packages | **required**: see [../README.md](../README.md#setup) |
