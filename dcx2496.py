#!/usr/bin/env python3
"""
dcx2496.py - control a Behringer DCX2496 (Ultradrive Pro) over its RS232 port.

Unofficial, reverse-engineered protocol (Behringer never published it) -- see
dcx2496_protocol.md in this folder for the full source document. Summary:

  38400 baud, 8 data bits, no parity, 1 stop bit.
  MIDI-SysEx-style framing:  F0 00 20 32 <deviceID> 0E <function> <data...> F7
  deviceID: 00..0F (unit 1..16 when several DCX2496s are daisy-chained)
  function 3F = remote-control enable, function 20 = direct parameter change.
  A parameter change is 4 bytes: [channel] [param] [valuehi] [valuelo], where
  value = (valuehi << 7) | valuelo  (14-bit value split 7-bit/7-bit, MIDI-clean).

Encoding verified against both worked examples in the source doc, e.g.
"set in A gain of device #1 to +6dB" = F0 00 20 32 00 0E 20 01 01 02 01 52 F7
  -> value = (0x01<<7)|0x52 = 210 -> gain_db = (210-150)/10 = +6.0  (matches)

This module only *sends* (the protocol is documented write-only; no confirmed
readback). Track your own state -- the DCX won't tell you what it's currently set to.

SAFETY: this is an unofficial protocol. Recommended first use: enable remote
control, then send ONE gain or mute change and visually confirm on the DCX2496's
own front-panel display before trusting more complex writes (EQ/crossover).

Usage as a library:
    from dcx2496 import DCX2496
    d = DCX2496("COM5")
    d.enable_remote()
    d.set_gain("out1", 0.0)          # 0 dB
    d.set_mute("out1", True)
    d.set_crossover("out1", hp_freq=500, hp_type="lr24")
    d.set_eq_band("out1", band=1, freq=1000, q=1.0, gain_db=-3.0, filt="bandpass")
    d.close()

Usage from the command line (handy for the "verify on the front panel first" step):
    python dcx2496.py --port COM5 enable
    python dcx2496.py --port COM5 gain out1 6.0
    python dcx2496.py --port COM5 mute out1 on
    python dcx2496.py --port COM5 raw "F0 00 20 32 00 0E 20 01 01 02 01 52 F7"
"""

import argparse
import sys
import math

try:
    import serial
except ImportError:
    sys.exit("pyserial is required.  Install with:  python -m pip install pyserial")


# ---------------------------------------------------------------- channels
CHANNELS = {
    "setup": 0x00,
    "inA": 0x01, "inB": 0x02, "inC": 0x03, "inSUM": 0x04,
    "out1": 0x05, "out2": 0x06, "out3": 0x07, "out4": 0x08, "out5": 0x09, "out6": 0x0A,
}
INPUT_CHANNELS = {"inA", "inB", "inC", "inSUM"}
OUTPUT_CHANNELS = {"out1", "out2", "out3", "out4", "out5", "out6"}

# ------------------------------------------------------- common in/out params
P_GAIN = 0x02
P_MUTE = 0x03
P_DELAY_SW = 0x04
P_DELAY = 0x05          # 0..4000 -> 0..200mm, step 0.05mm  (doc: "step 5cm" per 4000 range -> 0.05mm/step)
P_EQ_SW = 0x06
P_EQ_NUM = 0x07
P_EQ_INDEX = 0x08
P_DYNEQ_ATTACK = 0x09
P_DYNEQ_RELEASE = 0x0A
P_DYNEQ_RATIO = 0x0B
P_DYNEQ_THRESH = 0x0C
P_DYNEQ_SW = 0x0D
P_DYNEQ_FREQ = 0x0E
P_DYNEQ_Q = 0x0F
P_DYNEQ_GAIN = 0x10
P_DYNEQ_FILT = 0x11
P_DYNEQ_SLOPE = 0x12
# EQ band N (1..9): base + (N-1)*4  where base params are freq,Q,gain,filter,slope (5 wide, but doc steps by 4 -- see NOTE)
EQ_BAND1_BASE = 0x13  # freq=0x13 Q=0x14 gain=0x15 filter=0x16 slope=0x17 ; band2 starts 0x18 ... (step of 5 per band, not 4)

# ------------------------------------------------------------- output-only
P_NAME = 0x40
P_INPUT_SRC = 0x41
P_HP_FILT = 0x42
P_HP_FREQ = 0x43
P_LP_FILT = 0x44   # doc labels this "hp filter" again -- almost certainly the LOW-pass half of the crossover pair
P_LP_FREQ = 0x45
P_LIM_SW = 0x46
P_LIM_THRESH = 0x47
P_LIM_RELEASE = 0x48
P_POLARITY = 0x49
P_PHASE = 0x4A
P_SHORT_DELAY = 0x4B

FILTER_TYPES = ["off", "but6", "but12", "bes12", "lr12", "but18", "but24",
                "bes24", "lr24", "but48", "lr48"]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _lin_to_log_index(value, vmin, vmax, steps):
    """Map a value in [vmin,vmax] (Hz, ms, Q...) to a 0..steps log-scaled index."""
    value = _clamp(value, vmin, vmax)
    frac = math.log(value / vmin) / math.log(vmax / vmin)
    return round(frac * steps)


def freq_to_index(freq_hz):
    """20 Hz..20 kHz log, 0..320."""
    return _clamp(_lin_to_log_index(freq_hz, 20, 20000, 320), 0, 320)


def q_to_index(q):
    """0.1..10 log, 0..40."""
    return _clamp(_lin_to_log_index(q, 0.1, 10, 40), 0, 40)


def db_to_index_pm15(db):
    """-15..+15 dB, step 0.1dB -> 0..300."""
    return _clamp(round((db + 15.0) * 10), 0, 300)


def db_to_index_lim(db):
    """-24..0 dB, step 0.1dB -> 0..240 (limiter threshold)."""
    return _clamp(round((db + 24.0) * 10), 0, 240)


class DCX2496:
    def __init__(self, port, device_id=0x00, baud=38400, timeout=1.0):
        self.device_id = device_id
        self.ser = serial.Serial(port=port, baudrate=baud, bytesize=serial.EIGHTBITS,
                                  parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                  timeout=timeout)
        # Protocol doc: "RTS gating on RS485" -- RTS must be actively asserted for the
        # DCX2496 to accept bytes. pyserial does not guarantee RTS state on open unless
        # told to, so assert both explicitly.
        self.ser.rts = True
        self.ser.dtr = True

    def close(self):
        self.ser.close()

    # ---------------------------------------------------------- low level
    def _send_frame(self, function, data_bytes):
        frame = bytes([0xF0, 0x00, 0x20, 0x32, self.device_id, 0x0E, function]) \
            + bytes(data_bytes) + bytes([0xF7])
        self.ser.write(frame)
        return frame

    @staticmethod
    def frame_hex(frame):
        return " ".join("%02X" % b for b in frame)

    def enable_remote(self, receive=True, transmit=False):
        """function 3F: 04 00=receive, 08 00=transmit, 0C 00=both."""
        code = (0x04 if receive else 0) | (0x08 if transmit else 0)
        return self._send_frame(0x3F, [code, 0x00])

    def set_param(self, channel, param, value14bit):
        """Raw function-20 single parameter change."""
        ch = CHANNELS[channel] if isinstance(channel, str) else channel
        v = _clamp(int(value14bit), 0, 0x3FFF)
        valuehi = (v >> 7) & 0x7F
        valuelo = v & 0x7F
        return self._send_frame(0x20, [0x01, ch, param, valuehi, valuelo])

    # ---------------------------------------------------------- friendly API
    def set_gain(self, channel, db):
        return self.set_param(channel, P_GAIN, db_to_index_pm15(db))

    def set_mute(self, channel, muted):
        return self.set_param(channel, P_MUTE, 1 if muted else 0)

    def set_polarity(self, channel, inverted):
        return self.set_param(channel, P_POLARITY, 1 if inverted else 0)

    def set_phase(self, channel, degrees):
        """0..180 deg, step 5deg -> index 0..36."""
        idx = _clamp(round(degrees / 5.0), 0, 36)
        return self.set_param(channel, P_PHASE, idx)

    def set_delay(self, channel, mm, enable=True):
        self.set_param(channel, P_DELAY_SW, 1 if enable else 0)
        idx = _clamp(round(mm / 200.0 * 4000), 0, 4000)
        return self.set_param(channel, P_DELAY, idx)

    def set_crossover(self, out_channel, hp_freq=None, hp_type=None, lp_freq=None, lp_type=None):
        """out_channel: one of out1..out6. hp/lp_type: one of FILTER_TYPES."""
        assert out_channel in OUTPUT_CHANNELS, "crossover only applies to output channels"
        frames = []
        if hp_type is not None:
            frames.append(self.set_param(out_channel, P_HP_FILT, FILTER_TYPES.index(hp_type)))
        if hp_freq is not None:
            frames.append(self.set_param(out_channel, P_HP_FREQ, freq_to_index(hp_freq)))
        if lp_type is not None:
            frames.append(self.set_param(out_channel, P_LP_FILT, FILTER_TYPES.index(lp_type)))
        if lp_freq is not None:
            frames.append(self.set_param(out_channel, P_LP_FREQ, freq_to_index(lp_freq)))
        return frames

    def set_limiter(self, out_channel, enable=True, thresh_db=None, release_ms=None):
        assert out_channel in OUTPUT_CHANNELS
        frames = [self.set_param(out_channel, P_LIM_SW, 1 if enable else 0)]
        if thresh_db is not None:
            frames.append(self.set_param(out_channel, P_LIM_THRESH, db_to_index_lim(thresh_db)))
        if release_ms is not None:
            idx = _clamp(_lin_to_log_index(release_ms, 20, 4000, 251), 0, 251)
            frames.append(self.set_param(out_channel, P_LIM_RELEASE, idx))
        return frames

    def set_eq_switch(self, channel, enable):
        return self.set_param(channel, P_EQ_SW, 1 if enable else 0)

    def set_eq_band(self, channel, band, freq=None, q=None, gain_db=None, filt=None, slope6db=None):
        """band: 1..9 (static parametric EQ bands). filt: 'low_shelv'|'bandpass'|'hi_shelv'.

        IMPORTANT (live-hardware-confirmed 2026-09-23): param 0x07 ("eq number") gates how many
        of the 9 bands are actually active -- band 1 works regardless, but band 2+ are SILENTLY
        ignored unless this count is raised. Not documented in the source protocol doc beyond its
        name. To avoid that trap, this method always sends eq number=9 (enable all bands) first.
        """
        assert 1 <= band <= 9
        base = EQ_BAND1_BASE + (band - 1) * 5  # step-of-5 per band -- CONFIRMED on real hardware
        frames = [self.set_param(channel, P_EQ_NUM, 9)]
        if freq is not None:
            frames.append(self.set_param(channel, base + 0, freq_to_index(freq)))
        if q is not None:
            frames.append(self.set_param(channel, base + 1, q_to_index(q)))
        if gain_db is not None:
            frames.append(self.set_param(channel, base + 2, db_to_index_pm15(gain_db)))
        if filt is not None:
            fmap = {"low_shelv": 0, "bandpass": 1, "hi_shelv": 2}
            frames.append(self.set_param(channel, base + 3, fmap[filt]))
        if slope6db is not None:
            frames.append(self.set_param(channel, base + 4, 0 if slope6db else 1))
        return frames


def main():
    p = argparse.ArgumentParser(description="Control a Behringer DCX2496 over RS232 (unofficial protocol).")
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=38400)
    p.add_argument("--device-id", type=lambda x: int(x, 0), default=0x00)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("enable", help="enable remote control (send this first)")

    g = sub.add_parser("gain", help="set gain in dB")
    g.add_argument("channel", choices=list(CHANNELS))
    g.add_argument("db", type=float)

    m = sub.add_parser("mute", help="mute on/off")
    m.add_argument("channel", choices=list(CHANNELS))
    m.add_argument("state", choices=["on", "off"])

    x = sub.add_parser("xover", help="set an output's highpass (crossover) filter+freq")
    x.add_argument("channel", choices=list(OUTPUT_CHANNELS))
    x.add_argument("freq", type=float)
    x.add_argument("--type", default="lr24", choices=FILTER_TYPES)

    r = sub.add_parser("raw", help="send a literal hex frame, e.g. 'F0 00 20 32 00 0E 20 01 01 02 01 52 F7'")
    r.add_argument("hexframe")

    args = p.parse_args()
    d = DCX2496(args.port, device_id=args.device_id, baud=args.baud)
    try:
        if args.cmd == "enable":
            f = d.enable_remote()
            print("sent:", d.frame_hex(f))
        elif args.cmd == "gain":
            f = d.set_gain(args.channel, args.db)
            print("sent:", d.frame_hex(f))
        elif args.cmd == "mute":
            f = d.set_mute(args.channel, args.state == "on")
            print("sent:", d.frame_hex(f))
        elif args.cmd == "xover":
            frames = d.set_crossover(args.channel, hp_freq=args.freq, hp_type=args.type)
            for f in frames:
                print("sent:", d.frame_hex(f))
        elif args.cmd == "raw":
            raw = bytes(int(b, 16) for b in args.hexframe.split())
            d.ser.write(raw)
            print("sent:", d.frame_hex(raw))
    finally:
        d.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
