# Manuals

Put the R&S UPL manuals here (git-ignored). Nothing in the code reads them. They're the
reference behind the SCPI syntax, and `CLAUDE.md` cites them by volume and page.

| File (as downloaded) | What | Used for |
|---|---|---|
| `R&S_UPL_Audio_Analyzer_Op_Vol_1.pdf` (~3.4 MB) | Operating Manual Vol.1: front-panel operation, measurement functions, specs | how each function behaves; FFT line counts; filters |
| `R&S_UPL_Audio_Analyzer_Op_Vol_2.pdf` (~1.5 MB) | Operating Manual Vol.2: **remote control / SCPI command reference** | every SCPI command the tools send |
| `R&S_UPL_Audio_Analyzer__Data_and_Spec_Sheets.pdf` (~1 MB) | brochure + data sheet | option list (B21, B22…), specifications |
| Service Manual Vol.2 (optional, ~28 MB) | circuit diagrams, component plans, parts lists | hardware notes (`B29_HARDWARE.md`, `SERPA_PERIF.md`, the CPU-board sections of `CLAUDE.md`) |
| Service Manual UPL‑B1 (optional) | low-distortion generator schematics, calibration | the B1 notes in `CLAUDE.md` |

**Where to get them:** R&S publishes the operating manuals for legacy products on its website
(search "UPL operating manual"); the service manuals have been shared in the
[diyAudio UPL renovation thread](https://www.diyaudio.com/community/threads/rohde-schwarz-r-s-upl-audio-analyzer-renovation.353461/).

To search the PDFs as text: `pdftotext -layout <file> out.txt`.
