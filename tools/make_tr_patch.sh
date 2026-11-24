#!/bin/sh
# Generate firmware/teensyrom-tdrive.patch against a TeensyROM checkout.
# usage: tools/make_tr_patch.sh /path/to/TeensyROM
#        TD_DMA_LOAD=0 tools/make_tr_patch.sh /path/to/TeensyROM   -> build/teensyrom-tdrive-nodma.patch: no DMA LOAD, neither the firmware's
#        Fab04_TDriveDMALoad nor the KERNAL's request (the upstream TeensyROM build, docs/DESIGN.md 49); firmware/ is left alone
set -e
TD_DMA_LOAD="${TD_DMA_LOAD:-1}"; export TD_DMA_LOAD
TR="$1"; [ -d "$TR/Source/Teensy/MinimalBoot/Common" ] || { echo "usage: $0 /path/to/TeensyROM"; exit 1; }
HERE="$(cd "$(dirname "$0")/.." && pwd)"
# The D64/D71/D81 engine is TeensyROM's own (Source/Teensy/DiskImage, shared with GEOS, the TR block device and the menu): the patch
# carries no copy. d64/d64.c, d64.h, DiskImage.h and WriteBack.h here are copies of it for the host tests, and must match the tree's exactly.
for f in d64.c d64.h DiskImage.h WriteBack.h; do
   [ -f "$TR/Source/Teensy/DiskImage/$f" ] || { echo "$TR has no Source/Teensy/DiskImage/$f: TDrive needs a tree with the shared disk image engine" >&2; exit 1; }
   cmp -s "$HERE/d64/$f" "$TR/Source/Teensy/DiskImage/$f" || { echo "d64/$f differs from $TR/Source/Teensy/DiskImage/$f: copy the tree's into d64/ (or the change to the tree) and re-test" >&2; exit 1; }
done
C=Source/Teensy/MinimalBoot/Common
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
mkdir -p "$W/$C/IO_Handlers"
for f in Common_Defs.h Menu_Regs.h IOHandlers.h ISRs.c IO_Handlers/StatusFunctions.c IO_Handlers/IOH_KernalReplace.c IO_Handlers/Swift_ATcommands.c IO_Handlers/IOH_Swiftlink.c; do cp "$TR/$C/$f" "$W/$C/$f"; done
mkdir -p "$W/Source/Teensy"; cp "$TR/Source/Teensy/Teensy.ino" "$TR/Source/Teensy/IOHandlers.ino" "$TR/Source/Teensy/SerUSBIO.ino" "$TR/Source/Teensy/MainMenuItems.h" "$TR/Source/Teensy/C128Prg.ino" "$W/Source/Teensy/"
M=Source/C64/MainMenuCRT/source; mkdir -p "$W/$M" "$W/Source/Teensy/TRMenuFiles/ROMs"
cp "$TR/$M/MainMenu.asm" "$TR/$M/PRGLoadStartReloc.s" "$W/$M/"; cp "$TR/Source/Teensy/TRMenuFiles/ROMs/TeensyROMC64.h" "$W/Source/Teensy/TRMenuFiles/ROMs/"
B128=Source/C64/C128PrgBoot; mkdir -p "$W/$B128"; cp "$TR/$B128/C128PrgBoot.asm" "$W/$B128/"; cp "$TR/Source/Teensy/TRMenuFiles/ROMs/C128PrgBoot.bin.h" "$W/Source/Teensy/TRMenuFiles/ROMs/"
# the tree's docs that describe TDrive, and the C64 project manifest that builds TDrive Config (with the manifest's own test)
mkdir -p "$W/docs/Architecture" "$W/tools/lib" "$W/Source/C64"
cp "$TR/docs/ControlComms.md" "$W/docs/"; cp "$TR/docs/Architecture/Disk-Images.md" "$TR/docs/Architecture/C64-Software.md" "$W/docs/Architecture/"
cp "$TR/tools/c64-projects.json" "$W/tools/"; cp "$TR/tools/lib/c64-projects.test.mjs" "$W/tools/lib/"; cp "$TR/Source/C64/README.md" "$W/Source/C64/"
cd "$W"; git init -q; git add -A; git -c user.name=x -c user.email=x@x commit -qm base

python3 -I - "$C" "$HERE/firmware/REV" "$HERE/firmware/tdrive_remote.inc" "$HERE/firmware/tdrive_probe.asm" <<'PY'
import os, sys
C = sys.argv[1]
def edit(path, old, new):
    s = open(path).read()
    assert s.count(old) == 1, (path, old)
    open(path, "w").write(s.replace(old, new))
edit(f"{C}/Common_Defs.h",
     "   #define Fab04_KernalReplace        //include Kernal Replacement support\n",
     "   #define Fab04_KernalReplace        //include Kernal Replacement support\n"
     "   #define Fab04_TDrive               //virtual IEC drive for the replacement KERNAL (needs Fab04_KernalReplace)\n"
     + ("   #define Fab04_TDriveDMALoad        //TDrive LOAD writes C64 RAM by DMA (needs Fab04_FullDMACapable); off: the 128-byte window only\n"
        if os.environ["TD_DMA_LOAD"] != "0" else ""))
# both boards: the drive through the KERNAL's RAM vectors and a 6502 agent served from IO1 (docs/DESIGN.md 53; IOH_TDriveAgent.c)
edit(f"{C}/Common_Defs.h",
     "   #define Fab04_DebugSignals         //For debug only\n#endif\n",
     "   #define Fab04_DebugSignals         //For debug only\n#endif\n"
     "#define TDrive_Agent   //virtual IEC drive through the KERNAL's RAM vectors and a 6502 agent served from IO1 (no Kernal Replace)\n"
     "#define TDrive_Any     //any TDrive Special IO: the agent, and on the TR+ the replacement-KERNAL ones (Fab04_TDrive)\n")
# #85's AT/browser-command PIT unmask (SwiftLink dispatch) also for the TDrive Special IOs: TDrive+SwiftLink runs AT commands while the
# replaced KERNAL is served. The loop poll itself needs no edit: the TDrive launch goes through InitHndlr_KERNALReplace_PreStart(),
# whose FnetLoopPollStart() sets FnetPollHold.
for old in ("#ifdef Fab04_GlobalKernalReplace\nextern volatile bool FnetLoopPoll;",
            "#ifdef Fab04_GlobalKernalReplace\n            //SwiftLink can run while the KERNAL is replaced",
            "#ifdef Fab04_GlobalKernalReplace\n            if (FnetLoopPoll) NVIC_DISABLE_IRQ(IRQ_PIT);"):
    edit(f"{C}/IO_Handlers/IOH_Swiftlink.c", old,
         old.replace("#ifdef Fab04_GlobalKernalReplace", "#if defined(Fab04_GlobalKernalReplace) || defined(Fab04_TDrive)"))
# The Alt-button trace (IOH_TDrive.c TD_Trace*, docs/DESIGN.md 60): which action a press goes to, and the trace kept across a
# reboot copied before upstream prints (and clears) the CrashReport, while no serial monitor is listening yet.
edit("Source/Teensy/Teensy.ino",
     "      if (fSpecialBtnChange != NULL) fSpecialBtnChange(SpecialBtnBounce.read());\n",
     "#ifdef Fab04_TDrive\n      TD_TraceButton(SpecialBtnBounce.read());\n#endif\n"
     "      if (fSpecialBtnChange != NULL) fSpecialBtnChange(SpecialBtnBounce.read());\n")
edit("Source/Teensy/Teensy.ino",
     "   if (CrashReport) Serial.print(CrashReport);\n",
     "#ifdef Fab04_TDrive\n   TD_TraceBoot();\n#endif\n"
     "   if (CrashReport) Serial.print(CrashReport);\n")
import re
base = re.search(r'#define TRVersion\s+"([^"]+)"', open(f"{C}/Common_Defs.h").read()).group(1)
rev = open(sys.argv[2]).read().strip()                      # firmware/REV: bumped by hand on firmware-affecting commits
td_version = f"{base}.{rev}" if base.count(".") >= 2 else f"{base}.0.{rev}"   # e.g. 0.9 -> 0.9.0.1 (digits and dots only: the flash tool parses it)
edit(f"{C}/Common_Defs.h",
     f'#define TRVersion              "{base}"    //*VERSION*',
     f'#define TRVersion              "{td_version}"    //*VERSION*  (stock {base} + TDrive rev {rev})')
edit(f"{C}/Common_Defs.h",
     "#define FWFullToken       0x64E2  // Full firmware response\n",
     "#define FWFullToken       0x64E2  // Full firmware response\n"
     "#define TDriveGetToken    0x64E3  // TDrive: read what a unit has mounted\n"
     "#define TDriveSetToken    0x64E4  // TDrive: mount an image on a unit / unmount\n")
edit("Source/Teensy/SerUSBIO.ino",
     "      case FWCheckToken: //Check firmware type\n         SendU16(FWFullToken);\n         return;   \n",
     "      case FWCheckToken: //Check firmware type\n         SendU16(FWFullToken);\n         return;   \n"
     "#ifdef TDrive_Any\n      case TDriveGetToken:  //TDrive disk image of a unit (works while a C64 program runs)\n      case TDriveSetToken:  //TDrive change the disk image of a unit\n"
     "         TDriveRemoteCommand(TokenVal == TDriveSetToken);\n         return;\n#endif\n")
edit("Source/Teensy/SerUSBIO.ino",
     "FLASHMEM bool ReceiveFileName(RegMenuTypes* DriveType, char *FileNamePath)\n",
     open(sys.argv[3]).read() + "\nFLASHMEM bool ReceiveFileName(RegMenuTypes* DriveType, char *FileNamePath)\n")
# Inserted after the ASIDAllowed statement and not by rewriting the "Busy!" test below it: upstream PRs add lines inside
# that test (the RTC command's refusal), and a hunk that rewrites its condition would not apply on top of them.
edit("Source/Teensy/SerUSBIO.ino",
     "       TokenVal == CopyFileToken     || TokenVal == DeleteFileToken);\n",
     "       TokenVal == CopyFileToken     || TokenVal == DeleteFileToken);\n"
     "#ifdef TDrive_Any\n"
     "   //TDrive running a C64 program: directory listings (so a client can browse for an image to mount) once the drive is quiet;\n"
     "   //  ASIDAllowed is only read by the Busy! test below, so it doubles as \"allowed while a program runs\"\n"
     "   if (TD_IsHandler(CurrentIOHandler) && (TokenVal == GetDirectoryToken || TokenVal == GetDirNDJSONToken))\n   {\n"
     "      char Msg[64];\n      if (TDrive_RemoteQuiet(Msg, sizeof Msg))\n      {\n         SendU16(FailToken);\n         CmdChannel->printf(\"%s\\n\", Msg);\n         return;\n      }\n"
     "      ASIDAllowed = true;\n   }\n"
     "#endif\n")
edit(f"{C}/Common_Defs.h",
     "   eepAdNext          = 4235, // Next address to be used\n",
     "   eepAdTDriveDevs    = 4235, // (2:uint8_t x2)  TDrive KERNAL device numbers of the SD / USB units, 0 = default (TD_DEV0/1)\n"
     "   eepAdNext          = 4237, // Next address to be used\n")
edit("Source/Teensy/Teensy.ino",
     "   //future use:\n",
     "#ifdef TDrive_Any\n   EEPROM.write(eepAdTDriveDevs, 0);   //TDrive device numbers: 0 = defaults (8/9)\n   EEPROM.write(eepAdTDriveDevs+1, 0);\n#endif\n\n   //future use:\n")
# The TDrive entries go *after* every upstream selectable entry (after IOH_USBMouse, the last since upstream 239cb5f0; IOH_GeoRAM before), so upstream's own handlers keep
# their indices (a stored default Special IO, eepAdNextIOHndlr, still means the same one after flashing this build) and the TDrive
# ones form a block at the end of the Special IO list. LastSelectableIOH moves to the last TDrive entry. (Include order is separate
# and stays after IOH_KernalReplace.c, which IOH_TDrive.c needs.)
TD_ENUM = ("   #ifdef Fab04_TDrive\n      IOH_TDrive,\n      IOH_TDriveSwift,\n   #ifdef Fab04_REU\n      IOH_TDriveSwiftREU,\n      IOH_TDriveREU,\n   #endif\n   #endif  \n"
           "   #ifdef TDrive_Agent\n      IOH_TDriveAgent,\n   #endif  \n")
edit(f"{C}/Menu_Regs.h",
     "      IOH_USBMouse, //last manually selectable, see LastSelectableIOH\n",
     "      IOH_USBMouse, //last manually selectable, see LastSelectableIOH\n" + TD_ENUM)
edit(f"{C}/Menu_Regs.h",
     "#define LastSelectableIOH  IOH_USBMouse  //127 max.  Used in IOH_TeensyROM.c for Special IO display/select\n",
     "#define LastSelectableIOH  IOH_USBMouse  //127 max.  Used in IOH_TeensyROM.c for Special IO display/select\n"
     "#ifdef TDrive_Agent\n   #undef LastSelectableIOH\n   #define LastSelectableIOH  IOH_TDriveAgent   //the TDrive entries follow upstream's; the agent is last on both boards\n#endif\n")
edit(f"{C}/IOHandlers.h",
     '   #ifdef Fab04_KernalReplace\n      #include "IO_Handlers/IOH_KernalReplace.c"\n   #endif    \n',
     '   #ifdef Fab04_KernalReplace\n      #include "IO_Handlers/IOH_KernalReplace.c"\n   #endif    \n'
     '   #ifdef TDrive_Any\n      #include "IO_Handlers/IOH_TDrive.c"\n   #endif    \n'
     '   #ifdef TDrive_Agent\n      #include "IO_Handlers/IOH_TDriveAgent.c"   //needs IOH_TDrive.c\n   #endif    \n')
edit(f"{C}/IOHandlers.h",
     "      &IOHndlr_USBMouse,           //IOH_USBMouse,\n",
     "      &IOHndlr_USBMouse,           //IOH_USBMouse,\n"
     "   #ifdef Fab04_TDrive\n      &IOHndlr_TDrive,             //IOH_TDrive,\n      &IOHndlr_TDriveSwift,        //IOH_TDriveSwift,\n   #ifdef Fab04_REU\n      &IOHndlr_TDriveSwiftREU,     //IOH_TDriveSwiftREU,\n      &IOHndlr_TDriveREU,          //IOH_TDriveREU,\n   #endif\n   #endif  \n"
     "   #ifdef TDrive_Agent\n      &IOHndlr_TDriveAgent,        //IOH_TDriveAgent,\n   #endif  \n")
edit(f"{C}/IOHandlers.h",
     '      #include "IO_Handlers/IOH_Swiftlink.c"\n',
     '      #include "IO_Handlers/IOH_Swiftlink.c"\n'
     '   #ifdef Fab04_TDrive\n      #include "IO_Handlers/IOH_TDriveSwift.c"   //needs IOH_TDrive.c and IOH_Swiftlink.c above\n'
     '   #ifdef Fab04_REU\n      #include "IO_Handlers/IOH_TDriveREU.c"        //needs IOH_TDrive.c and IOH_REU.c above\n      #include "IO_Handlers/IOH_TDriveSwiftREU.c"   //needs IOH_TDriveSwift.c and IOH_TDriveREU.c above\n   #endif\n   #endif\n')
edit(f"{C}/IO_Handlers/StatusFunctions.c",
     "      NextIOHndlr = MenuSource[SelItemFullIdx].IOHndlrAssoc;\n",
     "      NextIOHndlr = MenuSource[SelItemFullIdx].IOHndlrAssoc;\n"
     "#ifdef Fab04_TDrive\n      NextIOHndlr = TDriveSwift_Remap(NextIOHndlr);   //SwiftLink programs keep the virtual drive\n#endif\n")
edit(f"{C}/IO_Handlers/StatusFunctions.c",
     "   if (NextIOHndlr == IOH_KernalReplace)\n   {\n      InitHndlr_KERNALReplace_PreStart(); //separate function so it doesn't get called twice\n",
     "   if (NextIOHndlr == IOH_KernalReplace\n#ifdef Fab04_TDrive\n       || TD_IsKernalHandler(NextIOHndlr)\n#endif\n      )\n   {\n"
     "#ifdef Fab04_TDrive\n      KernalImageSource = TD_IsKernalHandler(NextIOHndlr) ? &TD_KernalImage : NULL; //TDrive: its own image (IOH_TDrive.c), not the <Shift-K> file\n"
     "      if (TD_IsKernalHandler(NextIOHndlr)) TDrive_NoteLaunch(); //the menu source and image path for the auto-mount, before FreeDriveDirMenu() resets them\n"
     "#ifdef Fab04_REU\n      if (NextIOHndlr == IOH_TDriveREU || NextIOHndlr == IOH_TDriveSwiftREU) FreeDriveDirMenu(); //the REU's AllocRAMBanks frees it anyway; first, so the drive's open Files fill its hole instead of pinning it under the heap top (docs/DESIGN.md 50)\n#endif\n"
     "#endif\n"
     "      InitHndlr_KERNALReplace_PreStart(); //separate function so it doesn't get called twice\n"
     "#ifdef Fab04_TDrive\n      if (TD_IsKernalHandler(NextIOHndlr)) TDrive_PreStart(); //SD/USB probing now, while the C64 still waits\n#endif\n")
# The TDrive Special IOs serve their own KERNAL (/TDrive/kernal.bin, else the C64's own ROM patched in memory; docs/DESIGN.md 40):
# PreStart takes the image from KernalImageSource when one is set, the <Shift-K> file otherwise. The file branch stays where it
# is, only braced, so the hunks are two small insertions.
edit(f"{C}/IO_Handlers/IOH_KernalReplace.c",
     "FLASHMEM void InitHndlr_KERNALReplace_PreStart() //not called automatically via init; called earlier, manually, from KERNALPreStart()\n",
     "#ifdef Fab04_TDrive\n"
     "bool (*KernalImageSource)(uint8_t *Bin) = NULL; //fills Bin (8192 bytes) instead of the <Shift-K> file, false: nothing to serve (TDrive, set by KERNALPreStart())\n"
     "#endif\n\n"
     "FLASHMEM void InitHndlr_KERNALReplace_PreStart() //not called automatically via init; called earlier, manually, from KERNALPreStart()\n")
edit(f"{C}/IO_Handlers/IOH_KernalReplace.c",
     "   //load kernal image into RAM:\n",
     "#ifdef Fab04_TDrive\n"
     "   if (KernalImageSource != NULL)\n   {\n      if (!KernalImageSource(KernalBin)) return; //KernalLoaded stays false: nothing hooked\n   }\n   else\n#endif\n"
     "   {\n   //load kernal image into RAM:\n")
edit(f"{C}/IO_Handlers/IOH_KernalReplace.c",
     "   Serial.printf(\"Read %lu Bytes\\nKernal replace Enabled\\n\", CharNum);\n   LoadFile.close();\n",
     "   Serial.printf(\"Read %lu Bytes\\nKernal replace Enabled\\n\", CharNum);\n   LoadFile.close();\n   }\n")
# The launch-time bus probe (docs/DESIGN.md 37). KERNALPreStart() first lets TDrive_ProbeStep() answer the menu's probe steps;
# the menu clears rwRegScratch before PreStart (a TeensyROM without TDrive never sets it, so its menu skips the probe) and runs
# TDriveProbe after it, with the C64's own KERNAL still in place.
edit(f"{C}/IO_Handlers/StatusFunctions.c",
     "   //called before BASIC init and program load/launch\n#ifdef Fab04_KernalReplace\n",
     "   //called before BASIC init and program load/launch\n"
     "#ifdef Fab04_TDrive\n   if (TDrive_ProbeStep()) return; //a step of the menu's bus probe after a TDrive PreStart (MainMenu.asm, TDriveProbe)\n#endif\n"
     "#ifdef TDrive_Agent\n   //the agent's drive (IOH_TDriveAgent.c): SD/USB probing now, while the C64 still waits; it serves no KERNAL\n"
     "   if (TDrive_AgentPreStart((IO1[rWRegCurrMenuWAIT] == rmtTeensy && MenuSource[SelItemFullIdx].IOHndlrAssoc != IOH_None) ?\n"
     "                            MenuSource[SelItemFullIdx].IOHndlrAssoc : IO1[rwRegNextIOHndlr])) return;\n#endif\n"
     "#ifdef Fab04_KernalReplace\n")
# The PRG loader (copied to the tape buffer, shared by both boards): once the new IO handler answers, the agent hooks the KERNAL's
# vectors (A = $A5: only those the program left as the ROM set them). Its ID at IO2 $DF09/$DF0A and the JSR of its INSTALL entry
# at $DE14 must both be there: no other handler answers that way.
edit("Source/C64/MainMenuCRT/source/PRGLoadStartReloc.s",
     "smcSkipPrintRunning:\n",
     "   ;TDrive agent (teensyrom-tdrive, docs/DESIGN.md 53): let it hook the KERNAL's vectors now that the program is in memory\n"
     "   lda $df09\n   cmp #$d6\n   bne +\n   lda $df0a\n   cmp #$64\n   bne +\n   lda $de14\n   cmp #$20\n   bne +\n"
     "   lda #$a5\n   jsr $de14\n+\n"
     "smcSkipPrintRunning:\n")
# C128 mode (docs/DESIGN.md 56; upstream #96/#98): a TDrive Special IO runs as the agent there, after the drive's PreStart. The call goes
# after upstream's own Kernal Replace line, once the launch is certain, and before the reset is asked for.
edit("Source/Teensy/C128Prg.ino",
     '   SendMsgPrintfln(PSTR("Starting C128 mode"));\n',
     '#ifdef TDrive_Agent\n'
     '   const bool TDriveAgent = TDrive_C128Launch(); //teensyrom-tdrive: with a TDrive Special IO this launch runs the agent (IOH_TDriveAgent.c)\n'
     '#endif\n'
     '   SendMsgPrintfln(PSTR("Starting C128 mode"));\n')
# ... and Exit to C128 BASIC (an empty program) then goes through the boot ROM as well, whose loader installs the agent (no RUN typed)
edit("Source/Teensy/C128Prg.ino",
     '   if (IsEmptyBasicPrg(Prg))\n   {\n      ExitToC128Basic();\n',
     '#ifdef TDrive_Agent\n'
     '   if (IsEmptyBasicPrg(Prg) && !TDriveAgent) //teensyrom-tdrive: with the agent, the boot ROM\'s loader installs it, so it runs this too\n'
     '#else\n'
     '   if (IsEmptyBasicPrg(Prg))\n'
     '#endif\n'
     '   {\n      ExitToC128Basic();\n')
# ... and the boot ROM's loader hooks the KERNAL's vectors through the agent once the handler swap is done, in the system bank
# (I/O in), before it types RUN: the same check and call as PRGLoadStartReloc.s above.
edit("Source/C64/C128PrgBoot/C128PrgBoot.asm",
     "        lda #SYSTEM_BANK\n        sta MMU_CR\n",
     "        lda #SYSTEM_BANK\n        sta MMU_CR\n"
     "        ; TDrive agent (teensyrom-tdrive, docs/DESIGN.md 56): let it hook the KERNAL's vectors now that the program is in memory\n"
     "        lda $df09\n        cmp #$d6\n        bne +\n        lda $df0a\n        cmp #$64\n        bne +\n"
     "        lda $de14\n        cmp #$20\n        bne +\n        lda #$a5\n        jsr $de14\n+\n"
     "        lda prgEnd              ; an empty program (Exit to C128 BASIC with the agent): BASIC without RUN\n"
     "        cmp #<(BASIC_START + 2)\n        bne +\n        lda prgEnd + 1\n        cmp #>(BASIC_START + 2)\n        bne +\n"
     "        jmp (BASIC_RESTART)\n+\n")
edit("Source/C64/MainMenuCRT/source/MainMenu.asm",
     ";Check for Kernal Replace Special IO and start it now\n   lda #rCtlKERNALPreStartWAIT\n   sta wRegControl+IO1Port\n"
     "   jsr WaitForTRDots ;use WaitForTRWaitMsg instead?\n",
     ";Check for Kernal Replace Special IO and start it now\n"
     "   lda #0\n   sta rwRegScratch+IO1Port ;TDrive: a nonzero answer asks for TDriveProbe\n"
     "   lda #rCtlKERNALPreStartWAIT\n   sta wRegControl+IO1Port\n"
     "   jsr WaitForTRDots ;use WaitForTRWaitMsg instead?\n"
     "   jsr TDriveProbe\n")
edit("Source/C64/MainMenuCRT/source/MainMenu.asm",
     "   ;rts ;SelectItem never returns\n\nAnyKeyErrMsgWait:\n",
     "   ;rts ;SelectItem never returns\n\n" + open(sys.argv[4]).read() + "AnyKeyErrMsgWait:\n")
# TDrive Config in the Teensy menu's Utilities, run with a TDrive Special IO (TDriveSwift_Remap picks the user's default one). After
# "LOAD"*",8,1 and RUN": the menu finds that entry and "Exit to BASIC" by their place in the list (items 2 and 3).
edit("Source/Teensy/MainMenuItems.h",
     '#include "TRMenuFiles/ROMs/ccgms_2021_Swiftlink_DE_38400.prg.h"\n',
     '#include "TRMenuFiles/ROMs/ccgms_2021_Swiftlink_DE_38400.prg.h"\n'
     '#ifdef TDrive_Any\n   #include "TRMenuFiles/ROMs/tdconfig.prg.h"\n#endif\n'
     '#ifdef Fab04_TDrive\n   #define IOH_TDriveMenu IOH_TDrive        //TDrive Config runs with the default TDrive Special IO (TDriveSwift_Remap)\n'
     '#else\n   #define IOH_TDriveMenu IOH_TDriveAgent   //the plain TR\'s only one\n#endif\n')
edit("Source/Teensy/MainMenuItems.h",
     ', (uint8_t*)Load8Run_prg               , sizeof(Load8Run_prg) , //used by location, see Load8Run:\n',
     ', (uint8_t*)Load8Run_prg               , sizeof(Load8Run_prg) , //used by location, see Load8Run:\n'
     '#ifdef TDrive_Any\n'
     '     rtFilePrg  , IOH_TDriveMenu   , (char*)"TDrive Config             +TDrive", (uint8_t*)tdconfig_prg               , sizeof(tdconfig_prg) ,\n'
     '#endif\n')
# A macro around the whole of IOHandlerSelectInit(), not an edit inside it: upstream PRs rewrite its first lines (#81 puts a
# GEOS case ahead of the menu one), and any hunk within three lines of them would not apply. The remap leaves every handler
# but SwiftLink, REU and TDrive alone (GEOS's GeoRAM / REU_TRPage pass through).
edit("Source/Teensy/IOHandlers.ino",
     "void IOHandlerSelectInit()\n",
     "#ifdef TDrive_Any\n"
     "   //menu programs keep the virtual drive: SwiftLink / REU ones get the matching TDrive Special IO (TDriveSwift_Remap)\n"
     "   #define IOHandlerInit(h) IOHandlerInit(TDriveSwift_Remap(h))\n"
     "#endif\n"
     "void IOHandlerSelectInit()\n")
edit("Source/Teensy/IOHandlers.ino",
     "   else IOHandlerNextInit();\n}\n",
     "   else IOHandlerNextInit();\n}\n"
     "#ifdef TDrive_Any\n   #undef IOHandlerInit\n#endif\n")
PY
cp "$HERE/firmware/IOH_TDrive.c" "$HERE/firmware/IOH_TDriveSwift.c" "$HERE/firmware/IOH_TDriveREU.c" "$HERE/firmware/IOH_TDriveSwiftREU.c" \
   "$HERE/firmware/IOH_TDriveAgent.c" "$C/IO_Handlers/"
# TDrive Config: its source (util/tdconfig.asm, ACME, unchanged) as a C64 project of the tree, so the tree's build-c64.mjs makes
# tdconfig.prg.h (below) and the tree's tests check that header against the source
TDC=Source/C64/TDriveConfig; mkdir -p "$TDC"
cp "$HERE/util/tdconfig.asm" "$TDC/"; printf 'build/*\n' > "$TDC/.gitignore"
# the host tests of the TDrive engine and handlers (firmware/tr-tests: node --test harnesses over the tree's own sources)
mkdir -p Source/Teensy/tests; cp "$HERE"/firmware/tr-tests/* Source/Teensy/tests/
# the manifest entry, the tree's docs (firmware/tr-docs/ControlComms-tdrive.md: the remote get / set section)
python3 -I "$HERE/tools/tr_docs.py" "$HERE/firmware/tr-docs/ControlComms-tdrive.md"
# the menu, rebuilt into its header (TeensyROMC64.h) by the TR's own tool (ACME 0.97, node), in a scratch copy of what it reads
B="$(mktemp -d)"; mkdir -p "$B/Source" "$B/$C"
cp -R "$TR/tools" "$B/"; cp -R "$TR/Source/C64" "$B/Source/"; cp "$C/Menu_Regs.h" "$B/$C/"
cp tools/c64-projects.json "$B/tools/"; cp -R "$TDC" "$B/Source/C64/"
cp "$M/MainMenu.asm" "$M/PRGLoadStartReloc.s" "$B/$M/"
cp "$B128/C128PrgBoot.asm" "$B/$B128/"
(cd "$B" && node tools/build-c64.mjs --project MainMenuCRT,C128PrgBoot,TDriveConfig --rom-dir "$W/Source/Teensy/TRMenuFiles/ROMs" >/dev/null)
cmp -s "$B/$M/Menu_Regs.i" "$TR/$M/Menu_Regs.i" || { echo "Menu_Regs.i would change: carry it in the patch" >&2; exit 1; }
rm -rf "$B"
mkdir -p "$C/tdrive"
cp "$HERE"/d64/tdrive.c "$HERE"/d64/tdrive.h \
   "$HERE"/d64/tdrive_io.c "$HERE"/d64/tdrive_io.h "$HERE"/d64/tdrive_vec.c "$HERE"/d64/tdrive_vec.h "$HERE"/d64/td_cfg.h "$C/tdrive/"
# d64.h from the shared engine (tests/fw_host/run.py lays its tree out the same way)
sed -i.bak 's|^#include "d64.h"$|#include "../../../DiskImage/d64.h"|' "$C/tdrive/tdrive.h"; rm "$C/tdrive/tdrive.h.bak"
grep -q '^#include "../../../DiskImage/d64.h"$' "$C/tdrive/tdrive.h" || { echo "tdrive.h: no d64.h include to point at DiskImage" >&2; exit 1; }
# the KERNAL patches as a table for TD_KernalPatchApply (our bytes only; the firmware lays them over the C64's own ROM)
python3 -I "$HERE/tools/build.py" --table "$C/tdrive/td_kpatch.h" -D "TD_DMA_LOAD=$TD_DMA_LOAD"
# the plain TR's agent (vector/tdagent.s) for IOH_TDriveAgent.c: linked at $DE08, registers at $DF00, window at $DF80
python3 -I "$HERE/tools/build_agent.py" "$C/tdrive/td_agent.h"
git add -A -N
if [ "$TD_DMA_LOAD" = 0 ]; then OUT="$HERE/build/teensyrom-tdrive-nodma.patch"; mkdir -p "$HERE/build"; else OUT="$HERE/firmware/teensyrom-tdrive.patch"; fi
git diff --no-color > "$OUT"
echo "wrote ${OUT#$HERE/} ($(grep -c '^+++ ' "$OUT") files)"
