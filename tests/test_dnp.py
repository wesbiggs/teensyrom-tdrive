"""CMD native partitions (.dnp, docs/DESIGN.md 66): geometry, header, BAM count, directories and sub-directories, files, read-only.

The images come from tools/dnp.py (VICE's native-partition layout); c1541 cannot make or read them, so there is no second opinion
here: the layout was taken from VICE's vdrive source (vdrive-bam.c, vdrive-command.c) and should be checked against an image made
by DirMaster or a CMD drive when one is at hand."""
import ctypes, pathlib, sys, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'tools'))
from d64py import LIB, Disk
from dnp import Dnp, sample

E_RO, E_NOTFOUND = -6, -8


class GeometryTests(unittest.TestCase):
    def test_sizes(self):
        d = ctypes.create_string_buffer(LIB.d64_sizeof_d64())
        for size, ok in ((0, False), (65535, False), (65536, True), (65536 * 3, True), (65536 * 3 + 256, False),
                         (65536 * 255, True), (65536 * 256, False)):
            self.assertEqual(LIB.d64_open_dnp(d, None, None, ctypes.c_size_t(size)) == 0, ok, size)
        self.assertEqual(LIB.d64_open_dnp(d, None, None, ctypes.c_size_t(65536 * 7)), 0)
        LIB.d64_sector_offset.restype = ctypes.c_long
        self.assertEqual(LIB.d64_sectors(d), 7 * 256)
        self.assertEqual(LIB.d64_sectors_in_track(d, 7), 256)
        self.assertEqual(LIB.d64_sectors_in_track(d, 8), 0)
        self.assertEqual(LIB.d64_sector_offset(d, 1, 0), 0)
        self.assertEqual(LIB.d64_sector_offset(d, 2, 5), (256 + 5) * 256)
        self.assertEqual(LIB.d64_sector_offset(d, 7, 255), (7 * 256 - 1) * 256)
        self.assertEqual(LIB.d64_sector_offset(d, 8, 0), -1)

    def test_never_by_size(self):
        """a 3-track dnp is as long as a 40-track d64: the size picks the d64, only the name the dnp"""
        img = Dnp(3).bytes()
        self.assertEqual(len(img), 196608)
        self.assertEqual(Disk(img).header(), (b"", b"", b""))                       # read as a d64: 18/0 is empty
        self.assertEqual(Disk(img, dnp=True).header(), (b"NATIVE", b"00", b"1H"))


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.src = sample()
        self.disk = Disk(self.src.bytes(), dnp=True)

    def names(self): return [(e["name"], e["type"]) for e in self.disk.entries()]

    def test_header_and_root_directory(self):
        self.assertEqual(self.disk.header(), (b"CMDNATIVE", b"NP", b"1H"))
        self.assertEqual(self.names(), [(b"GAMES", 0x86), (b"HELLO", 0x82), (b"NOTES", 0x81)])

    def test_blocks_free(self):
        self.assertEqual(self.disk.free(), self.src.free_count())
        blank = Dnp(4)
        self.assertEqual(Disk(blank.bytes(), dnp=True).free(), 4 * 256 - 64)   # 1/0-1/63 are never counted
        one = Dnp(1)
        self.assertEqual(Disk(one.bytes(), dnp=True).free(), 192)
        big = Dnp(255)
        self.assertEqual(Disk(big.bytes(), dnp=True).free(), 255 * 256 - 64)   # 65216: still a 16-bit count

    def test_bam_bits_past_the_last_track_are_ignored(self):
        img = bytearray(Dnp(2).bytes())
        self.assertEqual(img[512 + 32 * 3], 0xFF)                                # CMD formats them free
        self.assertEqual(Disk(bytes(img), dnp=True).free(), 2 * 256 - 64)

    def test_bit_order(self):
        """sector 64 is bit 7 of track 1's byte 8: using it must cost exactly that block"""
        img = bytearray(Dnp(2).bytes())
        img[512 + 32 + 8] &= 0x7F
        self.assertEqual(Disk(bytes(img), dnp=True).free(), 2 * 256 - 64 - 1)
        img = bytearray(Dnp(2).bytes())
        img[512 + 64 + 31] = 0xFE                                                # track 2 sector 255 (bit 0 of the last byte)
        self.assertEqual(Disk(bytes(img), dnp=True).free(), 2 * 256 - 64 - 1)

    def test_files(self):
        self.assertEqual(self.disk.read_file(b"HELLO"), b"\x01\x08" + b"ROOT FILE" + bytes(300))
        self.assertEqual(self.disk.read_file(b"NOTES"), b"some text\r")
        self.assertIsNone(self.disk.read_file(b"INGAMES"))                       # not in the root

    def test_find_never_returns_a_directory(self):
        r, e = self.disk.find(b"GAMES")
        self.assertEqual(r, 0)
        r, e = self.disk.find(b"*")                                              # LOAD"*": the first file, past the DIR entry
        self.assertEqual((r, e.raw[6:11]), (1, b"HELLO"))

    def test_sub_directories(self):
        d = self.disk.d
        self.assertEqual(LIB.d64_dir_enter(d, b"NOPE"), E_NOTFOUND)
        self.assertEqual(LIB.d64_dir_enter(d, b"HELLO"), E_NOTFOUND)             # a file is no directory
        self.assertEqual(LIB.d64_dir_enter(d, b"GAM*"), E_NOTFOUND)              # exact names only
        self.assertEqual(LIB.d64_dir_enter(d, b"GAMES"), 0)
        self.assertEqual(self.disk.header(), (b"GAMES", b"NP", b"1H"))
        self.assertEqual(self.names(), [(b"INGAMES", 0x82), (b"DEEP", 0x86)])
        self.assertEqual(self.disk.read_file(b"INGAMES"), b"\x00\xc0in games")
        self.assertIsNone(self.disk.read_file(b"HELLO"))
        self.assertEqual(LIB.d64_dir_enter(d, b"DEEP"), 0)
        self.assertEqual(self.disk.read_file(b"BOTTOM"), b"\x00\xc0" + bytes(range(256)) * 4)
        self.assertEqual(self.disk.free(), self.src.free_count())                # the BAM is the partition's
        self.assertEqual(LIB.d64_dir_up(d), 1)
        self.assertEqual(self.disk.header()[0], b"GAMES")
        self.assertEqual(LIB.d64_dir_up(d), 1)
        self.assertEqual(self.disk.header()[0], b"CMDNATIVE")
        self.assertEqual(LIB.d64_dir_up(d), 0)                                   # at the root
        LIB.d64_dir_enter(d, b"GAMES"); LIB.d64_dir_enter(d, b"DEEP")
        LIB.d64_dir_root(d)
        self.assertEqual(self.disk.header()[0], b"CMDNATIVE")

    def test_listing(self):
        text = self.disk.listing()
        self.assertIn(b'"GAMES"            DIR ', text)
        self.assertIn(b'"HELLO"            PRG ', text)
        self.assertIn(b'"CMDNATIVE       " NP 1H', text)

    def test_long_directory(self):
        """a native directory is not bound to a track: 600 entries (75 sectors) list without a loop error"""
        d = Dnp(8)
        for i in range(600): d.add_file(b"F%03d" % i, b"x")
        disk = Disk(d.bytes(), dnp=True)
        self.assertEqual(len(disk.entries()), 600)
        self.assertEqual(disk.read_file(b"F599"), b"x")

    def test_read_only(self):
        self.assertEqual(self.disk.write_file(b"NEW", b"data"), E_RO)
        self.assertEqual(self.disk.scratch(b"HELLO"), E_RO)
        self.assertEqual(self.disk.rename(b"HELLO", b"BYE"), E_RO)
        self.assertEqual(self.disk.format(b"X", b"01"), E_RO)
        self.assertEqual(LIB.d64_validate(self.disk.d), E_RO)
        self.assertEqual(self.disk.dump(), self.src.bytes())


if __name__ == "__main__":
    unittest.main()
