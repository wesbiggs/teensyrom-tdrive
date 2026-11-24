"""Build CMD native partition images (.dnp) for the tests, laid out as VICE's vdrive writes a native partition (docs/DESIGN.md 66).

Nothing on the host writes .dnp files (c1541 has no such type), so the fixtures come from here:
  * 256 sectors on each of 1-255 tracks, the image is tracks * 64 KB
  * 1/1 root header: $00/$01 first directory sector (1/34), $02 'H', name $04 (16, $A0 padded over 25 bytes), id $16/$17,
    DOS "1H" at $19, $20/$21 = this header, $22/$23 = the parent's header (0/0 for the root), $24-$26 = where the DIR entry is
  * 1/2-1/33 BAM: byte 32 * t (counted from 1/2) starts track t's 32 bytes; a set bit = free, sector s = bit 7 - s % 8 of byte s / 8;
    the first 32 bytes are the BAM header ($02 'H', $03 ~'H', $04/$05 id, $06 $C0, $08 the number of tracks); tracks past the
    last are all free, as CMD formats them
  * 1/0, 1/1, 1/2-1/33 and 1/34 are used on a new partition; files are allocated upwards from 1/64
  * a sub-directory is an entry of type $86 (closed DIR) pointing at its header; its first directory sector follows the header
"""


class Dnp:
    def __init__(self, tracks, name=b"NATIVE", id_=b"00"):
        assert 1 <= tracks <= 255
        self.tracks = tracks
        self.img = bytearray(tracks * 65536)
        self.id = id_
        for t in range(1, 256):
            self.img[512 + 32 * t: 512 + 32 * t + 32] = b"\xff" * 32
        self.img[512 + 2] = 0x48; self.img[512 + 3] = 0xB7
        self.img[512 + 4: 512 + 6] = id_; self.img[512 + 6] = 0xC0; self.img[512 + 8] = tracks
        self.header(1, 1, name, (1, 34), (0, 0), (0, 0, 0))
        self.put(1, 34, bytes([0, 0xFF]) + bytes(254))
        for s in range(0, 35): self.use(1, s)
        self.next = (1, 64)

    # ---- sectors and the BAM ----
    def off(self, t, s):
        assert 1 <= t <= self.tracks and 0 <= s <= 255, (t, s)
        return ((t - 1) * 256 + s) * 256

    def sector(self, t, s): return bytes(self.img[self.off(t, s): self.off(t, s) + 256])

    def put(self, t, s, data):
        assert len(data) == 256
        self.img[self.off(t, s): self.off(t, s) + 256] = data

    def _bit(self, t, s): return 512 + 32 * t + s // 8, 0x80 >> (s % 8)

    def is_free(self, t, s):
        i, m = self._bit(t, s)
        return bool(self.img[i] & m)

    def use(self, t, s):
        i, m = self._bit(t, s)
        self.img[i] &= ~m & 0xFF

    def alloc(self):
        t, s = self.next
        while True:
            if t > self.tracks: raise RuntimeError("partition full")
            if self.is_free(t, s):
                self.use(t, s)
                self.next = (t, s)
                return t, s
            s += 1
            if s > 255: t, s = t + 1, 0

    def free_count(self):
        """blocks free as a CMD drive counts them: tracks 1..last, without 1/0-1/63"""
        return sum(self.is_free(t, s) for t in range(1, self.tracks + 1) for s in range(64 if t == 1 else 0, 256))

    # ---- directories ----
    def header(self, t, s, name, first, parent, entry):
        b = bytearray(256)
        b[0], b[1] = first
        b[2] = 0x48
        b[4:4 + 25] = b"\xa0" * 25
        b[4:4 + len(name)] = name
        b[0x16:0x18] = self.id
        b[0x19], b[0x1A] = 0x31, 0x48
        b[0x20], b[0x21] = t, s
        b[0x22], b[0x23] = parent
        b[0x24], b[0x25], b[0x26] = entry
        self.put(t, s, bytes(b))

    def slot(self, hdr):
        """a free directory slot under header hdr: (t, s, slot), growing the directory by a sector when it is full"""
        t, s = self.sector(*hdr)[0:2]
        while True:
            b = bytearray(self.sector(t, s))
            for i in range(8):
                if b[i * 32 + 2] == 0: return t, s, i
            if b[0] == 0:
                nt, ns = self.alloc()
                b[0], b[1] = nt, ns
                self.put(t, s, bytes(b))
                self.put(nt, ns, bytes([0, 0xFF]) + bytes(254))
                return nt, ns, 0
            t, s = b[0], b[1]

    def entry(self, hdr, type_, name, first, blocks):
        t, s, i = self.slot(hdr)
        b = bytearray(self.sector(t, s))
        e = i * 32
        b[e + 2:e + 32] = bytes(30)
        b[e + 2] = type_
        b[e + 3], b[e + 4] = first
        b[e + 5:e + 21] = b"\xa0" * 16
        b[e + 5:e + 5 + len(name)] = name
        b[e + 30], b[e + 31] = blocks & 0xFF, blocks >> 8
        self.put(t, s, bytes(b))
        return t, s, i

    ROOT = (1, 1)

    def add_file(self, name, data, hdr=ROOT, type_=0x82):
        """a file under header hdr (the root by default); returns its first t/s"""
        chunks = [data[i:i + 254] for i in range(0, len(data), 254)] or [b""]
        secs = [self.alloc() for _ in chunks]
        for k, (chunk, (t, s)) in enumerate(zip(chunks, secs)):
            if k + 1 < len(secs): link = secs[k + 1]
            else: link = (0, len(chunk) + 1)
            self.put(t, s, bytes(link) + chunk + bytes(254 - len(chunk)))
        self.entry(hdr, type_, name, secs[0], len(secs))
        return secs[0]

    def mkdir(self, name, hdr=ROOT):
        """a sub-directory under header hdr; returns its header t/s"""
        ht, hs = self.alloc()
        dt, ds = self.alloc()
        self.put(dt, ds, bytes([0, 0xFF]) + bytes(254))
        self.header(ht, hs, name, (dt, ds), hdr, (0, 0, 0))
        et, es, i = self.entry(hdr, 0x86, name, (ht, hs), 2)
        b = bytearray(self.sector(ht, hs)); b[0x24], b[0x25], b[0x26] = et, es, i * 32 + 2
        self.put(ht, hs, bytes(b))
        return ht, hs

    def bytes(self): return bytes(self.img)


def sample():
    """the image the tests and the VICE mock use: a DIR entry first in the root, files in two levels of sub-directories"""
    d = Dnp(4, b"CMDNATIVE", b"NP")
    games = d.mkdir(b"GAMES")
    d.add_file(b"HELLO", b"\x01\x08" + b"ROOT FILE" + bytes(300))          # two blocks
    d.add_file(b"NOTES", b"some text\r", type_=0x81)
    d.add_file(b"INGAMES", b"\x00\xc0" + b"in games", hdr=games)
    deep = d.mkdir(b"DEEP", hdr=games)
    d.add_file(b"BOTTOM", b"\x00\xc0" + bytes(range(256)) * 4, hdr=deep)
    return d
