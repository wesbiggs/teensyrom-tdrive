### TDrive Get / Set
Reads, or changes, the disk image a TDrive unit has mounted. Each unit is one of the two virtual drives: the SD card's and the USB drive's.

**Workflow:**
| Direction | Data |
|---|---|
| Receive | `TDriveGetToken` — `0x64E3` **or** `TDriveSetToken` — `0x64E4` |
| Receive | Drive (1): `USBDrive = 0`, `SD = 1` (as the file commands) |
| Receive | Set only: ImagePath, null-terminated, at most `MaxNamePathLength` bytes including the terminator. `"/dir/IMAGE.D64"` on that unit's own card; an empty string unmounts (the folder stays) |
| Send | `AckToken 0x64CC` and one line of JSON (the unit's state after the change), or `FailToken 0x9B7F` and one line of text with the reason |

Reasons include `Drive must be USB (0) or SD (1)`, `Path too long!`, `no such drive`, `path must start with /`, `file not found`, `not a disk image` (a folder, a name not ending in `.d64`, `.d71` or `.d81` in any case, or a file under 174848 bytes), `cannot mount (DOS error N)` and `C64 is busy with the drive`. A failed set leaves the current disk mounted. If the Drive byte or the path stops arriving, the board sends the text `Timeout!` and no `FailToken`.

The JSON line has these fields, in this order. While a TDrive handler runs: `unit` (0 = SD, 1 = USB, TDrive's own numbering, the reverse of the Drive byte), `storage` (`"sd"` or `"usb"`), `device` (the unit's current IEC device number), `fixed` (the device number pinned in settings, 0 = automatic), `mounted`, `writable`, `path` (host path of the image, `""` if none), `cwd` (the folder, `"/"` at the root), and on firmware that carries the border-flash debug counters a trailing `dbg` object. With the TR menu showing, or any other Special IO, the line instead has `unit`, `storage`, `running` (`false`), `device`, `fixed` (both the pinned device number, 0 = automatic), `mounted`, `writable` (always `true`), `path` and `cwd`; the `running` field is present only in that form.

**Idle mode.** When no TDrive handler is running, nothing is mounted. Get reports the image the unit will mount at its next start, which is the file `/.tdrive` in the root of that unit's card (if the image it names is gone, `mounted` is `false`); set checks the image and rewrites `/.tdrive`. It does not touch a running C64 program.

**Running mode.** A set waits for a quiet moment on the C64's drive (no LOAD or SAVE in flight, up to 3 s, polling the drive meanwhile), closes the unit's open channels, then mounts as the `CD:` DOS command would. If the C64 keeps the drive busy for the 3 s, the answer is `FailToken` and `C64 is busy with the drive`.

**Availability caveats.** These two commands are not gated by `Busy!`, and they have costs a client should know about:
  * Under any Special IO that is not a TDrive one, they take the idle path. That path reads `/.tdrive` and opens the named image on the SD card or USB drive (set also rewrites `/.tdrive`), and the main loop waits for it. A USB request with no stick present blocks the main loop for up to about 1.5 s while the board waits for the drive. Do not poll these commands; ask when a user acts.
  * During a TDrive run, while a remote command is reading its arguments (each wait for an argument byte can last up to `SerialTimoutMillis`, 500 ms) or sending a directory listing, the drive mailbox is not serviced. A C64 disk command issued meanwhile waits, and can hit the KERNAL's mailbox timeout of about 1.6 s. Send arguments promptly and request small directory pages (`Take`).

Firmware that predates these commands answers the tokens with `Unk cmd: 0x64e3` (or `0x64e4`), or `Busy!` from the minimal image, and would read anything sent after them as commands of its own. A sender that waits for the first `AckToken` or `FailToken` stops there. A firmware build without TDrive answers the same way.

**Handler:** `TDriveRemoteCommand(bool Set)`

---

