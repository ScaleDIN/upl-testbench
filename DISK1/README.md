# UPL firmware 3.06: install disk 1 (program)

Git-ignored except this README. This project folder is laid out like the R&S firmware download:
running R&S's self-extractor **`UPL_306.EXE`** (firmware 3.06, 2006) in the project root produces
`DISK1/`, `DISK2/` and `ReadMe.txt` there. Put `UPL_306.EXE` in the root and extract it, or copy
the two disk folders in.

Expected contents:

```
CONTENT.DOC  UPLINST.BAT  LHA.EXE
UPL.LZH      the instrument application, UPL_UI.EXE (16-bit Borland C++)
DSP.LZH      TMS320C3x DSP images (A.OUT, B.OUT, LOADER.OUT, DUMP.OUT; TI COFF)
DRIVER.LZH   DOS drivers: IECX (GPIB), GRAPHX, STRINX, BEPX, COMX (serial)
REF.LZH  SETUP.LZH  ROOT.LZH  TOOLS.LZH  FILECHK.LZH  LABEL.LZH
```

The `.LZH` archives are LHA; `LHA.EXE` is 16-bit DOS. Open them with Windows' own
`C:\Windows\System32\tar.exe -xf DISK1\UPL.LZH -C <dest>` or `python tools/lzh_extract.py`.
`CLAUDE.md` ("Instrument architecture") covers what's inside.

**Where to get it:** R&S's website (UPL firmware download, `UPL_306.EXE`).
