# Picasso serial protocol, version 1

Status: specification for Phase 6. The canonical firmware 0.6.0 (`firmware/WallDrawingMachine/`) and the host controller (`backend/app/machine/`) implement it. Both sides were tested against simulators. **No physical board has run this protocol yet.**

## Goals and non-goals

- Stream one prepared, immutable job over the existing USB-UART link, with acknowledgements that mean "this motion and pen change has finished".
- Keep status, pause and stop available while a motion acknowledgement is pending.
- Never execute a command twice, and never resend motion that might already have run. Never move during discovery, connection or handshake. Never start without a referenced origin, the expected position and a matching configuration.
- Not covered: firmware upload, upload to SD, speed control, measured feedback (there are no encoders), wireless links, and resuming after reset or reconnect.

## Physical link

- USB-UART at **115200 baud, 8N1**, no flow control.
- Opening the port can reset UNO-class boards (DTR). The host therefore waits for the handshake and treats every new **boot ID** as a new session with an **unknown position**.
- The host opens only the port the operator selected, with exclusive access where the OS supports it.
- Discovery lists ports without opening them. The host never probes or writes to unselected ports.

## Framing

```text
@<body>*<CRC>\n
```

- **`body`**: printable ASCII 0x20–0x7E without `@` or `*`. Tokens are separated by single spaces. An optional CR before the LF is accepted.
- **`CRC`**: CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no final XOR) over the body bytes, written as 4 uppercase hex digits. Python: `binascii.crc_hqx(body, 0xFFFF)`. Check value for `123456789`: `29B1`.
- **Size limits**:
  - host → device body: at most **90** bytes, so a frame is at most 96 bytes plus LF;
  - device → host body: at most **120** bytes;
  - G-code payload: at most **63** bytes, as before. Framing overhead is separate from it.
- **Firmware buffers**:
  - The firmware buffers one frame: 96 bytes plus NUL.
  - A frame that is too long, has a bad CRC or contains a bad byte is discarded and answered with `@ERR FRAME <LONG|CRC|FORMAT|BYTE>`.
  - **A rejected frame is never executed.**
  - Bytes outside a frame are ignored. A new `@` starts a fresh frame.
- **Log lines**: lines not starting with `@` are informational logs (for example `PICASSO FW ...`). The host ignores them.

## Session identity

- **Boot ID**: 8 hex digits from an EEPROM counter that increments on every reset. It changes on every reset.
- **Origin revision**: a counter, starting at 0 after boot, that increments each time the operator confirms *Set origin* on the keypad. A host can **never** set the origin; that physical confirmation stays local.
- **Configuration ID**: the 16-hex fingerprint of the compiled `machine_config.h` (see `firmware/README.md`). It must equal the verified profile's recorded ID.

## Messages: host to device

| Body | Allowed when | Reply |
| --- | --- | --- |
| `HELLO 1` | always | `HELLO 1 <fw> <dialect> <config_id> <boot> <caps>`; `ERR HELLO VERSION 1` if unsupported |
| `STATUS` | always | `ST ...` |
| `BEGIN <token> <x> <y> <boot> <orev>` | device `IDLE` | `OK BEGIN <token>`; or `ERR BEGIN <code>` |
| `M <seq> <gcode>` | own USB job running | `RCV <seq>`, then `ACK <seq> <x> <y>` or `NAK <seq> <code>` |
| `END <token>` | own USB job, nothing pending | `OK END <token>`; or `ERR END <code>` |
| `PAUSE` / `RESUME` | own USB job running or paused | `OK PAUSE` / `OK RESUME`; or `ERR ... STATE` |
| `STOP` | any job executing | `OK STOP`; or `ERR STOP STATE` |
| `HOME <boot> <orev>` | `IDLE` with a valid origin | `OK HOME`; or `ERR HOME <code>` |

`<caps>` is a comma-separated list. Version 1 reports `STREAM,PAUSE,STOP,HOME`. `<token>` is 8 lowercase hex digits chosen by the host. `<x> <y>` are fixed decimals in millimetres.

### BEGIN preconditions (checked by the firmware)

| Error code | Condition |
| --- | --- |
| `STATE` | The device is not `IDLE`. Menus, SD validation or ready, jog, pen test and any running job are all non-idle. **This makes SD and USB jobs mutually exclusive.** |
| `NO_REGION` | The firmware has no compiled workspace. |
| `NO_ORIGIN` | The origin was never referenced since boot, or the motors were released. |
| `SESSION` | `<boot>` is not the current boot ID. |
| `REFERENCE` | `<orev>` is not the current origin revision. |
| `POSITION` | The commanded position differs from `<x> <y>` by more than 0.0005 mm. |
| `ARGS` | The arguments are malformed. |

The device does not move to satisfy BEGIN. If the position does not match, either prepare the job again for the current start, or run an explicit `HOME`. `HOME` is a validated pen-up straight travel to (0,0) and fails without moving if any part of it leaves the workspace.

### Motion commands

- `<seq>` counts from 1 within a job and must be exactly the last received sequence + 1. The payload is one `picasso-fw-v1` line (see `GCODE_CONTRACT.md`).
- On receipt the device parses the line and validates the segment from its current commanded position against the workspace and rope limits, exactly as for SD jobs. It then replies `RCV <seq>`.
- Invalid lines get `NAK <seq> <code>` with a parser or geometry code. The line is **not executed**, and the job fails with the pen raised.
- `ACK <seq> <x> <y>` is sent only when the motion and any pen change (including settling) have **completed**. `<x> <y>` is the commanded position: an estimate from step counts, not a measurement.
- Only one motion command may be pending. A second one gets `NAK <seq> BUSY` and is not executed.
- **Duplicates.** A frame with `seq` equal to the received or completed sequence is never executed again. The reply is `RCV <seq> DUP` while it is running, or `ACK <seq> <x> <y> DUP` once it is done. A gap (`seq` greater than last + 1) gets `NAK <seq> SEQUENCE`, and the job fails.
- **Pause** finishes the current motion slice (at most one ≈0.054 mm sub-target), raises and settles the pen, and keeps the coils energized. The pending ACK is delayed until the job resumes and the motion completes. **Resume** lowers the pen only if it was down, waits for it to settle, and continues. Resume always needs an explicit request, from the host or from ENTER on the keypad.
- **Stop**, from the host or from ESC on the keypad, finishes the current slice, raises the pen and aborts the job. Any received but incomplete command gets `NAK <seq> ABORTED`; it may have run partly. The position is reported in the event.

### Host-loss watchdog

While a host-started job (`BEGIN` or `HOME`) is executing, the device stops it with reason `HOST_LOST` if no valid frame arrives for **3000 ms**. The host polls `STATUS` every 500 ms while connected, so a crashed application, a pulled cable or a closed port raises the pen within about 3 s plus one motion slice.

## Messages: device to host

- **`BOOT <boot> 1`**: sent once after reset.
- **`ST <state> <job> <boot> <orev> <origin> <x> <y> <pen> <rx> <done> <result>`**:
  - `state`: `IDLE`, `LOCAL`, `RUNNING`, `PAUSING`, `PAUSED`, `RESUMING` or `ENDING`. `LOCAL` means the operator is using the menus.
  - `job`: `-`, `SD`, `SQUARE`, `HOME` or `USB:<token>`.
  - `origin`: `UNSET`, `VALID` or `FRESH`.
  - `pen`: `UP` or `DOWN`.
  - `rx` and `done`: the last received and the last completed sequence of the current or previous USB job.
  - `result`: the last outcome, written `COMPLETED|ABORTED|FAILED|NONE:<reason>`.
- **`EVT <event> <job> <done> <x> <y> <reason>`**: `<event>` is `PAUSED`, `RESUMED`, `COMPLETED`, `ABORTED` or `FAILED`.
- **`RCV`, `ACK`, `NAK`, `OK`, `ERR`**: as described above.

Reason codes: `NONE`, `STOPPED` (keypad), `HOST_STOP`, `HOST_LOST`, `SEQUENCE`, `SD_INIT`, `NO_FILE`, `SD_READ`, `FILE_CHANGED`, `NO_MOVES`, and the parser and geometry codes (`BAD_NUMBER`, `OUT_REGION`, `ROPE_LIMIT` and so on).

## Host behaviour (backend/app/machine)

1. **Connect.** The operator selects one port and connects explicitly. The host sends `HELLO 1` up to three times, one second apart (it is read-only), waiting up to 6 s for boot. It accepts only protocol 1, dialect `picasso-fw-v1` and a `STREAM` capability. Anything else is *incompatible*, and the port is closed without sending any other frame.
2. **Start.** The operator starts a frozen physical job against the device's displayed boot ID and origin revision, and confirms that the area is clear. The host requires all of the following, then sends `BEGIN`:
   - the job is a physical preparation against the selected, current, verified profile;
   - the profile records `picasso-canonical` firmware;
   - the profile's configuration ID equals the device's;
   - a fresh `ST` reports `IDLE`, an origin that is not `UNSET`, and the same boot ID, origin revision and position as the job's expected start.
3. **Streaming.** One worker sends one `M` at a time and waits for `RCV`, then `ACK`. Control requests (`STATUS`, `PAUSE`, `RESUME`, `STOP`) are written directly under the port write lock, so they never wait for the motion lock or the pending ACK.
4. **Missing replies are checked, not guessed.**
   - **No `RCV` within 1 s, or `ERR FRAME`**: the host asks for `STATUS`. If `rx = seq - 1`, the device provably did not receive the frame, and the identical frame may be retransmitted, at most twice. If `rx = seq`, the frame was received and the host keeps waiting. In any other case, or if the status request fails, the run becomes a **fault**: the host sends `STOP` as a best effort and never sends motion again.
   - **No `ACK` by the estimated deadline**: the host asks for `STATUS`. If `done ≥ seq`, the ACK was lost and the host continues; nothing is resent. If the device is still `RUNNING` or paused on that sequence, the host extends the wait up to a hard limit (3 × the estimate + 30 s). Silence or a mismatch is a **fault** with unknown position.
5. **End.** After the last ACK the host sends `END` and waits for `EVT COMPLETED`.
6. **Reset, disconnect and restart.** A new boot ID, a disconnect, three missed status polls or an application restart end the run as `fault` or `interrupted`. Nothing reconnects or resumes automatically. A new run needs a new start request against the new session, and the origin must be referenced again on the keypad, because reset makes it `UNSET`.

Run records (`UsbRun`) persist to the local database. They count *acknowledged* commands and the *commanded* position; they are never presented as measured carriage feedback. On startup, any run still marked starting, streaming, pausing, paused or stopping becomes `interrupted`.

## Serial permissions and troubleshooting

- **Linux**: add your user to the group that owns the device (`ls -l /dev/ttyUSB0`, often `dialout` or `uucp`), then log in again. ModemManager can probe new modems; if it grabs the port, disable it for the device. The device should appear as `/dev/ttyUSB*` (CH340) or `/dev/ttyACM*`.
- **Windows**: install the CH340 driver (vendor `CH341SER.EXE` in `Drawbot_C/02 arduino code/Driver`, or a current one from the manufacturer). Use the `COMn` port shown in Device Manager. Close the Arduino IDE's Serial Monitor, because ports are exclusive.
- **macOS**: current macOS includes a CH34x driver (`/dev/cu.wchusbserial*`). Older systems need the vendor driver.
- **"Busy" or "permission denied"**: another program owns the port. Close it and reconnect explicitly.
- **No handshake**: the board runs the legacy sketch or older canonical firmware without the protocol, the wrong port was selected, or the board is still resetting. Upload firmware 0.6.0 or later (`firmware/README.md`). Uploading is always a separate, explicit maintenance step.
