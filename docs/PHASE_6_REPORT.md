# Phase 6 report: USB protocol and acknowledged machine control

Date: 2026-10-26. Version: **0.6.0** (application and firmware).

**Phase 6 software is complete and tested against simulated devices. No physical board ran the protocol.**

During this phase:

- no firmware was uploaded;
- no real serial port was opened by the tests;
- no motor moved.

All 543 original files still match the Phase 1 SHA-256 manifest.

## Implemented

Each item below follows the Phase 6 task list in [the roadmap](DEVELOPMENT_PLAN.md).

1. **Protocol first.** [SERIAL_PROTOCOL.md](SERIAL_PROTOCOL.md) was written before either endpoint. It covers:
   - framing: `@body*CRC16`, CCITT-FALSE, with bounded bodies of 90 bytes host to device and 120 device to host, kept separate from the 63-byte G-code payload;
   - session identity: the boot ID (an EEPROM counter) and the origin revision;
   - messages, error codes, duplicate and gap rules, and completion semantics;
   - the host-loss watchdog and host recovery rules;
   - OS serial permissions and troubleshooting.
2. **Firmware 0.6.0.**
   - The portable core gains a resynchronising `FrameReader` (one 96-byte frame buffer), CRC-16 and whole-token parsers.
   - Frames are written while the CRC is computed, with no transmit buffer.
   - `HELLO` and `STATUS` never move the machine and are answered in every state. `BEGIN` and `HOME` are accepted only when the menus are idle, which makes SD and USB jobs mutually exclusive.
   - The host can never set the origin.
3. **Host connection** (`backend/app/machine/`, pySerial 3.5).
   - Port listing never opens ports, and only a listed port can be opened, with exclusive access.
   - Connecting sends at most three read-only `HELLO 1` frames. A silent or non-Picasso device receives nothing else.
   - Protocol, dialect or capability mismatches leave the connection *incompatible*.
4. **Streaming.**
   - A dedicated worker sends one `M` frame at a time. It waits for `RCV` (validated on receipt), then for `ACK`, which the firmware sends only after the motion and any pen settling have finished.
   - Control requests (STATUS, PAUSE, RESUME, STOP) are written under the port write lock, never behind the motion wait.
   - Missing replies are resolved with `STATUS`, never by guessing:
     - a frame is retransmitted only when status proves `rx = seq − 1`;
     - a lost `ACK` is recovered from `done ≥ seq`;
     - silence becomes a fault with an unknown position, a best-effort STOP and no further motion.
   - The firmware never executes a sequence number twice: repeats get `RCV/ACK … DUP`, and gaps fail the job.
5. **Start, pause, resume and stop.**
   - Before starting, the host checks all of the following, then sends `BEGIN`, which the firmware checks again:
     - the job is a physical preparation against the current, selected, verified profile;
     - the profile records canonical firmware and its configuration ID equals the device's;
     - the boot ID and origin revision are the ones the operator reviewed;
     - the device is `IDLE` with a referenced origin;
     - the commanded position equals the job's start.
   - **A mismatch never causes a hidden travel.** The operator either prepares the job again or runs an explicit *Go to origin*: a confirmed route that the firmware validates against its workspace.
   - Pause finishes one motion slice, raises the pen and holds the coils. Resume always needs an explicit request.
   - Stop, from the host or ESC on the keypad, raises the pen and reports the unfinished command as `NAK … ABORTED`.
   - Device resets (a new boot ID), disconnects, missed polls and application restarts end the run as `fault` or `interrupted`. Nothing reconnects or resumes automatically.
   - **Firmware watchdog:** a host job is stopped with `HOST_LOST` after 3 s without frames.
6. **Reporting.**
   - `UsbRun` records acknowledged progress, the executing line and the commanded position, with `measured_feedback: false`.
   - Runs persist in a new additive `runs` table. On startup, active runs become `interrupted`.
   - The studio shows the connection, firmware, configuration match, session, origin, commanded position, device state and last result.
7. **Studio and docs.**
   - The *Machine* tab has a **USB machine** panel. The physical job dialog gains *4. Or draw over USB*, with a precondition checklist, an area-clear confirmation, live progress and pause, resume and stop. The footer shows the connection state.
   - Serial permissions and drivers for Linux, Windows and macOS are documented. Flashing remains a manual step.
   - The commissioning guide gains USB checks (§10).

**Simulated device for development and tests.** With `PICASSO_SIMULATED_DEVICE=1`, the port list includes *Simulated Picasso firmware (host simulation, not hardware)*.

- It runs the **real firmware sketch** in the host simulator's new `bridge` mode, with stdin and stdout as the serial port and time scaled from the wall clock (default ×3).
- The simulator's keypad script stands in for the operator's origin confirmation.
- It uses a synthetic configuration and is labelled as a simulation in the UI.

## Validation

Completed on Linux with Python 3.14.4, Node 22.22.1, npm 9.2.0, g++ 15.2.0 and pySerial 3.5.

### Totals

- **160 Python tests pass** (128 existing + 32 new). One upstream Starlette/httpx deprecation warning remains.
- **133 C++ core checks pass**, adding frame and CRC tests:
  - the `123456789` → `29B1` check value;
  - CRLF, bad CRC, bad hex, embedded `*`, the 90/91-byte boundary, overflow, control bytes;
  - `@` resynchronisation after a truncated frame;
  - token parsers.

### Firmware protocol (8 tests on the simulated sketch)

- **Handshake.** Boot identity, HELLO and STATUS move nothing; version and unknown commands are refused.
- **BEGIN.** It refuses `NO_ORIGIN`, `SESSION`, `REFERENCE`, `POSITION` and `ARGS`, and `STATE` while an SD job waits at the keypad.
- **Completion and duplicates.** Commands are acknowledged only after completion, with a pen-down gap of at least 300 ms. Repeats while running or after completion are answered `DUP` and are not executed. A second command while one is pending gets `NAK BUSY`. Comments are ignored, and END produces `EVT COMPLETED`.
- **Invalid commands.** Gaps (`NAK SEQUENCE`) and out-of-workspace commands (`NAK OUT_REGION`) fail the job with zero steps.
- **Stop.** A host STOP aborts mid-travel with the pen up, coils held and `NAK 1 ABORTED`.
- **Watchdog.** With STATUS polling, a job waits indefinitely. With silence, it aborts with `HOST_LOST` and the pen up.
- **Bad frames.** Corrupted and oversized frames get `ERR FRAME CRC|LONG` and nothing happens. Keypad ESC stops a USB job.
- **HOME.** It is bound to the session and returns to (0,0).

### Host controller (18 fake-device tests)

- **Handshake.** Only read-only frames are sent. A silent device receives exactly three `HELLO 1` and nothing else. A version mismatch is *incompatible*.
- **Preconditions.** Nine unmet preconditions never send BEGIN or motion. A legacy-firmware profile cannot stream.
- **Ordering.** Each command is sent and executed exactly once, in order, and completion is persisted.
- **Priority stop.** While the device **holds a motion ACK**, a status snapshot answers in under 0.1 s and `STOP` is sent and handled before that ACK. No motion is sent after STOP.
- **Lost replies.** A lost ACK or a lost receipt causes no resend. A rejected frame is retransmitted once, **only after** a STATUS shows it was not received, and the device executes it once.
- **Failures.**
  - Silence leads to a fault, a STOP attempt and *lost*.
  - A mid-run reset leads to a fault and a new session.
  - Unplugging leads to a fault.
  - Duplicate or corrupted replies are ignored.
- **Pause and resume.** A held completion is not acknowledged or followed while paused. A second start is refused, and resume is refused when not paused.
- **HOME and restarts.** HOME needs confirmation and the current session. A restart marks active runs interrupted.

### End-to-end and API

- **4 end-to-end tests** with the Python controller driving the simulated sketch at ×4:
  - A prepared 40 mm circle completes. The device ends exactly at the last point with the pen up and coils held, and the pen-down count equals the stroke count.
  - Stop, then refusal of an implicit restart, then validated *Go to origin*, then a second job that completes.
  - Pause and resume complete the drawing.
  - When the host freezes, the firmware watchdog aborts with `HOST_LOST` and the pen up.
- **2 API tests:**
  - The endpoints work, `/api/machine` stays responsive while an ACK is held, and STOP works.
  - Unlisted port paths are refused (`PORT_NOT_LISTED`).

### Frontend and repository

- **5 component tests and 9 Chromium journeys pass.** The new journey connects to the simulated firmware, sees the configuration match and confirmed origin, prepares a physical job, passes all 4 checks and starts over USB. It watches the run reach `COMPLETED` with every command acknowledged, then disconnects.
- Contract drift check, typecheck, production build, the original-file manifest (`PASS`) and `git diff --check` all pass.

## Addendum: Execute over USB and the UNO build (firmware 0.6.1)

**Why.** The SD card is wired to the Arduino, so moving it to the computer for every drawing is the slow path. The goal is to generate, preview and draw from the studio.

**Finding.** Compiled for `arduino:avr:uno`, firmware 0.6.0 needs **38,878 / 32,256 B flash (120%)** and **2,088 / 2,048 B SRAM (101%)**. It could not be uploaded to an UNO. The committed 0.5.0 was also over, at 101% flash. A probe sketch puts the SD library alone at about 8.7 KB of flash and 676 B of SRAM.

**Changes.**

- **Firmware 0.6.1.**
  - `PICASSO_ENABLE_SD`, default `0`, compiles out the SD job path, and with it the SD library, file state and line reader.
  - The **USB-only** UNO build uses **28,118 B flash (87%)** and **1,317 B SRAM (64%)**, leaving 731 B for the stack.
  - Protocol v1, HELLO capabilities and configuration IDs are unchanged.
  - The main menu becomes *Setup*/*Info*. The Info screen and boot line state the build (`USB`/`USB+SD`, `SD OFF|ON`).
- **Build tooling.**
  - `scripts/firmware.py build --with-sd` selects the SD build.
  - Every Arduino build fails with less than 384 B of SRAM headroom.
  - CI builds the USB-only UNO configurations, plus USB+SD for `arduino:avr:mega`.
  - Host tests build both variants. The simulated device and the USB end-to-end tests run the USB-only build.
- **Port access.**
  - Listed ports report `accessible`, checked without opening them.
  - An `EACCES` open error explains the `dialout` fix.
- **Studio.**
  - An **Execute** button sits beside *Simulation*. Its sheet connects to the port and shows the verified profile, then prepares and checks the drawing automatically.
  - It lists the four start checks, offers *Go to origin* and asks for the area-clear confirmation **on every run**.
  - During a run, the preview shows acknowledged progress over a faint full path, the commanded position, and an always-visible **Stop**.
  - The footer follows the 1 s machine snapshot.

**Validation.**

| Area | Result |
| --- | --- |
| Python tests | **162** pass. New: the USB-only firmware variant, and port access and permission mapping. |
| Component tests | **8** pass, 3 new. |
| Chromium journeys | **10** pass. The new journey runs Execute → connect in the sheet → COMPLETED → Go to origin → second run → Stop from the preview → `aborted`. |
| Firmware compile | USB-only UNO compiles for fixture, `reference-350` and `reference-400`. USB+SD compiles for Mega. |

No board was flashed, and no motor moved.

## Not performed and pending

- **Hardware USB checks** (commissioning guide §10), with only the simulated firmware tested so far:
  - the real handshake and configuration ID;
  - reset on connect;
  - acknowledged motion matching the pen;
  - measured pause and stop latency from the studio and from the keypad;
  - cable pull leading to `HOST_LOST`;
  - SD/USB exclusion.
- **Flashing the USB-only build to the actual board.** The compile and memory report now exist; see the addendum. The build was made with the local `arduino:avr` 1.8.8 core, and CI pins 1.8.6.
- **Phase 4 and Phase 5 hardware checks**, which remain pending.

## Known limits

- **Commanded position only.** Progress and position are commanded estimates from acknowledged commands and step counts; there are no encoders.
- **Watchdog and simulation speed.** The 3 s watchdog requires the host's 0.5 s polling. A heavily loaded computer that stalls for more than 3 s stops the job, which is the safe outcome.
- **Serial buffer.** The ATmega328P hardware receive buffer is 64 bytes. A long frame arriving during a display redraw can be lost; the CRC and the `STATUS` recovery handle that without duplicate execution.
- **Jobs and positions.** One job runs at a time. Resuming a faulted run is intentionally unsupported: re-reference the origin and prepare again. A job's start must equal the current commanded position; only (0,0) starts are prepared today, so use *Go to origin* between jobs.
- **UNO and SD jobs.** The UNO build has no SD job menu. Drawing over USB replaces it, and the card can stay in the slot unused.
- **Platforms.** Serial discovery uses pySerial on Linux, macOS and Windows, but only Linux was exercised, and only with no real ports present.

## Handoff to Phase 7

The USB path accepts only validated, frozen jobs. Phase 7 AI interpretation must keep producing schema-checked drawing specifications that go through the same preparation pipeline, and must never emit G-code or protocol frames directly.

Screenshots: [studio](screenshots/phase-6-studio.png), [mobile](screenshots/phase-6-mobile.png), [test export](screenshots/phase-6-test-export.png), [firmware profile](screenshots/phase-6-firmware-profile.png), [USB run](screenshots/phase-6-usb-run.png), [Execute](screenshots/phase-6-execute.png).
