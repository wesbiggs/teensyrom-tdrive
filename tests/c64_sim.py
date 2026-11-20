"""A C64 machine-code program run in py65 with the KERNAL calls it makes answered in Python (a test aid, used by tests/test_vdconfig.py).

The program is loaded from its PRG and started at the SYS address of its BASIC stub, as if BASIC had called it. A JSR to one of the KERNAL
jump-table entries below is carried out here and returns like the real routine: SETLFS, SETNAM, OPEN, CLOSE, CHKIN, CHKOUT, CLRCHN,
CHRIN, CHROUT, GETIN, PLOT, LISTEN, SECOND, UNLSN. Any other jump into the ROM area is an error. Files go to a drive object
(open / close / get / getline / put / st, and .units for "present"), the screen is a 40x25 model with cursor addressing, reverse and colour
codes and the two character sets (CHR$(14) / CHR$(142); row() shows what the set displays: in the lower-case set $41-$5A as
small letters and $C1-$DA as capitals), keys come from a script. run() returns "key" when the program waits for a key it does not
have, "end" when it returns to BASIC and "menu" when it writes the tdrive mailbox's VIO_MENU command (the Teensy would reset the
C64 into the TR menu then; answered at $DE13 unless menu_answer is False). The fast LOAD's block commands FLOAD_OPEN / FLOAD_BLK are
answered from the drive as well (the name and the blocks in the IO2 window at $DF80, DATA $DE12, ST $DE14), unless fast is False
("not mine": the program must fall back to OPEN + CHRIN); fast_blocks counts the blocks sent.
layout picks the TDrive handler: "kernal" (the TR+ KERNAL build: registers at $DE10, ID bytes $D6 $64 at $DE19/$DE1A), "agent" (the
TDrive agent: registers at $DF00, IDs at $DF09/$DF0A, IO1 $DE08-$DEFF the agent's code, which the program must never write) or None
(no TDrive handler: no IDs, and any write to $DE00-$DFFF fails the run). The device numbers in mem are given at the KERNAL build's
$DE16/$DE17 and moved to the layout's registers. Under the agent the bus scan is modelled as d64/tdrive_vec.c and d64/tdrive_io.c do it:
real = the numbers a real drive answers at; the units' numbers are provisional until VIO_SCAN / VIO_FREE (the program's own scan) or,
failing that, the engine's own scan at the first OPEN; an OPEN that reaches a real drive is an error ("not modelled").
Kept from the real KERNAL on purpose: CHRIN from a serial file answers CR without reading while ST ($90) is not 0, every read ORs its
bits into ST, and bytes sent to a file reach the drive at UNLISTEN (CLRCHN / CLOSE), so a command is one PRINT#."""
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

COLOR_OF = {144: 0, 5: 1, 28: 2, 159: 3, 156: 4, 30: 5, 31: 6, 158: 7, 129: 8, 149: 9, 150: 10, 151: 11, 152: 12, 153: 13, 154: 14, 155: 15}
STATUS = 0x90
TXTCOL = 0x0286
END = 0xFF00            # the return address handed to the program: reaching it means "back in BASIC"


class Screen:
    def __init__(self):
        self.ch = [[" "] * 40 for _ in range(25)]
        self.rev = [[False] * 40 for _ in range(25)]
        self.col = [[1] * 40 for _ in range(25)]
        self.r = self.c = 0
        self.reverse = False
        self.color = 1
        self.scrolled = 0
        self.lower = False                  # the lower-case character set

    def clear(self):
        for r in range(25):
            for c in range(40): self.ch[r][c] = " "; self.rev[r][c] = False; self.col[r][c] = self.color
        self.r = self.c = 0

    def put(self, code):
        if code == 147: self.clear(); return
        if code in (14, 142): self.lower = code == 14; return
        if code == 19: self.r = self.c = 0; return
        if code == 18: self.reverse = True; return
        if code == 146: self.reverse = False; return
        if code in COLOR_OF: self.color = COLOR_OF[code]; return
        if code == 17: self.r = min(24, self.r + 1); return
        if code == 145: self.r = max(0, self.r - 1); return
        if code == 13: self.c = 0; self.newline(); self.reverse = False; return
        if code & 0x7F < 32: return
        self.ch[self.r][self.c] = self.glyph(code); self.rev[self.r][self.c] = self.reverse; self.col[self.r][self.c] = self.color
        self.c += 1
        if self.c >= 40: self.c = 0; self.newline()    # the C64 wraps as soon as the last column is written (and scrolls on the last row)

    def glyph(self, code):
        if 0xC1 <= code <= 0xDA or 0x61 <= code <= 0x7A: return chr((code & 0x1F) + 64) if self.lower else "?"   # shifted: capitals / graphics
        if 0x41 <= code <= 0x5A and self.lower: return chr(code + 32)
        return chr(code)

    def newline(self):
        if self.r < 24: self.r += 1
        else:
            self.scrolled += 1
            self.ch = self.ch[1:] + [[" "] * 40]; self.rev = self.rev[1:] + [[False] * 40]; self.col = self.col[1:] + [[1] * 40]

    def row(self, r): return "".join(self.ch[r]).rstrip()
    def text(self): return "\n".join(self.row(r) for r in range(25))


def petscii(s): return "".join(chr(ord(c) - 32) if "a" <= c <= "z" else c for c in s)


class C64:
    MBXCMD, MBXARG, MBXDATA, MBXSTAT, MBXST, MBXLEN, WIN, VIO_MENU, FLOAD_OPEN, FLOAD_BLK = 0xDE10, 0xDE11, 0xDE12, 0xDE13, 0xDE14, 0xDE15, 0xDF80, 16, 9, 10
    FL = "fast-load"                                    # the drive channel the fast commands use

    VIO_SCAN, VIO_FREE = 14, 15
    AGENT_CODE = 0xDE   # what the agent's page reads (its byte at $DE16 is $DE: the number a program reading the wrong layout saw)

    def __init__(self, prg, drive, mem=None, menu_answer=True, fast=True, layout="kernal", real=()):
        prg = bytes(prg)
        self.cpu = c = MPU(memory=ObservableMemory())
        self.mem = c.memory
        load = prg[0] | prg[1] << 8
        self.mem[load:load + len(prg) - 2] = list(prg[2:])
        self.layout, self.real = layout, set(real)
        base = 0xDF00 if layout == "agent" else 0xDE10
        (self.MBXCMD, self.MBXARG, self.MBXDATA, self.MBXSTAT, self.MBXST, self.MBXLEN) = range(base, base + 6)
        self.DEV0 = base + 6
        if layout == "agent":
            for a in range(0xDE08, 0xDF00): self.mem[a] = self.AGENT_CODE
        if layout is not None: self.mem[base + 9], self.mem[base + 10] = 0xD6, 0x64
        for a, v in (mem or {}).items(): self.mem[self.DEV0 + a - 0xDE16 if 0xDE10 <= a <= 0xDE1A else a] = v
        self.scan_pending = layout == "agent"          # the agent's units have provisional numbers until a scan
        self.released, self.scans = None, []
        self.io_writes, self.inside = [], False
        self.mem.subscribe_to_write(range(0xDE00, 0xE000), self.io_write)
        i = prg.index(b"\x9e") + 1
        start = int(prg[i:prg.index(b"\0", i)].decode().strip())
        self.screen, self.drive, self.keys = Screen(), drive, []
        self.files, self.inp, self.outp, self.wbuf, self.cmdbuf = {}, None, None, bytearray(), {}
        self.lfs, self.name, self.ldev, self.steps = (0, 0, 0), "", None, 0
        self.menu, self.menu_answer = False, menu_answer
        self.fast, self.fast_blocks, self.fast_opens = fast, 0, 0
        c.sp = 0xF6
        self.push((END - 1) >> 8); self.push((END - 1) & 0xFF)
        c.pc = start
        self.traps = {0xFFBA: self.setlfs, 0xFFBD: self.setnam, 0xFFC0: self.open, 0xFFC3: self.close, 0xFFC6: self.chkin, 0xFFC9: self.chkout,
                      0xFFCC: self.clrchn, 0xFFCF: self.chrin, 0xFFD2: self.chrout, 0xFFE4: self.getin, 0xFFF0: self.plot,
                      0xFFB1: self.listen, 0xFF93: self.second, 0xFFAE: self.unlsn}

    # ---- CPU helpers ----
    def push(self, v): self.mem[0x100 + self.cpu.sp] = v; self.cpu.sp = (self.cpu.sp - 1) & 0xFF

    def pull(self): self.cpu.sp = (self.cpu.sp + 1) & 0xFF; return self.mem[0x100 + self.cpu.sp]

    def ret(self, a=None, x=None, y=None, carry=None):
        c = self.cpu
        if a is not None: c.a = a & 0xFF
        if x is not None: c.x = x & 0xFF
        if y is not None: c.y = y & 0xFF
        if carry is not None: c.p = (c.p | c.CARRY) if carry else (c.p & ~c.CARRY)
        c.p = (c.p & ~(c.ZERO | c.NEGATIVE)) | (c.ZERO if c.a == 0 else 0) | (c.a & 0x80)

    def run(self, max_steps=20_000_000):
        """run until the program returns to BASIC ("end") or waits for a key it does not have ("key")"""
        c = self.cpu
        while True:
            pc = c.pc
            if pc == END: return "end"
            t = self.traps.get(pc)
            if t:
                if t() == "wait": return "key"
                lo = self.pull(); hi = self.pull(); c.pc = ((hi << 8) | lo) + 1
                continue
            if pc >= 0xA000 and not 0xC000 <= pc < 0xD000: raise RuntimeError("call into the ROM at $%04X, not modelled" % pc)
            c.step()
            if self.menu: return "menu"
            self.steps += 1
            if self.steps > max_steps: raise RuntimeError("runaway program at $%04X" % c.pc)

    def press(self, *keys):
        for k in keys:
            if isinstance(k, str): self.keys.extend(ord(petscii(ch)) for ch in k)     # unshifted keys give the upper case codes
            else: self.keys.append(k)

    def io_write(self, addr, v):
        if self.inside: return None                     # the model's own answers
        ok = self.layout is not None and (self.MBXCMD <= addr <= self.MBXLEN or self.WIN <= addr < self.WIN + 128)
        if not ok: raise RuntimeError("write of $%02X to $%04X: not a register of this TDrive handler (%s)" % (v, addr, self.layout))
        self.io_writes.append(addr)
        if addr == self.MBXCMD:
            self.inside = True
            try: self.mbx_cmd(addr, v)
            finally: self.inside = False
        return None

    # ---- the agent's bus scan (tdrive_scan_begin / tdrive_scan_free) ----
    def publish(self):
        n = {u.title: d for d, u in self.drive.units.items()}
        self.mem[self.DEV0], self.mem[self.DEV0 + 1] = n.get("SD", 0), n.get("USB", 0)

    def scan_begin(self):
        self.scan_pending = False
        self.released = sorted(self.drive.units.values(), key=lambda u: u.title != "SD")
        self.drive.units = {}
        self.publish()
        return len(self.released)

    def scan_free(self, dev):
        if self.released and 8 <= dev <= 30 and dev not in self.drive.units: self.drive.units[dev] = self.released.pop(0)
        self.publish()
        return len(self.released)

    def mbx_cmd(self, addr, v):
        m = self.mem
        if v in (self.VIO_SCAN, self.VIO_FREE):
            if self.layout != "agent": raise RuntimeError("bus scan command under the %s layout" % self.layout)
            self.scans.append(v)
            m[self.MBXDATA] = self.scan_begin() if v == self.VIO_SCAN else self.scan_free(m[self.MBXARG])
            m[self.MBXST] = 0
            m[self.MBXSTAT] = 0x5A
            return
        if v in (self.FLOAD_OPEN, self.FLOAD_BLK) and self.scan_pending:
            m[self.MBXSTAT] = 0x3C; return                  # SCANREQ: a transaction before any scan
        if v in (self.FLOAD_OPEN, self.FLOAD_BLK):
            if not self.fast: m[self.MBXSTAT] = 0xA5; return
            m[self.MBXST] = 0
            if v == self.FLOAD_OPEN:                    # as fload_open in d64/tdrive_io.c: OPEN on secondary 0, the first two bytes
                self.fast_opens += 1
                self.drive.close(self.FL)
                name = bytes(m[self.WIN:self.WIN + m[self.MBXLEN]]).decode("latin1")
                dev = m[self.MBXARG]
                if dev not in self.drive.units: m[self.MBXDATA] = 5
                else:
                    self.drive.open(self.FL, dev, 0, name)
                    if self.drive.chans[self.FL].kind != "r": self.drive.close(self.FL); m[self.MBXDATA] = 4
                    else:
                        for i in range(2): m[self.WIN + i] = self.drive.get(self.FL)
                        m[self.MBXDATA] = 0
            else:                                       # fload_blk: up to 128 bytes, ST $40 with the last block, then the channel closes
                n, st = 0, 0x40
                if self.FL in self.drive.chans:
                    st = 0
                    while n < 128:
                        m[self.WIN + n] = self.drive.get(self.FL); n += 1
                        if self.drive.st & 0x40: st = 0x40; break
                    if st: self.drive.close(self.FL)
                    self.fast_blocks += 1
                m[self.MBXDATA] = n; m[self.MBXST] = st
            m[self.MBXSTAT] = 0x5A
            return
        if v != self.VIO_MENU: raise RuntimeError("mailbox command %d, not modelled" % v)
        self.mem[self.MBXSTAT] = 0x5A if self.menu_answer else 0x80
        self.menu = self.menu_answer

    # ---- KERNAL ----
    def setlfs(self): self.lfs = (self.cpu.a, self.cpu.x, self.cpu.y)

    def setnam(self):
        a = self.cpu.x | self.cpu.y << 8
        self.name = bytes(self.mem[a:a + self.cpu.a]).decode("latin1")

    def open(self):
        lf, dev, sa = self.lfs
        if lf in self.files: return self.ret(a=2, carry=1)
        if self.scan_pending and dev >= 4 and self.name:   # the agent's engine scans at the run's first OPEN, before it looks at the number
            self.inside = True
            self.scan_begin()
            for d in range(8, 31):
                if not self.released: break
                if d not in self.real: self.scan_free(d)
            self.inside = False
        if dev in self.real and dev not in self.drive.units: raise RuntimeError("OPEN %d,%d,%d,%r reached a real drive" % (lf, dev, sa, self.name))
        if dev not in self.drive.units: self.mem[STATUS] |= 0x80; return self.ret(a=5, carry=1)
        self.files[lf] = (dev, sa)
        self.drive.open(lf, dev, sa, self.name)
        self.ret(carry=0)

    def flush(self):
        if self.outp is not None and self.wbuf: self.drive.put(self.outp, self.wbuf.decode("latin1"))
        self.wbuf = bytearray()

    def close(self):
        lf = self.cpu.a
        if lf == self.outp: self.flush(); self.outp = None
        if lf == self.inp: self.inp = None
        if self.files.pop(lf, None) is not None: self.drive.close(lf)
        self.cmdbuf.pop(lf, None)
        self.ret(carry=0)

    def chkin(self):
        lf = self.cpu.x
        if lf not in self.files: return self.ret(a=3, carry=1)
        self.inp = lf; self.ret(carry=0)

    def chkout(self):
        lf = self.cpu.x
        if lf not in self.files: return self.ret(a=3, carry=1)
        self.flush(); self.outp = lf; self.ret(carry=0)

    def clrchn(self):
        self.flush(); self.inp = self.outp = None

    def chrin(self):
        if self.inp is None: raise RuntimeError("CHRIN from the keyboard is not modelled")
        if self.mem[STATUS]: return self.ret(a=13)
        dev, sa = self.files[self.inp]
        if sa == 15:
            buf = self.cmdbuf.get(self.inp) or bytearray((self.drive.getline(self.inp) + "\r").encode("latin1"))
            b = buf.pop(0); st = 0 if buf else 64
            self.cmdbuf[self.inp] = buf
        else:
            b = self.drive.get(self.inp); st = self.drive.st
        self.mem[STATUS] |= st
        self.ret(a=b, carry=0)

    def chrout(self):
        if self.outp is None:                       # the text colour is $0286, as in the KERNAL: a colour code sets it, a program may too
            self.screen.color = self.mem[TXTCOL] & 15; self.screen.put(self.cpu.a); self.mem[TXTCOL] = self.screen.color
        else: self.wbuf.append(self.cpu.a)
        self.ret(carry=0)

    def getin(self):
        if not self.keys: return "wait"
        self.ret(a=self.keys.pop(0), carry=0)

    def plot(self):
        if self.cpu.p & self.cpu.CARRY: return self.ret(x=self.screen.r, y=self.screen.c)
        self.screen.r, self.screen.c = min(24, self.cpu.x), min(39, self.cpu.y)

    def listen(self): self.ldev = self.cpu.a

    def second(self):
        if self.ldev not in self.drive.units and self.ldev not in self.real: self.mem[STATUS] |= 0x80

    def unlsn(self): pass
