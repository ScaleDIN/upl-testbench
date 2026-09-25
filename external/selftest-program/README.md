# R&S factory selftest program

Put **`SELFTEST_Program.TXT`** here (git-ignored, ~28 KB): the R&S factory selftest for the UPL,
as a plain-text UPL BASIC listing (`UPL OUT` / `UPL IN` to the instrument's own SCPI parser).

`upl_selftest.py` doesn't read this file at run time. Its command sequence and every tolerance were
copied from it, so it's the reference for checking that script (see
[SELFTEST_README.md](../../SELFTEST_README.md)).

Not to be confused with `SELFTEST.BAS` in the firmware's `DISK2/USER.LZH`, which is the
tokenized version that runs on the instrument (OPTIONS → Exec Macro).

**Where to get it:** it has been shared in the [diyAudio UPL renovation thread](https://www.diyaudio.com/community/threads/rohde-schwarz-r-s-upl-audio-analyzer-renovation.353461/). The tokenized `SELFTEST.BAS` from the
firmware disks has the same program, but only its string literals are readable
(`python tools/lzh_extract.py DISK2/USER.LZH SELFTEST.BAS`).
