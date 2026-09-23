#!/usr/bin/env python3
"""
upl_capture.py - pull measurement data off an R&S UPL over RS232 (COM2).

Requires the UPL "Remote Control" option UPL-B4 (which you have) and the UPL's
COM2 configured for remote control. Speaks the exact SCPI dialect used by the
R&S example programs shipped on the UPL install media (IEC_EXAM/*.BAS,
RS232_BT.BAS): commands and replies are terminated with a single LF (\\n),
arrays come back comma-separated, and files come back as 488.2 block data.

UPL side setup (front panel, once):
  OPTIONS panel:
    - Remote control destination .......... COM2 (RS232)   [not IEC-BUS]
    - COM2: Parity NONE, Data 8, Stop 1, Handshake RTS/CTS, Baud 115200 (confirmed working;
      set on the OPTIONS panel -- it's listed there even though older docs said 56000 was the max)
  Use an R&S 1050.0346 cable or an equivalent 9-pin null-modem cable with full
  RTS/CTS handshake, via a USB-serial adapter that exposes real RTS/CTS.

Examples:
  python upl_capture.py --port COM4 probe
  python upl_capture.py --port COM4 read
  python upl_capture.py --port COM4 sweep -o sweep.csv
  python upl_capture.py --port COM4 nsweep --start 20 --stop 20000 --points 40 -o fr.csv
  python upl_capture.py --port COM4 storetrace "C:\\UPL\\FR.EXP" --xaxis
  python upl_capture.py --port COM4 getfile "C:\\UPL\\MYTRACE.EXP" -o MYTRACE.exp
  python upl_capture.py --port COM4 raw "SENS:DATA?"

Offline: every subcommand accepts --dry-run, which swaps the serial link for a
stub that prints the exact SCPI it would send and answers queries with canned
values. No instrument, no --port needed. `seqcheck` asserts the emitted
sequences still match the documented ones.
"""

import argparse
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    sys.exit("pyserial is required.  Install with:  python -m pip install pyserial")


class UPL:
    def __init__(self, port, baud=115200, timeout=10.0):
        # 8 data bits, no parity, 1 stop, hardware RTS/CTS handshake -- per RS232_BT.BAS
        self.ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            rtscts=True,
            timeout=timeout,
        )
        time.sleep(0.1)
        self.ser.reset_input_buffer()

    def write(self, cmd):
        """Send one command, LF-terminated (the UPL's Comout)."""
        self.ser.write(cmd.encode("latin1") + b"\n")
        self.ser.flush()

    def _read_until_lf(self):
        """Read single bytes until LF, return text without the LF (the UPL's Comin$)."""
        buf = bytearray()
        while True:
            b = self.ser.read(1)
            if not b:
                raise TimeoutError("no LF-terminated reply from UPL (check cable, COM2 remote, handshake)")
            if b == b"\n":
                break
            buf += b
        return buf.decode("latin1").strip()

    def query(self, cmd):
        self.write(cmd)
        return self._read_until_lf()

    def read_block(self, cmd):
        """Query returning 488.2 definite-length block  #<n><len><bytes>  (MMEM:DATA?)."""
        self.write(cmd)
        if self.ser.read(1) != b"#":
            raise ValueError("expected '#' at start of block reply")
        n = int(self.ser.read(1).decode("latin1"))
        length = int(self.ser.read(n).decode("latin1"))
        data = bytearray()
        while len(data) < length:
            chunk = self.ser.read(length - len(data))
            if not chunk:
                raise TimeoutError("short block read")
            data += chunk
        self.ser.read(1)  # trailing LF
        return bytes(data)

    def set_timeout(self, seconds):
        """Raise/lower the reply timeout (a native sweep can block for minutes)."""
        self.ser.timeout = seconds

    def drain(self, settle=0.3):
        """Discard any late reply. After a query times out, the UPL may still answer
        it; without this, that stale reply would be read as the answer to the
        *next* query and every value after it would be shifted by one."""
        time.sleep(settle)
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()


class UPLGPIB:
    """Same interface as UPL, over IEC/IEEE-488 through a VISA library (the
    Agilent/Keysight 82357B needs Keysight IO Libraries -- pyvisa-py cannot
    drive it). Resource names look like GPIB0::20::INSTR; R&S examples use
    address 20. Put the UPL in OPTIONS -> Remote via -> IEC.

    With SCPI on GPIB, the UPL's COM2 is free for SNDFILE.BAS -- the setup
    App Note 1GA42 assumes -- so no port contention and no Remote toggling."""

    def __init__(self, resource, timeout=10.0):
        import pyvisa
        self.inst = pyvisa.ResourceManager().open_resource(resource)
        self.inst.write_termination = "\n"
        self.inst.read_termination = "\n"
        self.inst.timeout = int(timeout * 1000)
        self.inst.clear()

    def write(self, cmd):
        self.inst.write(cmd)

    def query(self, cmd):
        import pyvisa
        try:
            return self.inst.query(cmd).strip()
        except pyvisa.errors.VisaIOError as e:
            if e.error_code == pyvisa.constants.StatusCode.error_timeout:
                raise TimeoutError(f"no reply from UPL over GPIB to {cmd!r}") from e
            raise

    def read_block(self, cmd):
        """488.2 definite-length block. EOI ends the message on GPIB, so no LF
        framing problem here (unlike RS-232)."""
        self.inst.write(cmd)
        raw = self.inst.read_raw()
        if raw[:1] != b"#":
            raise ValueError("expected '#' at start of block reply")
        n = int(raw[1:2])
        length = int(raw[2:2 + n])
        return bytes(raw[2 + n:2 + n + length])

    def set_timeout(self, seconds):
        self.inst.timeout = int(seconds * 1000)

    def drain(self, settle=0.3):
        time.sleep(settle)
        self.inst.clear()

    def close(self):
        self.inst.close()


def connect(port, baud=115200, timeout=10.0):
    """UPL over RS-232 for 'COMn' / '/dev/tty*', over GPIB for a VISA resource
    name ('GPIB0::20::INSTR'), so every tool takes either via --port."""
    if port.upper().startswith("GPIB"):
        return UPLGPIB(port, timeout)
    return UPL(port, baud, timeout)


class DryRunUPL:
    """Offline stand-in for UPL: records every command, answers queries from a
    canned table. Lets the whole tool be exercised -- and the exact SCPI
    sequence reviewed -- without an instrument on the other end."""

    IDN = "ROHDE & SCHWARZ, UPL, 3.06, 0.33"

    def __init__(self, points=8, echo=True, fft_lines=None, fft_res=5.859375, fft_start=0.0):
        self.sent = []
        self.points = points
        self.echo = echo
        # When fft_lines is set the stub models the 1024-line block limit and
        # DISP:TRAC:IND paging, so the FFT readout path can be tested offline.
        self.fft_lines = fft_lines
        self.fft_res = fft_res
        self.fft_start = fft_start
        self.block = 0
        # Simulated DIAG:DEV: table sizes per selector. Selecting an unknown one,
        # or addressing past the end, queues an error for the next SYST:ERR? --
        # which is how the real instrument is expected to signal "end of table".
        self.diag_tables = {"SERN": 2, "CAGEN": 6, "CANLR0": 4, "CLDG": 3, "CDPHASE": 2, "INSTKEY": 2}
        self.diag_dev = None
        self.diag_addr = 0
        self.pending_error = None

    def _block_slice(self):
        lo = self.block * FFT_BLOCK
        hi = min(lo + FFT_BLOCK, self.fft_lines)
        return lo, max(lo, hi)

    # --- canned data -------------------------------------------------------
    def _freqs(self):
        import math
        lo, hi, n = 20.0, 20000.0, self.points
        if n == 1:
            return [lo]
        step = (math.log10(hi) - math.log10(lo)) / (n - 1)
        return [round(10 ** (math.log10(lo) + i * step), 4) for i in range(n)]

    def _levels(self):
        return [round(0.9 + 0.01 * i, 5) for i in range(self.points)]

    def _reply(self, cmd):
        c = cmd.strip().upper()
        if c.startswith("*IDN?"):
            return self.IDN
        if c.startswith("*OPC?"):
            return "1"
        if c.startswith("SYST:ERR"):
            err, self.pending_error = self.pending_error, None
            return err or '0,"No error"'
        if c.startswith("DIAG:DEV:DATA?"):
            # plausible-looking words, distinct per table and address
            return str(1000 * (list(self.diag_tables).index(self.diag_dev) + 1) + self.diag_addr) \
                if self.diag_dev in self.diag_tables else "0"
        if c.startswith("CALC:TRAN:FREQ:RES"):
            return f"{self.fft_res} Hz"
        if c.startswith("CALC:TRAN:FREQ:SPAN"):
            return f"{(self.fft_lines or 0) * self.fft_res} Hz"
        if c.startswith("CALC:TRAN:FREQ:STAR"):
            return f"{self.fft_start} Hz"
        if c.startswith("CALC:TRAN:FREQ:STOP"):
            return f"{self.fft_start + (self.fft_lines or 0) * self.fft_res} Hz"
        if self.fft_lines is not None and (c.startswith("TRAC? ") or c.startswith("TRAC:POIN?")):
            lo, hi = self._block_slice()
            if c.startswith("TRAC:POIN?"):
                return str(hi - lo)
            if c.startswith("TRAC? LIST"):
                return ",".join(f"{self.fft_start + i * self.fft_res:.4f}" for i in range(lo, hi))
            return ",".join(f"{1e-5 + (1.0 if i == 512 else 0.0):.6g}" for i in range(lo, hi))
        if c.startswith("TRAC:POIN?") or c.startswith("TRACE:POIN"):
            return str(self.points)
        if c.startswith("TRAC? LIST") or c.startswith("SOUR:LIST:FREQ?"):
            return ",".join(str(f) for f in self._freqs())
        if c.startswith("TRAC? "):
            return ",".join(str(v) for v in self._levels())
        if c.startswith("MMEM:CAT"):
            return '"FR.EXP",,4096,"FRX.EXP",,2048'
        if c.startswith("MMEM:STOR:INFO?"):
            return "4096 bytes sent C:\\UPL\\FR.EXP"
        if c.startswith("MMEM:CHECK"):
            return "0"
        if c.startswith("INST"):
            return "ANLG"
        if c.startswith("INP:TYPE?"):
            return "INT"
        if c.endswith("?"):
            return "1.0"
        return ""

    # --- same surface as UPL ----------------------------------------------
    def write(self, cmd):
        self.sent.append(cmd)
        c = cmd.strip().upper()
        if c.startswith("DISP:TRAC:IND"):
            self.block = int(cmd.split()[-1])
        elif c.startswith("DIAG:DEV:ADDR"):
            self.diag_addr = int(cmd.split()[-1])
            if self.diag_dev in self.diag_tables and self.diag_addr >= self.diag_tables[self.diag_dev]:
                self.pending_error = '-222,"Data out of range"'
        elif c.startswith("DIAG:DEV "):
            self.diag_dev = c.split()[-1]
            self.diag_addr = 0
            if self.diag_dev not in self.diag_tables:
                self.pending_error = '-224,"Illegal parameter value"'
        if self.echo:
            print(f"  ->  {cmd}")

    def drain(self, settle=0.0):
        pass

    def query(self, cmd):
        self.sent.append(cmd)
        reply = self._reply(cmd)
        if self.echo:
            print(f"  ->  {cmd}")
            print(f"  <-  {reply}")
        return reply

    def read_block(self, cmd):
        self.sent.append(cmd)
        if self.echo:
            print(f"  ->  {cmd}   (block read)")
        return b"(dry-run: no file data)\n"

    def set_timeout(self, seconds):
        if self.echo:
            print(f"  ..  reply timeout -> {seconds:g}s")

    def close(self):
        pass


def parse_values(reply, what):
    """Parse a comma-separated ASCII block reply into floats.

    The UPL answers with text like 'No Values' when the trace buffer was never
    filled -- which is exactly what happens if DISP:TRAC:FEED was not set or the
    sweep went to the Z axis (SWE2) instead of the X axis (SWE1). Catch that and
    say so, rather than dying in float()."""
    reply = reply.strip()
    if not reply:
        raise ValueError(f"{what}: empty reply from UPL")
    parts = [v.strip() for v in reply.split(",") if v.strip() != ""]
    try:
        return [float(v) for v in parts]
    except ValueError:
        raise ValueError(
            f"{what}: UPL replied {reply!r} instead of numbers.\n"
            "  The trace buffer is empty. Usual causes:\n"
            "    - DISP:TRAC:FEED was never set (the trace has no source feeding it);\n"
            "    - the sweep used SOUR:FREQ:MODE SWE2 (frequency on the Z axis) "
            "instead of SWE1 (X axis);\n"
            "    - no sweep has run yet, or it was aborted.\n"
            "  The 'nsweep' subcommand sets all of this up for you."
        )


def cmd_probe(upl, args):
    idn = upl.query("*IDN?")
    print("*IDN? ->", idn)
    if "UPL" in idn.upper():
        print("OK: remote control (UPL-B4) is active on this port.")
        return 0
    print("WARNING: reply does not contain 'UPL'. Remote not confirmed.")
    return 1


def cmd_read(upl, args):
    # Mapping straight from IEC_EXAM/EXAM1.BAS
    fields = [
        ("CH1 function",   "SENS:DATA?"),
        ("CH1 input peak", "SENS2:DATA?"),
        ("CH1 frequency",  "SENS3:DATA?"),
        ("CH1 phase",      "SENS4:DATA?"),
        ("CH2 function",   "SENS:DATA2?"),
        ("CH2 input peak", "SENS2:DATA2?"),
    ]
    if not args.no_trigger:
        upl.write("INIT;*WAI")
        upl.query("*OPC?") if args.opc else time.sleep(0.2)
    for label, scpi in fields:
        print(f"{label:16s}: {upl.query(scpi)}")
    return 0


def cmd_sweep(upl, args):
    # From IEC_EXAM/EXAM2.BAS: single sweep, then trace + x-axis frequency list.
    upl.write("INIT:CONT OFF")
    upl.write("INIT;*WAI")
    upl.query("*OPC?") if args.opc else time.sleep(0.5)

    npts = int(float(upl.query("TRAC:POIN? TRAC1")))
    levels = parse_values(upl.query("TRAC? TRAC1"), "TRAC? TRAC1")
    freqs = parse_values(upl.query("SOUR:LIST:FREQ?"), "SOUR:LIST:FREQ?")

    rows = max(len(levels), len(freqs))
    out = open(args.output, "w") if args.output else sys.stdout
    out.write("point,frequency_Hz,level\n")
    for i in range(rows):
        f = freqs[i] if i < len(freqs) else ""
        l = levels[i] if i < len(levels) else ""
        out.write(f"{i+1},{f},{l}\n")
    if args.output:
        out.close()
        print(f"Wrote {rows} points (declared {npts}) to {args.output}")
    return 0


def cmd_autoexport(upl, args):
    """One shot: (optionally load a setup), trigger a fresh single sweep, and pull the
    trace(s) + x-axis straight over the wire to a timestamped CSV -- the same numbers
    the UPL's STORE TRACE LIST / EXPORT would write, but with no file created on the
    instrument. Uses only commands verified from the R&S examples (EXAM2/EXAM3)."""
    import datetime

    def grab_trace(sel):
        return parse_values(upl.query(f"TRAC? {sel}"), f"TRAC? {sel}")

    reps = args.repeat if args.repeat and args.repeat > 0 else 1
    for rep in range(reps):
        if args.setup:
            upl.write(f"MMEM:LOAD:STAT 0,'{args.setup}'")
        # ASCii format => TRAC? returns readable comma-separated numbers
        upl.write("FORM ASCii")
        upl.write("INIT:CONT OFF")
        upl.write("INIT;*WAI")
        upl.query("*OPC?") if args.opc else time.sleep(args.settle)

        npts = int(float(upl.query("TRAC:POIN? TRAC1")))
        freqs = parse_values(upl.query("SOUR:LIST:FREQ?"), "SOUR:LIST:FREQ?")
        lev1 = grab_trace("TRAC1")
        lev2 = grab_trace("TRAC2") if args.both else None

        ts = datetime.datetime.now()
        if args.output:
            name = ts.strftime(args.output) if "%" in args.output else args.output
        else:
            name = ts.strftime("upl_%Y%m%d_%H%M%S.csv")

        rows = max(len(freqs), len(lev1), len(lev2) if lev2 else 0)
        with open(name, "w") as out:
            out.write(f"# R&S UPL export  {ts.isoformat()}  points={npts}\n")
            out.write("# values in basic units (e.g. V for level); scale as needed\n")
            hdr = "point,frequency_Hz,ch1" + (",ch2" if lev2 else "") + "\n"
            out.write(hdr)
            for i in range(rows):
                f = freqs[i] if i < len(freqs) else ""
                a = lev1[i] if i < len(lev1) else ""
                line = f"{i+1},{f},{a}"
                if lev2 is not None:
                    line += f",{lev2[i] if i < len(lev2) else ''}"
                out.write(line + "\n")
        print(f"[{rep+1}/{reps}] wrote {rows} points -> {name}")
        if rep + 1 < reps:
            time.sleep(max(0.0, args.interval))
    return 0


STATE_TMP = "C:\\UPL\\USER\\UPLTMP.SCO"


class preserve_state:
    """Snapshot the UPL's complete setup, restore it afterwards, delete the scratch file.

    Lifted straight from R&S's own shipped FLAT_GEN.BAS macro, which brackets its
    calibration exactly this way:

        MMEM:STOR:STAT 2,'\\upl\\user\\upl.tmp'    ; snapshot
        MMEM:LOAD:STAT 0,'...flat_gen.sac'        ; reconfigure freely
        ... measure ...
        MMEM:LOAD:STAT 2,'\\upl\\user\\upl.tmp'    ; restore
        MMEM:DEL '\\upl\\user\\upl.tmp'

    Mode 2 is the COMPLETE instrument setup (.SCO); mode 0 is the current setup
    (.SAC) -- Vol.2 sec 3.10.5.1. This is a much better neighbour than opening with
    a bare `*RST`, which throws away whatever the user had configured by hand.
    `*RST` inside the block is still fine: the snapshot is what puts it back.

    Opt-in for now (`--preserve`): it writes a file to the instrument's disk, and
    like everything else added on 2026-09-23 it has not been run against hardware.
    Restore is best-effort -- a failure to restore must not mask a measurement error."""

    def __init__(self, upl, path=STATE_TMP, enabled=True):
        self.upl, self.path, self.enabled = upl, path, enabled

    def __enter__(self):
        if self.enabled:
            self.upl.write(f"MMEM:STOR:STAT 2,'{self.path}'")
            err = self.upl.query("SYST:ERR?")
            if not err.startswith("0,"):
                print(f"WARNING: could not snapshot instrument state ({err}); "
                      "continuing without restore.", file=sys.stderr)
                self.enabled = False
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.enabled:
            try:
                self.upl.write(f"MMEM:LOAD:STAT 2,'{self.path}'")
                self.upl.write(f"MMEM:DEL '{self.path}'")
            except Exception as e:      # never mask the real error
                print(f"WARNING: failed to restore instrument state: {e}", file=sys.stderr)
        return False


FFT_BLOCK = 1024          # TRAC? never returns more than 1024 values (Vol.2 sec 3.15.11.2.1)
FFT_MAX_BLOCKS = 8        # DISP:TRAC:IND 0..7 for FFT block paging (Vol.2 sec 3.15.11.2.2)


def fft_line_count(size, zoom=1, digital=False):
    """Displayable FFT lines, per Vol.1 sec 2.6.5.12 (p.2.221).

        Zooming OFF, analog : size * 117/256      (8192 -> 3744)
        Zooming OFF, digital: size * 127/256      (8192 -> 4064)
        Zooming ON          : size * 117/256 * 2  (8192 -> 7488, the manual's own example)

    The FFT is complex after the zoom shift, which is why you never get size/2.
    With Zooming ON the real count can be *lower* than this if an eccentric CENTer
    pushes some lines into negative frequencies -- so treat it as an upper bound
    and page until a block comes back short."""
    base = size * (127 if digital else 117) // 256
    return base * 2 if zoom > 1 else base


def read_fft(upl, max_blocks=FFT_MAX_BLOCKS, sel="TRAC1", verbose=False):
    """Read a complete FFT, paging over the 1024-line block limit.

    THE thing to know about FFT readout on this instrument: `TRAC?` returns at
    most 1024 values, full stop. An 8k FFT has 3744 lines (analog, unzoomed) or
    7488 (zoomed), so a single `TRAC?` gives you only the FIRST block -- the
    bottom ~6 kHz of the spectrum at 48 kHz sampling, silently, with no error.
    `DISP:TRAC:IND <n>` selects which block the next `TRAC?` returns
    (Vol.2 sec 3.15.11.2.2, block index 0..7).

    Take the X axis from `TRAC? LIST1` per block rather than computing
    bin*resolution: it is correct for zoomed FFTs too, where the block does not
    start at 0 Hz.

    Returns (freqs, levels) concatenated across blocks."""
    freqs, levels = [], []
    for blk in range(max_blocks):
        upl.write(f"DISP:TRAC:IND {blk}")
        y = parse_values(upl.query(f"TRAC? {sel}"), f"TRAC? {sel} (block {blk})")
        x = parse_values(upl.query("TRAC? LIST1"), f"TRAC? LIST1 (block {blk})")
        n = min(len(x), len(y))
        freqs.extend(x[:n])
        levels.extend(y[:n])
        if verbose:
            span = f"{x[0]:.1f}-{x[-1]:.1f} Hz" if n else "empty"
            print(f"  block {blk}: {n} lines  {span}", file=sys.stderr)
        if n < FFT_BLOCK:       # short block => that was the last one
            break
    upl.write("DISP:TRAC:IND 0")  # leave the block index where we found it
    return freqs, levels


FEED_CHOICES = {
    # DISP:TRAC[1|2]:FEED -- Vol.2 sec 3.10.6, p.3.183. The trace records nothing
    # until one of these is fed to it; this is what TRACe[:DATA] footnote 1 means
    # by "depending on DISPlay:TRACe:FEED and of SENSe1:FUNCtion".
    "func1":   "SENSe1:DATA1",   # measurement function (SENS1:FUNC), channel 1
    "func2":   "SENSe1:DATA2",   # same function, channel 2
    "inprms1": "SENSe2:DATA1",   # input RMS ch1 (meaningful for THD / THDN)
    "inprms2": "SENSe2:DATA2",   # input RMS ch2
    "freq1":   "SENSe3:DATA1",   # frequency meter ch1
    "freq2":   "SENSe3:DATA2",   # freq / phase / group delay ch2, per SENS3:FUNC
    "hold":    "HOLD",
    "off":     "OFF",
}


def cmd_nsweep(upl, args):
    """Drive the UPL's OWN sweep engine and read the result back over the wire.

    Sequence is the manual's frequency-sweep example (Vol.2 sec 3.15.9.1, p.3.305)
    plus the block-data rules from sec 3.10.10, cross-checked against R&S's own
    app-note programs (1ga16_1l IMPEDANC/SOUND, 1GA21 CDTEST, 1GA24 TUNTEST,
    1GA30 Adctest). Unlike the host-side stepping in dcx_sweep.py, the whole
    sweep runs inside the instrument -- far fewer round trips.

    NOT YET VERIFIED AGAINST HARDWARE (written 2026-09-23 from the documentation
    after the earlier live attempt failed on SWE2 + missing FEED). Run with
    --dry-run first to inspect the sequence."""
    with preserve_state(upl, args.state_file, enabled=args.preserve):
        return _nsweep(upl, args)


def _nsweep(upl, args):
    feed = FEED_CHOICES[args.feed]

    if args.reset:
        upl.write("*RST;*WAI")
    if args.setup:
        # R&S's own FLAT_GEN.BAS configures a measurement this way rather than by
        # sending every panel setting: MMEM:LOAD:STAT 0,'<name>.SAC'.
        upl.write(f"MMEM:LOAD:STAT 0,'{args.setup}'")

    # ASCii => TRAC? replies are comma-separated text. FORM REAL would return a
    # 488.2 binary block with no delimiter, which has no EOI to end it on RS232.
    upl.write("FORM ASC")
    upl.write(f"SENS1:FUNC '{args.func}'")
    if args.volt is not None:
        upl.write(f"SOUR:VOLT {args.volt} V")

    upl.write("DISP:TRAC:OPER CURV")
    upl.write(f"DISP:TRAC:FEED '{feed}'")
    if args.both:
        upl.write("DISP:TRAC2:FEED 'SENSe1:DATA2'")
    upl.write(f"DISP:TRAC:X:SPAC {'LOG' if args.spacing == 'log' else 'LIN'}")

    # SWE1 = frequency on the X axis. SWE2 puts it on the Z axis, which leaves
    # TRAC1 empty -- that was the bug in the earlier attempt.
    # Each sweep-parameter command takes 2-3 s to process (measured live
    # 2026-09-23). Sent back to back, the UPL drops CTS mid-line while busy and
    # the PL2303 adapter then doubled a byte ("FREQQ", "MOODE") every run. So:
    # one command per line, and *OPC? after each so nothing is in flight while
    # the instrument is busy. R&S's examples use the compound form over GPIB.
    upl.set_timeout(args.sweep_timeout)
    try:
        for c in ("SOUR:SWE:MODE AUTO",
                  "SOUR:FREQ:MODE SWE1",
                  f"SOUR:FREQ:STAR {args.start} HZ",
                  f"SOUR:FREQ:STOP {args.stop} HZ",
                  f"SOUR:SWE:FREQ:SPAC {'LOG' if args.spacing == 'log' else 'LIN'}",
                  f"SOUR:SWE:FREQ:POIN {args.points}"):
            upl.write(c)
            upl.query("*OPC?")
        upl.write("DISP:CONF AP")
        err = upl.query("SYST:ERR?")
    finally:
        upl.set_timeout(args.timeout)
    if not err.startswith("0,"):
        print(f"WARNING: UPL reported an error after configuration: {err}", file=sys.stderr)

    # INIT:CONT OFF;*WAI is itself the single-sweep trigger in every R&S example.
    # A 40-point sweep took ~17s live, so the reply timeout must be generous.
    print(f"Sweeping {args.points} points {args.start}-{args.stop} Hz ...", file=sys.stderr)
    upl.set_timeout(args.sweep_timeout)
    t0 = time.time()
    try:
        upl.write("INIT:CONT OFF;*WAI")
        upl.query("*OPC?")
    finally:
        upl.set_timeout(args.timeout)
    print(f"  sweep finished in {time.time() - t0:.1f}s", file=sys.stderr)

    npts = int(float(upl.query("TRAC:POIN? TRAC1")))
    if npts == 0:
        raise ValueError(
            "TRAC:POIN? TRAC1 returned 0 -- the trace buffer is empty.\n"
            "  Check SYST:ERR? and that DISP:TRAC:FEED took effect for this "
            "measurement function."
        )
    levels = parse_values(upl.query("TRAC? TRAC1"), "TRAC? TRAC1")
    freqs = parse_values(upl.query("TRAC? LIST1"), "TRAC? LIST1")
    lev2 = parse_values(upl.query("TRAC? TRAC2"), "TRAC? TRAC2") if args.both else None

    if args.restore:
        # Leaving the generator in sweep mode changes what a plain SOUR:FREQ does
        # afterwards -- the cleanup gotcha recorded in CLAUDE.md.
        # SOUR:SWE:MODE takes only MANual|AUTO -- "OFF" is -141 (live
        # 2026-09-23). FREQ:MODE FIX alone is what ends the sweep.
        upl.write("SOUR:FREQ:MODE FIX")

    rows = max(len(freqs), len(levels), len(lev2) if lev2 else 0)
    out = open(args.output, "w") if args.output else sys.stdout
    try:
        out.write(f"# R&S UPL native sweep  func={args.func}  feed={feed}  points={npts}\n")
        out.write("point,frequency_Hz,ch1" + (",ch2" if lev2 else "") + "\n")
        for i in range(rows):
            f = freqs[i] if i < len(freqs) else ""
            a = levels[i] if i < len(levels) else ""
            line = f"{i+1},{f},{a}"
            if lev2 is not None:
                line += f",{lev2[i] if i < len(lev2) else ''}"
            out.write(line + "\n")
    finally:
        if args.output:
            out.close()
            print(f"Wrote {rows} points to {args.output}")
    return 0


FFT_SIZES = {"256": "S256", "512": "S512", "1024": "S1K", "2048": "S2K", "4096": "S4K", "8192": "S8K"}


def cmd_fft(upl, args):
    """Run one FFT and read the WHOLE spectrum, paging the 1024-line block limit.

    Replaces the single `TRAC? TRAC1` that silently truncates to the first
    1024 lines. See read_fft() for the mechanism and CLAUDE.md for the history."""
    with preserve_state(upl, args.state_file, enabled=args.preserve):
        return _fft(upl, args)


def _fft(upl, args):
    if args.reset:
        upl.write("*RST;*WAI")
    upl.write("FORM ASC")
    upl.write("SENS1:FUNCtion 'FFT'")
    upl.write(f"CALC:TRAN:FREQ:FFT {FFT_SIZES[args.size]}")
    upl.write(f"CALC:TRAN:FREQ:WINDow {args.window}")
    # Over the bus you set the ZOOM FACTOR, never the SPAN -- "contrary to the
    # manual mode ... SPAN can only be read in but not entered" (Vol.2 p.3.134).
    # ZOOM before CENT, the order the shipped DEMO.BAS uses.
    upl.write(f"CALC:TRAN:FREQ:ZOOM {args.zoom}")
    if args.center is not None:
        upl.write(f"CALC:TRAN:FREQ:CENT {args.center} HZ")

    err = upl.query("SYST:ERR?")
    if not err.startswith("0,"):
        print(f"WARNING: UPL reported an error after FFT setup: {err}", file=sys.stderr)

    res = upl.query("CALC:TRAN:FREQ:RES?")
    span = upl.query("CALC:TRAN:FREQ:SPAN?")
    start = upl.query("CALC:TRAN:FREQ:STAR?")
    stop = upl.query("CALC:TRAN:FREQ:STOP?")
    expect = fft_line_count(int(args.size), args.zoom, digital=args.digital)
    print(f"FFT {args.size} zoom={args.zoom} res={res} span={span} start={start} stop={stop}",
          file=sys.stderr)
    print(f"  expecting up to {expect} lines = {-(-expect // FFT_BLOCK)} block(s) of {FFT_BLOCK}",
          file=sys.stderr)

    upl.set_timeout(args.fft_timeout)
    try:
        upl.write("INIT:CONT OFF;*WAI")
        upl.query("*OPC?")
    finally:
        upl.set_timeout(args.timeout)

    freqs, levels = read_fft(upl, max_blocks=args.max_blocks, verbose=True)
    if len(freqs) <= FFT_BLOCK and expect > FFT_BLOCK:
        print(f"WARNING: got {len(freqs)} lines but expected ~{expect}. "
              "Block paging may not be working on this firmware.", file=sys.stderr)

    out = open(args.output, "w") if args.output else sys.stdout
    try:
        out.write(f"# R&S UPL FFT  size={args.size} zoom={args.zoom} window={args.window} "
                  f"res={res} lines={len(freqs)}\n")
        out.write("freq_Hz,level\n")
        for f, v in zip(freqs, levels):
            out.write(f"{f:.4f},{v}\n")
    finally:
        if args.output:
            out.close()
            print(f"Wrote {len(freqs)} lines to {args.output}")
    return 0


TRACE_SEL = {"a": "TRACe1", "b": "TRACe2", "ab": "TR1And2"}


def cmd_storetrace(upl, args):
    """Have the UPL write its current trace to a file on its OWN disk.

    Vol.2 sec 3.10.5.1.1 "Loading and Storing Traces and Lists", used verbatim by
    four R&S app-note programs. This is the "save on the UPL, transfer later"
    half -- pair it with the SNDFILE / ser_in.py route to get the file to the PC.

    Format note from the manual: EXPort writes a bare text table (.EXP) that any
    editor or spreadsheet reads, but it carries no header info, so the UPL itself
    cannot load it back. Use ASCii or BIN if the file has to return to the
    instrument.

    NOT YET VERIFIED AGAINST HARDWARE (written 2026-09-23 from the documentation)."""
    fmt = {"exp": "EXPort", "asc": "ASCii", "bin": "BIN"}[args.format]
    upl.write(f"MMEM:STOR:FORM {fmt}")
    upl.write(f"MMEM:STOR:TRAC {TRACE_SEL[args.trace]},'{args.remote}'")
    print(f"Stored trace {args.trace.upper()} as {fmt} -> {args.remote} (on the UPL)")

    if args.xaxis:
        xname = args.xaxis_name or _sibling(args.remote, "X")
        upl.write(f"MMEM:STOR:LIST LIST1,'{xname}'")
        print(f"Stored X-axis list -> {xname} (on the UPL)")

    err = upl.query("SYST:ERR?")
    print(f"SYST:ERR? -> {err}")
    if not err.startswith("0,"):
        print("WARNING: the store did not complete cleanly.", file=sys.stderr)
        return 1

    if args.verify:
        import os
        folder = os.path.dirname(args.remote) or None
        print("MMEM:CAT? ->", upl.query(f"MMEM:CAT? '{folder}'" if folder else "MMEM:CAT?"))

    print(
        "\nNext step -- getting it to the PC (App Note 1GA42_0E):\n"
        "  1. UPL: FILE panel -> Info Text (under STORE INSTRUMENT STATE) -> the path above\n"
        f"  2. PC:  python ser_in.py --port COMn out\\{_basename(args.remote)}\n"
        "  3. UPL: OPTIONS panel -> Exec Macro -> SELECT -> C:\\UPL\\USER\\SNDFILE.BAS -> ENTER\n"
        "  Start the PC listener BEFORE triggering SNDFILE."
    )
    return 0


# --- DIAG:DEV read-only dump -------------------------------------------------
#
# DIAG:DEV is undocumented. R&S's own selftest (SELFTEST_Program.TXT) uses it to
# read the serial number:  DIAG:DEV SERN ; DIAG:DEV:ADDR n ; DIAG:DEV:DATA?
# In UPL_UI.EXE's keyword table SERNumber sits among the selectors below, which
# look like calibration tables and the option key. Only SERN is proven.

DIAG_PROVEN = ("SERN",)
# Believed to be stored-state reads: calibration tables, the option key, a sensor.
DIAG_ALLOWED = ("SERN", "CAGEn", "CANLr0", "CLDG", "CDPHase", "INSTkey", "RTEMperature")
DIAG_DEFAULT = ("SERN", "CAGEn", "CANLr0", "CLDG", "CDPHase", "INSTkey")
# Refused outright: these sound like live hardware access (registers, pins,
# DSP memory, serial links, a DC output) where merely selecting them might act.
DIAG_REFUSED = {
    "REG": "register access", "PIN": "pin access", "ENPIN": "pin enable",
    "CALDCOUT": "DC output", "DSPA": "DSP A memory", "DSPB": "DSP B memory",
    "RX1": "serial link", "RX2": "serial link", "TX1": "serial link", "TX2": "serial link",
}


def _diag_query(upl, cmd):
    """The only way diagdump talks to DIAG:DEV:DATA -- and only as a query.
    A bare `DIAG:DEV:DATA <value>` would be a write into calibration storage."""
    if not cmd.rstrip().endswith("?"):
        raise RuntimeError(f"refusing non-query DIAG command: {cmd!r}")
    return upl.query(cmd)


def _err(upl):
    return upl.query("SYST:ERR?").strip()


def cmd_diagdump(upl, args):
    """READ-ONLY dump of the UPL's per-unit stored state via undocumented DIAG:DEV.

    For each selector: select it, then walk DIAG:DEV:ADDR 0,1,2,... reading
    DIAG:DEV:DATA? until the instrument reports an error (end of table), a read
    times out, or --max-addr is reached. Every step is followed by SYST:ERR?.
    Replies are recorded raw -- their format is unknown, so nothing is parsed.

    NOT YET RUN AGAINST HARDWARE. Try `--dry-run` first, then a real run with
    `--devices SERN` (the one proven selector) before the full default list."""
    import datetime
    import json

    devices = [d.strip() for d in args.devices.split(",")] if args.devices else list(DIAG_DEFAULT)
    allowed_upper = {d.upper(): d for d in DIAG_ALLOWED}
    for d in devices:
        if d.upper() in DIAG_REFUSED:
            raise SystemExit(f"refusing selector {d!r} ({DIAG_REFUSED[d.upper()]}): it may act on "
                             "live hardware. diagdump only reads stored-state tables.")
        if d.upper() not in allowed_upper:
            raise SystemExit(f"unknown selector {d!r}. Allowed: {', '.join(DIAG_ALLOWED)}")

    idn = upl.query("*IDN?").strip()
    start_err = _err(upl)
    if not start_err.startswith("0,"):
        print(f"note: error queue was not empty at start: {start_err} (drained)", file=sys.stderr)
        for _ in range(20):                       # drain anything left over
            if _err(upl).startswith("0,"):
                break

    rows, summary = [], {}
    for dev in devices:
        sel = "SERN" if dev.upper() == "SERN" else allowed_upper[dev.upper()]
        upl.write(f"DIAG:DEV {sel}")
        err = _err(upl)
        if not err.startswith("0,"):
            print(f"  {sel:13s} not accepted: {err}", file=sys.stderr)
            summary[sel] = {"status": "rejected", "error": err, "words": 0}
            continue
        words, stop = [], "max-addr"
        for addr in range(args.max_addr):
            upl.write(f"DIAG:DEV:ADDR {addr}")
            err = _err(upl)
            if not err.startswith("0,"):
                stop = f"address rejected at {addr}: {err}"
                break
            try:
                val = _diag_query(upl, "DIAG:DEV:DATA?").strip()
            except TimeoutError:
                upl.drain()
                stop = f"read timed out at {addr}"
                break
            err = _err(upl)
            if not err.startswith("0,"):
                stop = f"read error at {addr}: {err}"
                break
            words.append(val)
            rows.append((sel, addr, val))
        summary[sel] = {"status": "read", "words": len(words), "stop": stop, "values": words}
        preview = " ".join(words[:8]) + (" ..." if len(words) > 8 else "")
        print(f"  {sel:13s} {len(words):4d} words  [{stop}]  {preview}", file=sys.stderr)

    ts = datetime.datetime.now()
    base = args.output or ts.strftime("diagdump_%Y%m%d_%H%M%S")
    base = base[:-4] if base.lower().endswith((".csv", ".txt")) else base
    with open(base + ".csv", "w") as f:
        f.write(f"# UPL DIAG:DEV read-only dump  {ts.isoformat()}\n# *IDN? {idn}\n")
        f.write("device,addr,raw_value\n")
        for sel, addr, val in rows:
            f.write(f"{sel},{addr},{val}\n")
    with open(base + ".json", "w") as f:
        json.dump({"timestamp": ts.isoformat(), "idn": idn, "devices": summary}, f, indent=2)
    print(f"wrote {len(rows)} words -> {base}.csv / {base}.json", file=sys.stderr)
    print("Keep these files with the disk image: they are this unit's identity and calibration.",
          file=sys.stderr)
    return 0


def _basename(path):
    return path.replace("/", "\\").rsplit("\\", 1)[-1]


def _sibling(path, suffix):
    """C:\\UPL\\FR.EXP + 'X' -> C:\\UPL\\FRX.EXP (DOS 8.3: keep it short)."""
    head, _, tail = path.replace("/", "\\").rpartition("\\")
    stem, dot, ext = tail.partition(".")
    stem = (stem[:7] + suffix) if len(stem) >= 8 else stem + suffix
    return (head + "\\" if head else "") + stem + dot + ext


def cmd_catalog(upl, args):
    print(upl.query(f"MMEM:CAT? '{args.path}'" if args.path else "MMEM:CAT?"))
    return 0


def cmd_getfile(upl, args):
    upl.write("INIT:FORC STOP")  # stop measurement for clean transfer (per RS232_BT.BAS)
    data = upl.read_block(f"MMEM:DATA? '{args.remote}'")
    with open(args.output, "wb") as f:
        f.write(data)
    print(f"Pulled {len(data)} bytes from '{args.remote}' -> {args.output}")
    try:
        print("UPL checksum:", upl.query(f"MMEM:CHECK? '{args.remote}'"))
    except Exception:
        pass
    return 0


def cmd_raw(upl, args):
    if args.command.rstrip().endswith("?"):
        print(upl.query(args.command))
    else:
        upl.write(args.command)
    return 0


def cmd_seqcheck(upl, args):
    """Run the new sequences against the dry-run stub and assert the SCPI matches
    what the manual and the R&S app-note programs document. Pure offline check --
    catches a regression in the command order or spelling without an instrument."""
    import argparse as _ap
    failures = []

    def check(name, sent, required, forbidden=()):
        joined = "\n".join(sent)
        for token in required:
            if token not in joined:
                failures.append(f"{name}: missing {token!r}")
        for token in forbidden:
            if token in joined:
                failures.append(f"{name}: should not send {token!r}")
        print(f"  {name}: {len(sent)} commands")

    # --- nsweep ---
    stub = DryRunUPL(points=6, echo=False)
    ns = _ap.Namespace(
        func="RMS", feed="func1", start=20, stop=20000, points=40, spacing="log",
        volt=None, both=False, reset=True, restore=True, output=None, setup=None,
        timeout=10.0, sweep_timeout=120.0, preserve=False, state_file=STATE_TMP,
    )
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        cmd_nsweep(stub, ns)
    check(
        "nsweep", stub.sent,
        required=[
            "FORM ASC",
            "DISP:TRAC:OPER CURV",
            "DISP:TRAC:FEED 'SENSe1:DATA1'",
            "SOUR:SWE:MODE AUTO",
            "SOUR:FREQ:MODE SWE1",
            "SOUR:SWE:FREQ:POIN 40",
            "DISP:CONF AP",
            "INIT:CONT OFF;*WAI",
            "TRAC:POIN? TRAC1",
            "TRAC? TRAC1",
            "TRAC? LIST1",
            "SOUR:FREQ:MODE FIX",
        ],
        # compound sweep commands corrupt on the PL2303; SWE:MODE has no OFF
        forbidden=["SWE2", "FORM REAL", "SWE:MODE OFF", "AUTO;:SOUR"],
    )
    # every slow sweep command must be followed by *OPC? before the next write
    i = stub.sent.index("SOUR:SWE:FREQ:POIN 40")
    if stub.sent[i + 1] != "*OPC?":
        failures.append("nsweep: sweep-parameter commands must each be followed by *OPC?")
    # FEED must precede the trigger, or the trace records nothing.
    if stub.sent.index("DISP:TRAC:FEED 'SENSe1:DATA1'") > stub.sent.index("INIT:CONT OFF;*WAI"):
        failures.append("nsweep: DISP:TRAC:FEED must be sent before the sweep trigger")

    # --- storetrace ---
    stub2 = DryRunUPL(echo=False)
    st = _ap.Namespace(
        remote="C:\\UPL\\FR.EXP", format="exp", trace="a",
        xaxis=True, xaxis_name=None, verify=False,
    )
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        cmd_storetrace(stub2, st)
    check(
        "storetrace", stub2.sent,
        required=[
            "MMEM:STOR:FORM EXPort",
            "MMEM:STOR:TRAC TRACe1,'C:\\UPL\\FR.EXP'",
            "MMEM:STOR:LIST LIST1,'C:\\UPL\\FRX.EXP'",
        ],
    )
    if stub2.sent.index("MMEM:STOR:FORM EXPort") > stub2.sent.index("MMEM:STOR:TRAC TRACe1,'C:\\UPL\\FR.EXP'"):
        failures.append("storetrace: MMEM:STOR:FORM must be sent before MMEM:STOR:TRAC")

    # --- fft block paging ---
    stub3 = DryRunUPL(echo=False, fft_lines=fft_line_count(8192))
    ff = _ap.Namespace(
        size="8192", zoom=1, center=None, window="BLACkman_harris", digital=False,
        max_blocks=FFT_MAX_BLOCKS, reset=True, output=None,
        timeout=10.0, fft_timeout=120.0, preserve=False, state_file=STATE_TMP,
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        cmd_fft(stub3, ff)
    check(
        "fft", stub3.sent,
        required=["FORM ASC", "SENS1:FUNCtion 'FFT'", "CALC:TRAN:FREQ:FFT S8K",
                  "CALC:TRAN:FREQ:ZOOM 1", "INIT:CONT OFF;*WAI",
                  "DISP:TRAC:IND 0", "DISP:TRAC:IND 1", "DISP:TRAC:IND 2", "DISP:TRAC:IND 3"],
        forbidden=["CALC:TRAN:FREQ:SPAN "],   # SPAN is query-only over the bus
    )
    got = sum(1 for line in buf.getvalue().splitlines() if line and line[0].isdigit())
    if got != 3744:
        failures.append(f"fft: read {got} lines, expected 3744 (block paging broken)")
    else:
        print(f"  fft: paged {got} lines across 4 blocks (single TRAC? would give 1024)")
    # A block index must be selected before each read, or every block returns block 0.
    if "DISP:TRAC:IND 1" in stub3.sent:
        i_ind, i_trac = stub3.sent.index("DISP:TRAC:IND 1"), None
        for j in range(i_ind + 1, len(stub3.sent)):
            if stub3.sent[j].startswith("TRAC? TRAC"):
                i_trac = j
                break
        if i_trac is None:
            failures.append("fft: no TRAC? read after selecting block 1")

    if fft_line_count(8192) != 3744 or fft_line_count(8192, digital=True) != 4064 \
            or fft_line_count(8192, zoom=2) != 7488:
        failures.append("fft_line_count: disagrees with Vol.1 sec 2.6.5.12")
    else:
        print("  fft_line_count: 3744 analog / 4064 digital / 7488 zoomed, per Vol.1 2.6.5.12")

    # --- preserve_state brackets the measurement (FLAT_GEN.BAS idiom) ---
    stub4 = DryRunUPL(points=6, echo=False)
    ns2 = _ap.Namespace(**{**vars(ns), "preserve": True})
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        cmd_nsweep(stub4, ns2)
    snap = f"MMEM:STOR:STAT 2,'{STATE_TMP}'"
    rest = f"MMEM:LOAD:STAT 2,'{STATE_TMP}'"
    check("preserve", stub4.sent, required=[snap, rest, f"MMEM:DEL '{STATE_TMP}'"])
    if snap in stub4.sent and rest in stub4.sent:
        if stub4.sent.index(snap) != 0:
            failures.append("preserve: the snapshot must be the very first command")
        if stub4.sent.index(rest) < stub4.sent.index("INIT:CONT OFF;*WAI"):
            failures.append("preserve: restore must come after the measurement")
        if "*RST;*WAI" in stub4.sent and stub4.sent.index("*RST;*WAI") < stub4.sent.index(snap):
            failures.append("preserve: *RST must not precede the snapshot")
    # and stays out of the way when not asked for
    if any(c.startswith("MMEM:STOR:STAT") for c in stub.sent):
        failures.append("preserve: snapshotted without --preserve")

    # --- diagdump: read-only guarantees ---
    import re as _re
    import tempfile
    tmp = tempfile.mkdtemp()
    stub5 = DryRunUPL(echo=False)
    dd = _ap.Namespace(devices=None, max_addr=2048, output=f"{tmp}/dd")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        cmd_diagdump(stub5, dd)
    writes = [c for c in stub5.sent if _re.match(r"DIAG:DEV:DATA(?!\?)", c.strip().upper())]
    if writes:
        failures.append(f"diagdump: sent non-query DIAG:DEV:DATA {writes[:2]}")
    sent_sel = {c.split()[-1].upper() for c in stub5.sent if c.upper().startswith("DIAG:DEV ")}
    if sent_sel & set(DIAG_REFUSED):
        failures.append(f"diagdump: selected refused device(s) {sent_sel & set(DIAG_REFUSED)}")
    # every ADDR must be followed immediately by an error check
    for i, c in enumerate(stub5.sent):
        if c.startswith("DIAG:DEV:ADDR") and (i + 1 >= len(stub5.sent) or stub5.sent[i + 1] != "SYST:ERR?"):
            failures.append(f"diagdump: '{c}' not followed by SYST:ERR?")
            break
    words = sum(1 for c in stub5.sent if c == "DIAG:DEV:DATA?")
    if words != sum(DryRunUPL().diag_tables[d.upper()] for d in DIAG_DEFAULT):
        failures.append(f"diagdump: read {words} words, expected every table read to its end")
    print(f"  diagdump: {words} words, query-only, no refused selectors, SYST:ERR? after every ADDR")

    # refused selectors must be rejected before anything is sent
    stub6 = DryRunUPL(echo=False)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            cmd_diagdump(stub6, _ap.Namespace(devices="SERN,REG", max_addr=4, output=f"{tmp}/x"))
        failures.append("diagdump: accepted a refused selector")
    except SystemExit:
        if stub6.sent:
            failures.append(f"diagdump: sent {stub6.sent} before refusing")
    print("  diagdump: refused selector stops the run before any command is sent")

    # a rejected selector is skipped; a timed-out read drains the port and stops that table
    class _Flaky(DryRunUPL):
        def __init__(self):
            super().__init__(echo=False)
            self.diag_tables = {"SERN": 2, "CAGEN": 10}
            self.drained = 0
        def query(self, cmd):
            if cmd == "DIAG:DEV:DATA?" and self.diag_dev == "CAGEN" and self.diag_addr == 3:
                self.sent.append(cmd)
                raise TimeoutError("simulated")
            return super().query(cmd)
        def drain(self, settle=0.0):
            self.drained += 1
    stub7 = _Flaky()
    with contextlib.redirect_stderr(io.StringIO()):
        cmd_diagdump(stub7, _ap.Namespace(devices="SERN,CLDG,CAGEn", max_addr=2048, output=f"{tmp}/y"))
    import json as _json
    got = _json.load(open(f"{tmp}/y.json"))["devices"]
    if got.get("CLDG", {}).get("status") != "rejected":
        failures.append("diagdump: an unsupported selector was not recorded as rejected")
    if got.get("CAGEn", {}).get("words") != 3 or stub7.drained != 1:
        failures.append("diagdump: timeout did not stop the table at 3 words with one drain")
    if got.get("SERN", {}).get("words") != 2:
        failures.append("diagdump: the table before the failures was affected")
    print("  diagdump: rejected selector skipped; read timeout drains once and stops that table")

    # --- parse_values error path ---
    for bad in ("No Values", ""):
        try:
            parse_values(bad, "test")
            failures.append(f"parse_values({bad!r}) should have raised")
        except ValueError:
            pass
    print("  parse_values: rejects empty / 'No Values' replies")

    # --- 8.3 sibling naming ---
    cases = {
        "C:\\UPL\\FR.EXP": "C:\\UPL\\FRX.EXP",
        "C:\\UPL\\SWEEPDAT.EXP": "C:\\UPL\\SWEEPDAX.EXP",
        "FR.EXP": "FRX.EXP",
    }
    for src, want in cases.items():
        got = _sibling(src, "X")
        if got != want:
            failures.append(f"_sibling({src!r}) = {got!r}, expected {want!r}")
    print(f"  _sibling: {len(cases)} DOS 8.3 cases")

    print()
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("All offline sequence checks passed.")
    print("Documented sources: Vol.2 sec 3.10.5.1.1, 3.10.6, 3.10.10, 3.15.9.1;")
    print("R&S app notes 1ga16_1l, 1GA21, 1GA24, 1GA30.")
    return 0


def main():
    p = argparse.ArgumentParser(description="Pull data off an R&S UPL over RS232 (COM2).")
    p.add_argument("--port", help="serial port (COM4, /dev/ttyUSB0) or GPIB VISA resource "
                   "(GPIB0::20::INSTR); not needed with --dry-run")
    p.add_argument("--baud", type=int, default=115200, help="must match UPL COM2 (default 115200)")
    p.add_argument("--timeout", type=float, default=10.0, help="reply timeout seconds")
    p.add_argument("--opc", action="store_true", help="use *OPC? to wait instead of a fixed delay")
    p.add_argument("--dry-run", action="store_true",
                   help="do not open a serial port; print the SCPI that would be sent and use canned replies")
    p.add_argument("--preserve", action="store_true",
                   help="snapshot the UPL's complete setup before the measurement and restore it after "
                        "(MMEM:STOR/LOAD:STAT 2, the FLAT_GEN.BAS idiom); writes a scratch file on the UPL")
    p.add_argument("--state-file", default=STATE_TMP,
                   help=f"scratch path on the UPL used by --preserve (default {STATE_TMP})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="send *IDN? to confirm remote control (UPL-B4) is live")

    r = sub.add_parser("read", help="read the standard live values (rms/peak/freq/phase, both channels)")
    r.add_argument("--no-trigger", action="store_true", help="do not send INIT;*WAI first")

    s = sub.add_parser("sweep", help="capture the current sweep trace to CSV")
    s.add_argument("-o", "--output", help="CSV file (default: stdout)")

    a = sub.add_parser("autoexport", help="trigger a fresh sweep and pull trace(s)+x-axis to a timestamped CSV")
    a.add_argument("-o", "--output", help="output name; may contain strftime codes (default upl_<timestamp>.csv)")
    a.add_argument("--setup", help="UPL setup file to MMEM:LOAD:STAT first, e.g. C:\\UPL\\MYSETUP.SAC")
    a.add_argument("--both", action="store_true", help="also capture channel 2 (TRAC2)")
    a.add_argument("--settle", type=float, default=0.5, help="seconds to wait after INIT if not using --opc")
    a.add_argument("--repeat", type=int, default=1, help="number of captures (for logging)")
    a.add_argument("--interval", type=float, default=0.0, help="seconds between repeats")

    n = sub.add_parser("nsweep", help="run the UPL's OWN sweep engine and pull the trace + x-axis to CSV")
    n.add_argument("--start", type=float, default=20.0, help="sweep start frequency in Hz (default 20)")
    n.add_argument("--stop", type=float, default=20000.0, help="sweep stop frequency in Hz (default 20000)")
    n.add_argument("--points", type=int, default=40, help="sweep points, 2..1024 (default 40)")
    n.add_argument("--spacing", choices=["log", "lin"], default="log", help="sweep spacing (default log)")
    n.add_argument("--func", default="RMS", help="SENS1:FUNC measurement function, e.g. RMS, THD, THDN (default RMS)")
    n.add_argument("--feed", choices=sorted(FEED_CHOICES), default="func1",
                   help="what feeds trace A (default func1 = SENSe1:DATA1, the measured function on ch1)")
    n.add_argument("--volt", type=float, help="generator level in V, if it should be set")
    n.add_argument("--both", action="store_true", help="also feed and capture trace B (channel 2)")
    n.add_argument("--setup", help="UPL setup file to MMEM:LOAD:STAT 0 first, e.g. C:\\UPL\\MYSETUP.SAC")
    n.add_argument("--no-reset", dest="reset", action="store_false", help="skip the leading *RST")
    n.add_argument("--no-restore", dest="restore", action="store_false",
                   help="leave the generator in sweep mode afterwards (default restores FIX)")
    n.add_argument("--sweep-timeout", type=float, default=120.0,
                   help="reply timeout while the sweep runs; 40 points took ~17s live (default 120)")
    n.add_argument("-o", "--output", help="CSV file (default: stdout)")

    ff = sub.add_parser("fft", help="run an FFT and read the WHOLE spectrum (pages the 1024-line block limit)")
    ff.add_argument("--size", choices=sorted(FFT_SIZES, key=int), default="8192", help="FFT size (default 8192)")
    ff.add_argument("--zoom", type=int, default=1, help="zoom factor: 1=off, else 2/4/8/... (default 1)")
    ff.add_argument("--center", type=float, help="zoom center frequency in Hz (only meaningful with --zoom > 1)")
    ff.add_argument("--window", default="BLACkman_harris", help="CALC:TRAN:FREQ:WINDow (default BLACkman_harris)")
    ff.add_argument("--digital", action="store_true", help="digital analyzer: line count is size*127/256, not 117/256")
    ff.add_argument("--max-blocks", type=int, default=FFT_MAX_BLOCKS, help="block-index ceiling (default 8)")
    ff.add_argument("--no-reset", dest="reset", action="store_false", help="skip the leading *RST")
    ff.add_argument("--fft-timeout", type=float, default=120.0, help="reply timeout while the FFT runs (default 120)")
    ff.add_argument("-o", "--output", help="CSV file (default: stdout)")

    st = sub.add_parser("storetrace", help="tell the UPL to write its current trace to a file on its own disk")
    st.add_argument("remote", help="path on the UPL, e.g. C:\\UPL\\FR.EXP")
    st.add_argument("--format", choices=["exp", "asc", "bin"], default="exp",
                    help="exp = plain text table for the PC (default); asc/bin can be reloaded by the UPL")
    st.add_argument("--trace", choices=["a", "b", "ab"], default="a", help="which trace buffer (default a)")
    st.add_argument("--xaxis", action="store_true", help="also store the X-axis list (MMEM:STOR:LIST LIST1)")
    st.add_argument("--xaxis-name", help="explicit path for the X-axis file (default: derived from remote)")
    st.add_argument("--verify", action="store_true", help="MMEM:CAT? the directory afterwards")

    dd = sub.add_parser("diagdump", help="READ-ONLY dump of per-unit stored state (serial, cal tables, option key) "
                                         "via undocumented DIAG:DEV -- unverified")
    dd.add_argument("--devices", help=f"comma-separated selectors (default: {','.join(DIAG_DEFAULT)}); "
                                      f"allowed: {','.join(DIAG_ALLOWED)}")
    dd.add_argument("--max-addr", type=int, default=2048,
                    help="stop walking a table after this many addresses (default 2048 = the X24164's size)")
    dd.add_argument("-o", "--output", help="output base name; writes <name>.csv and <name>.json")

    sub.add_parser("seqcheck", help="offline: assert the nsweep/storetrace SCPI matches the documented sequences")

    c = sub.add_parser("catalog", help="list files on the UPL (MMEM:CAT?)")
    c.add_argument("path", nargs="?", help="optional directory, e.g. C:\\UPL")

    g = sub.add_parser("getfile", help="pull a file off the UPL (e.g. a stored EXPORT trace)")
    g.add_argument("remote", help="path on the UPL, e.g. C:\\UPL\\MYTRACE.EXP")
    g.add_argument("-o", "--output", required=True, help="local file to write")

    rw = sub.add_parser("raw", help="send one SCPI command; query if it ends with '?'")
    rw.add_argument("command")

    args = p.parse_args()

    if args.cmd == "seqcheck":
        return cmd_seqcheck(None, args)

    if args.dry_run:
        print("--- DRY RUN: no serial port opened ---")
        # For `fft`, model a real spectrum of the requested size/zoom (8192
        # unzoomed analog = 3744 lines) so the block paging is actually exercised.
        if args.cmd == "fft":
            upl = DryRunUPL(fft_lines=fft_line_count(int(args.size), args.zoom, args.digital))
        else:
            upl = DryRunUPL()
    else:
        if not args.port:
            p.error("--port is required (or use --dry-run)")
        upl = connect(args.port, args.baud, args.timeout)
    try:
        return {
            "probe": cmd_probe,
            "read": cmd_read,
            "sweep": cmd_sweep,
            "nsweep": cmd_nsweep,
            "fft": cmd_fft,
            "diagdump": cmd_diagdump,
            "storetrace": cmd_storetrace,
            "autoexport": cmd_autoexport,
            "catalog": cmd_catalog,
            "getfile": cmd_getfile,
            "raw": cmd_raw,
        }[args.cmd](upl, args)
    finally:
        upl.close()


if __name__ == "__main__":
    sys.exit(main())
