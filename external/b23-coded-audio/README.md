# UPL‑B23 coded-audio library

Put the **UPL‑B23 "Coded Audio Signal Generation"** data here (git-ignored, ~15 MB zipped). B23
generates IEC 61937 (AC‑3) bitstreams from a library of pre-coded WAV files. The option key only
enables the function; **the data library has to be installed on the UPL's disk separately**.

Expected contents (as distributed):

```
Disk1.IMA, Disk2.IMA, Disk3.IMA     floppy images of the three install disks
Disk1/ Disk2/ Disk3/                the same, extracted: README.B23, B23INST.BAT,
                                    20_192.EXE, 51_448_1.EXE, 51_448_2.EXE (self-extracting)
CODED.zip                           the unpacked library, 2030 files
```

On the instrument the library belongs in **`C:\CODED\AC3\48000\`** (`20_192\` = 2/0 at 192 kb/s,
`51_448\` = 5.1 at 448 kb/s, plus single-channel sets `C L R LS RS LFE`). `README.B23` is R&S's
original; the `B23INST.BAT` installers in some copies are a later third-party repack, so check them
before running them. Getting files onto the UPL, and the SCPI to use B23, is in `CLAUDE.md`,
"UPL‑B23".

Nothing in this project's code reads these files. B23 is only useful for testing a *decoder*
(e.g. an AV receiver).

**Where to get it:** it shipped with the option on floppies; copies have been
shared in the [diyAudio UPL renovation thread](https://www.diyaudio.com/community/threads/rohde-schwarz-r-s-upl-audio-analyzer-renovation.353461/).
