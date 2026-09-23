"""Extract a member from an LHA/LZH archive compressed with -lh5-.

The UPL firmware ships its content as .LZH archives (DISK2/*.LZH) and the
1GA36 / FM-tuner app notes nest .LZH inside their self-extracting ZIPs.
LHA.EXE next to them is 16-bit DOS and will not run on 64-bit Windows, and
neither `lha` nor 7-Zip is present on this PC -- hence this decoder.

    python tools/lzh_extract.py DISK2/USER.LZH SNDFILE.BAS > SNDFILE.BAS
    python tools/lzh_extract.py DISK2/USER.LZH SELFTEST.BAS | less

With no member name it lists the archive.  Output is raw bytes: the .BAS
files are tokenized R&S BASIC, so pipe them through a printable-only filter
if you just want the string literals.
"""

import struct, sys

class Bits:
    def __init__(self, data):
        self.d = data; self.p = 0; self.bitbuf = 0; self.nbits = 0
    def fill(self):
        while self.nbits <= 24:
            b = self.d[self.p] if self.p < len(self.d) else 0
            self.p += 1
            self.bitbuf = ((self.bitbuf << 8) | b) & 0xFFFFFFFF
            self.nbits += 8
    def peek(self, n):
        self.fill()
        return (self.bitbuf >> (self.nbits - n)) & ((1 << n) - 1)
    def get(self, n):
        if n == 0: return 0
        v = self.peek(n); self.nbits -= n
        self.bitbuf &= (1 << self.nbits) - 1
        return v

def read_table(bs, nlen, special):
    n = bs.get(special[0])
    lens = [0]*nlen
    if n == 0:
        c = bs.get(special[0])
        return None, c
    i = 0
    while i < n:
        c = bs.peek(3)
        if c != 7:
            bs.get(3)
        else:
            bs.get(3)
            while bs.peek(1):
                bs.get(1); c += 1
            bs.get(1)
        lens[i] = c; i += 1
        if special[1] is not None and i == special[1]:
            j = bs.get(2)
            for _ in range(j):
                if i < nlen: lens[i] = 0; i += 1
    return lens, None

def read_clen(bs, nlen, ptc_lens, ptc_tbl):
    n = bs.get(9)
    lens = [0]*nlen
    if n == 0:
        c = bs.get(9)
        return None, c
    i = 0
    while i < n:
        c = decode_sym(bs, ptc_lens)
        if c <= 2:
            if c == 0: cnt = 1
            elif c == 1: cnt = bs.get(4) + 3
            else: cnt = bs.get(9) + 20
            for _ in range(cnt):
                if i < nlen: lens[i] = 0; i += 1
        else:
            lens[i] = c - 2; i += 1
    return lens, None

def decode_sym(bs, lens):
    # slow canonical huffman decode
    code = 0; length = 0
    # build once cached
    tbl = lens_tbl(lens)
    while True:
        code = (code << 1) | bs.get(1); length += 1
        if (length, code) in tbl: return tbl[(length, code)]
        if length > 16: raise ValueError("bad huff")

_cache = {}
def lens_tbl(lens):
    key = id(lens)
    if key in _cache and _cache[key][0] is lens: return _cache[key][1]
    tbl = {}; code = 0
    for l in range(1, 17):
        for sym, ln in enumerate(lens):
            if ln == l:
                tbl[(l, code)] = sym; code += 1
        code <<= 1
    _cache[key] = (lens, tbl)
    return tbl

def lh5_decode(data, outsize):
    bs = Bits(data)
    out = bytearray()
    while len(out) < outsize:
        blocksize = bs.get(16)
        if blocksize == 0: break
        ptc_lens, ptc_fix = read_table(bs, 19, (5, 3))
        if ptc_lens is None:
            ptc_lens = [0]*19
            clens, cfix = read_clen_fixed(bs, ptc_fix)
        else:
            clens, cfix = read_clen(bs, 510, ptc_lens, None)
        if clens is None:
            clens = [0]*510; cfix_v = cfix
        else:
            cfix_v = None
        pt2_lens, pt2_fix = read_table(bs, 14, (4, None))
        if pt2_lens is None:
            pt2_lens = [0]*14
            pt2_fix_v = pt2_fix
        else:
            pt2_fix_v = None
        for _ in range(blocksize):
            c = cfix_v if cfix_v is not None else decode_sym(bs, clens)
            if c < 256:
                out.append(c)
            else:
                length = c - 256 + 3
                p = pt2_fix_v if pt2_fix_v is not None else decode_sym(bs, pt2_lens)
                dist = (1 << (p-1)) + bs.get(p-1) if p > 1 else p
                dist += 1
                start = len(out) - dist
                for k in range(length):
                    out.append(out[start + k])
            if len(out) >= outsize: break
    return bytes(out[:outsize])

def read_clen_fixed(bs, fix):
    return None, fix

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__, file=sys.stderr)
        sys.exit(0 if len(sys.argv) >= 2 else 2)
    path = sys.argv[1]
    want = sys.argv[2] if len(sys.argv) > 2 else None
    d = open(path,'rb').read()
    p = 0
    while p < len(d):
        hs = d[p]
        if hs == 0: break
        csz, osz = struct.unpack('<II', d[p+7:p+15])
        nl = d[p+21]
        name = d[p+22:p+22+nl].decode('latin1')
        body = d[p+hs+2:p+hs+2+csz]
        if want is None:
            print(f"{meth if False else name:16s} {osz:8d}", file=sys.stderr)
        elif name.upper() == want.upper():
            out = lh5_decode(body, osz)
            sys.stdout.buffer.write(out)
            sys.exit(0)
        p += hs+2+csz
    sys.exit(1)
