#!/usr/bin/env python3
"""Edits of TeensyROM files outside the firmware for tools/make_tr_patch.sh, run in its work tree: TDrive Config in the C64 project
manifest (and the manifest test's project count), its rows in the C64 docs, and the TDrive parts of docs/ControlComms.md and
docs/Architecture/Disk-Images.md. Every edit asserts on the unpatched text, as make_tr_patch.sh's own do.

usage: tr_docs.py CONTROLCOMMS_SECTION     (firmware/tr-docs/ControlComms-tdrive.md: the "TDrive Get / Set" section)
"""
import sys

def edit(path, old, new):
    s = open(path).read()
    assert s.count(old) == 1, (path, old)
    open(path, "w").write(s.replace(old, new))

edit("tools/c64-projects.json", '    {\n      "name": "C128PrgBoot",\n',
     '''    {
      "name": "TDriveConfig",
      "description": "TDrive Config, in the TR menu with a TDrive Special IO: edits the Alt-button disk lists and the mounted images. Source: teensyrom-tdrive util/tdconfig.asm, copied unchanged by its make_tr_patch.sh.",
      "dir": "Source/C64/TDriveConfig",
      "steps": [
        { "assembler": "acme", "source": "tdconfig.asm", "output": "tdconfig.prg", "format": "cbm" }
      ],
      "headers": [
        { "input": "build/tdconfig.prg", "dest": "tdconfig.prg.h", "progmem": true }
      ]
    },
    {
      "name": "C128PrgBoot",
''')
edit("tools/lib/c64-projects.test.mjs", "  assert.equal(projects.length, 16);\n", "  assert.equal(projects.length, 17);\n")
edit("Source/C64/README.md", "| `C128PrgBoot` |",
     "| `TDriveConfig` | TDrive Config: edits the Alt-button disk lists and the mounted images (TR menu, TDrive Special IOs). "
     "Its source is teensyrom-tdrive's `util/tdconfig.asm`, copied unchanged by that repository's `tools/make_tr_patch.sh` |\n| `C128PrgBoot` |")
edit("docs/Architecture/C64-Software.md", "| `TRCustomBasicCommands` |",
     "| `TDriveConfig` | `TDriveConfig` | TDrive Config, the TDrive Special IOs' disk-list and mount editor. Its source is teensyrom-tdrive's "
     "`util/tdconfig.asm`, copied unchanged by that repository's `tools/make_tr_patch.sh` (change it there); it is at the project root, not in "
     "`source/`, and builds `tdconfig.prg` (header `tdconfig.prg.h`, array `tdconfig_prg`) |\n| `TRCustomBasicCommands` |")
edit("docs/Architecture/Disk-Images.md",
     "The TR block device (`TRBlockIO.c`) uses it with an `FsFile`. VDrive takes it when it moves onto this tree: its\n"
     "units keep their own dirty flag and idle timer today, and flush through `File::flush()`, which drops a failed sync.\n",
     "The TR block device (`TRBlockIO.c`) and the TDrive units (`IOH_TDrive.c`, the firmware's name for VDrive) both use it with\n"
     "an `FsFile`: each unit keeps a `struct ImageWriteBack`, records its writes, and syncs through `FsFile::sync()` so a sync\n"
     "the card fails leaves the image dirty and is tried again.\n")
# the TDrive remote commands, which host apps (Trom API, c64cast) read as the contract
edit("docs/ControlComms.md", "\nWhile the ASID Player is running, Ping and the file operations",
     "\nWhile a TDrive Special IO runs a C64 program, GetDirectory and GetDirNDJSON are also accepted, so a client can browse for a disk "
     "image to mount. The drive must be quiet first: the board waits up to 3 s for the C64's drive to go idle, then answers `FailToken` "
     "and the line `C64 is busy with the drive`. `TDriveGetToken` and `TDriveSetToken` are not Busy-gated at all; see "
     "[TDrive Get / Set](#tdrive-get--set).\n\nWhile the ASID Player is running, Ping and the file operations")
edit("docs/ControlComms.md", "|DebugToken        | 0x6467  |",
     "|TDriveGetToken    | 0x64E3  | Read what a TDrive unit has mounted (see [TDrive Get / Set](#tdrive-get--set)) |\n"
     "|TDriveSetToken    | 0x64E4  | Mount a disk image on a TDrive unit, or unmount (see [TDrive Get / Set](#tdrive-get--set)) |\n"
     "|DebugToken        | 0x6467  |")
edit("docs/ControlComms.md", "### Set Color Reference\n", open(sys.argv[1]).read() + "### Set Color Reference\n")
