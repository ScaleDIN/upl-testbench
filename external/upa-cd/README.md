# UPA‑CD Audio Test Disc

Put the **R&S Audio Test Disc UPA‑CD (852.8400.02)** here as a zip (git-ignored, ~810 MB). Keep it
zipped: `measurements/upacd_test.py` reads tracks straight out of it and **uses the first `*.zip`
in this folder by default** (`--zip` overrides).

Expected layout inside the zip:

```
UPA-CD/Wav Files/01 - <name>.wav      47 tracks, 44.1 kHz / 16-bit / stereo, bit-exact CD rips
UPA-CD/Wav Files/02 - <name>.wav
...
UPA-CD/Booklet.pdf                    scanned booklet (no text layer): track list and levels
```

Only the `UPA-CD/Wav Files/NN - *.wav` naming matters to the script (it matches the two-digit track
number). A rip of your own disc works if you zip it that way.

Tracks the script uses: **4** (D/A linearity staircase to −91.2 dBFS) for `linearity`, and any
stepped-tone track with `segments`. The full track list is in `CLAUDE.md`, "UPA-CD".

**Level warning:** many tracks are at 0 dBFS; the booklet warns they are much louder than normal
program material. Fine straight into the UPL; not through an amplifier into speakers.

**Where to get it:** the physical disc (R&S accessory, long discontinued); rips have been
shared in the [diyAudio UPL renovation thread](https://www.diyaudio.com/community/threads/rohde-schwarz-r-s-upl-audio-analyzer-renovation.353461/).
