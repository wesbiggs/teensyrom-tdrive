; TDSUITE's machine-code checks (tests/basic/tdsuite.bas, sections 11-14): BUSTEST, LOADTEST, VAULTTEST and REUTEST, each in its own
; scope, appended to the tokenized BASIC program by tools/suite_files.py (build_tdsuite) and linked right after it. LOAD sets the
; start of BASIC variables ($2D/$2E) to the end of the file, so the code survives RUN; TDSUITE finds the jump table below as the
; last 14 bytes before that address ("TD" + four JMPs). TDSUITE lowers the top of BASIC to $6000 first, so REUTEST's buffers
; ($6000-$9FFF) and the strings stay apart.
; Assembled with -I tests/asm; MBX/WIN may be given with -D (the VICE mock's mailbox), as for the old stand-alone BUSTEST.

.scope bus
.include "bustest.s"
.endscope

.scope load
.include "loadtest.s"
.endscope

.scope vault
.include "vaulttest.s"
.endscope

.scope reu
.include "reutest.s"
.endscope

.segment "JUMPS"
        .byte "TD"                      ; the tag TDSUITE checks (PETSCII = ASCII here)
        jmp bus::start                  ; TDSUITE: SYS mc (mc = the start of variables - 12)
        jmp load::start                 ; mc+3
        jmp vault::start                ; mc+6
        jmp reu::start                  ; mc+9
