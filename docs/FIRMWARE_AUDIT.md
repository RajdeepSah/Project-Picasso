# Firmware audit — Phase 1

Audit date: 2026-10-24. This report describes files present in the workspace, not a verified image read from the Arduino. No firmware was modified or uploaded during Phase 1.

## Sources and baseline decision

- `WallDrawingMachine.ino` is **empty (0 bytes)**. It cannot establish the machine's current pin map or behavior.
- `Drawbot_C/02 arduino code/Walldraw/Walldraw.ino` is the usable project reference, 725 lines. References below use this file unless another source is named.
- `SdCard/02 arduino code/Walldraw/Walldraw.ino` is a 721-line alternative reference. A complete diff found the functional differences to be **350 mm versus 400 mm motor separation** and the OLED welcome text. Other differences are comments/formatting. Both variants implement the same parser and motion routines.
- The Arduino's currently flashed sketch and physical motor spacing remain unknown. Do not select 350 or 400 mm by assumption. Preserve both references until measurement and a known working hardware baseline exist.

SHA-256 fingerprints:

```text
WallDrawingMachine.ino
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Drawbot_C/02 arduino code/Walldraw/Walldraw.ino
aae7083fe130967f87f349e498b1957ffbe63d851a5668dc41b0ec67494eb29c
SdCard/02 arduino code/Walldraw/Walldraw.ino
303dd6154c65ba8042470fd4e51bf139d8a63fb1a9d4ff61bd5f557870e04ace
```

## Existing machine flow

1. `setup()` initializes serial at 115200 baud, buzzer, SSD1306 character display, both stepper drivers and the pen servo (lines 389–417).
2. The servo is immediately commanded to the configured raised position. `teleport(0,0)` sets an **assumed** origin and theoretical cable lengths without moving the machine (lines 217–224, 405–411).
3. The menu offers `DEMO`, `SD`, and `SET` through a resistor-ladder keypad on A1. `DEMO` draws built-in boxes, circles, heart and butterfly curves. `SET` moves to `(0,251)` or `(0,0)`; these are moves, not sensor-based homing (lines 469–587, 689–725).
4. Choosing `SD` calls `SD.begin(4)`, raises the pen, and opens **`main.nc` at the card root** (lines 503–519).
5. `drawfile()` reads characters into an Arduino `String`; every LF (`\n`) calls `nc()` on the accumulated line. An unterminated last line is discarded (lines 349–386).
6. `nc()` optionally changes pen state from Z and moves when it finds both X and Y (lines 310–341). `line_safe()` subdivides Cartesian lines, `IK()` converts each point into two cable lengths, and `moveto()` performs blocking, interleaved motor steps (lines 113–120, 229–306).
7. The completion routine disables both motors and sounds five 300 ms on/off beeps, even if `drawfile()` reported a missing file to the display (lines 454–467, 516–518).

There is no application, host control service, file transfer protocol, job queue, serial command processing, status response, or persistent calibration in this firmware.

## Hardware configuration inferred from source

The code comments refer to UNO wiring (lines 89–90), and the bundled CH340 driver is consistent with a USB-serial clone. Neither establishes the exact physical board or USB bridge. The following assignments are confirmed **source settings**, not a wiring inspection:

- Left stepper/driver inputs IN1–IN4: **D7, D8, D9, D10**, in that order (`setup()`, line 398).
- Right stepper/driver inputs IN1–IN4: **D2, D3, D5, D6**, in that order (line 399).
- Pen servo signal: **A0** (line 406).
- Keypad ADC: **A1**; down/select nominal ADC 330, enter 90, escape 517; each accepted within a strict ±10 window (lines 84–87, 419–452).
- Buzzer: **A2**, active HIGH, completion beep enabled (lines 82–83, 392–393, 454–467).
- SD chip select: **D4**, with board-specific hardware SPI (`SD.begin(4)`, line 506). On an UNO-class ATmega328P this normally means D11/MOSI, D12/MISO, D13/SCK; verify the actual board before assigning these physically.
- OLED: `U8X8_SSD1306_128X64_NONAME_HW_I2C`, no reset pin (line 51). Hardware I²C uses board-defined SDA/SCL; UNO-class wiring is commonly A4/A5. OLED address and actual wiring are not explicitly configured in this sketch.
- Serial: **115200 baud**, with no implemented receive loop (lines 71, 391). On an UNO-style USB-serial board the USB connection exposes UART; it does not expose the SPI SD card as a mass-storage drive.
- Motor system: the chosen library is specifically for **28BYJ-48 motors with ULN2003 driver boards** (`TinyStepper_28BYJ_48/library.properties`, `.cpp` lines 3–15). Confirm motor voltage, supply capacity, common ground and driver connections from the physical machine. Do not power motors from MCU GPIO.

Preserve every pin assignment initially. In particular, D10 is both a motor coil signal and the hardware SS pin on an UNO. The motor code keeps it as an output, which is relevant to SPI master operation. The bundled SD initialization can set hardware SS HIGH in its non-SPI-library branch (`SD/src/utility/Sd2Card.cpp`, lines 273–284); the SPI-library branch delegates initialization to the board core. This warrants a motor/SD interaction bench check with the selected core, **not an automatic pin reassignment**. Servo's AVR implementation uses Timer1 on the usual ATmega328P branch (`Servo/src/avr/ServoTimers.h`, lines 55–57). Normal digital coil writes on D9/D10 are not PWM writes, so Timer1 usage alone does not establish a conflict.

## Calibration and coordinate model

Current source constants (lines 9–45):

- 2048 full steps/revolution.
- Nominal spool diameter 35 mm.
- `TPS = 35 × 3.1416 / 2048 ≈ 0.05369 mm/full step`. This is nominal cable movement per motor step, **not guaranteed Cartesian accuracy**; gearing, spool winding diameter, cable tension, backlash, and position affect the result.
- Motor separation 350 mm in `Drawbot_C`, 400 mm in `SdCard`.
- Left/right anchor X coordinates `−separation/2` and `+separation/2`.
- Both anchors use Y = **250 mm**, relative to the startup origin. `LIMYMAX = −250` is named but never used to validate a motion.
- Servo raised 85°, lowered 70°. Existing values must remain until hardware testing establishes a change.
- Left motor signed directions: reel-in +1, reel-out −1. Right: reel-in −1, reel-out +1. The library's phase order determines actual shaft rotation; verify resulting cable extension/retraction with the actual winding before changing signs based on comments.
- Requested speed 10,000 steps/s and acceleration 100,000 steps/s² per motor (lines 400–403). These are not measured operating limits.

`IK()` computes:

```text
Lleft_steps  = round(sqrt((x + separation/2)^2 + (y - 250)^2) / TPS)
Lright_steps = round(sqrt((x - separation/2)^2 + (y - 250)^2) / TPS)
```

For the physical branch **below the anchors**, the math makes positive Y point upward, toward the anchor line. Some comments describe orientation inconsistently; use the equations and a pen-up test as authority. The preview should use an explicit screen-to-machine Y transformation. No generated path should cross the anchor line: above/below points can have identical cable lengths. The rectangle between the X and Y constants is not a tested work envelope. `(0,251)` in the existing SET menu crosses above the anchor line and must not be copied into a new automatic homing workflow.

For illustration only, the implied origin cable lengths are approximately 305.16 mm (350 mm separation) or 320.16 mm (400 mm separation). A 50 mm spacing disagreement is significant; neither configuration can be approved from filenames alone.

`FK()` is unused and incorrect for these units/branch: it calculates an angle using cable lengths converted to millimetres, then multiplies by step counts and adds a positive Y displacement (lines 94–108). Do not use it for future telemetry without fixing and testing it against `IK()`.

## Actual input dialect, not general CNC G-code

The parser never reads the G/M command number. It looks for the first uppercase X, Y, and Z **anywhere in the line**, including comments. It uppercases the entire string first (lines 310–341).

Behavior:

- `G0` and `G1` are labels only. Both follow the same movement path and speed. `G0` does **not** automatically raise the pen; `G1` does **not** automatically lower it.
- A move requires both X and Y on the **same** line. Omitted axes are not modal. `G1 X10` produces no XY move.
- Expected field order is **X, then Y, then optional Z**. Reordered words are parsed incorrectly because substring boundaries assume that order.
- Coordinates are always treated as absolute millimetre-style values. There is no G20/G21 unit change, G90/G91 mode, offset, scaling, rotation, or homing command implementation.
- Z is a binary pen control, applied **before** XY motion on the same line: `Z > 0` raises; `Z <= 0` lowers. Z-only lines do work. Z is not a linear height axis.
- F is not parsed. Speed controls in an initial application must not imply that changing F affects this machine.
- G2/G3 and I/J/R arcs are not parsed. A G2/G3 line with X and Y becomes a straight endpoint move. The presence of an unused `arc()` function does not mean G-code arcs are supported.
- M3/M5/M17/M18/M84, G4 dwell, G28 homing, checksums, line numbers, and end-of-program codes have no defined opcode behavior. A line containing any of these plus coordinate letters can still trigger XY/Z behavior.
- Comments are not stripped. Example: `; Centre = X139.7 Y177.8` can move the pen. `; Pen up = Z3.0 ...` can change pen state. A statement ignored by a strict parser can be dangerous here.
- Missing or malformed numeric text is passed to `String.toFloat()` and can become zero or a numeric prefix. There is no finite-number check, range check, token validation, maximum line enforcement or error response.
- Only LF triggers execution. CRLF is usually tolerated through whitespace/numeric prefix conversion, but the final line must end in LF. `MAX_BUF=64` is unused and does not constrain the `String` reader.

### Conservative legacy export contract

Until firmware parsing is upgraded, generated `.nc` files should use a **strict subset that the host validates**:

1. ASCII, LF line endings, LF after the final line, fixed decimal numbers, no exponent syntax, no comments or blank metadata lines.
2. Canonical application output uses initial/final `G0 Z5` and movement lines `G0 X<number> Y<number> Z5` for travel or `G1 X<number> Y<number> Z0` for drawing. Z5 is a pen-up sentinel, not a five-millimetre servo height. Separate `G1 Z0` transitions are also understood by the legacy firmware, but application output should follow the single documented contract in [GCODE_CONTRACT.md](GCODE_CONTRACT.md).
3. Always include X, then Y, then Z on movement lines. The parser applies Z before that move, so the move into the first drawing point must use Z5 and the move along the first drawn segment uses Z0. Explicit fields avoid reliance on inherited pen state. Neither G0 nor G1 supplies a pen state itself.
4. Raise at the beginning and end, and between disconnected strokes. Do not add an unconditional return-to-origin move unless the whole return route is valid and the origin is known.
5. Flatten circles, Bézier curves and arcs to polylines on the host. Choose a documented geometric error tolerance instead of pretending G2/G3 work.
6. Fit/translate the entire job, including travel segments, into an explicitly configured and later hardware-verified working area. Reject nonfinite, oversized, too-complex, or uncalibrated execution requests. Preview-only work may proceed with a visibly unverified profile.
7. Enforce a host-side line-length cap suitable for the planned fixed-buffer parser (for example ≤63 ASCII bytes excluding LF); do not claim this limit is currently enforced by the firmware.
8. Save generated jobs under unique names locally, but stage the selected one as **`SdCard/main.nc`** and copy only that selected artifact to the physical card root for legacy execution.

Example shape of a compatible export (an illustration, not permission to run these coordinates on unverified hardware):

```gcode
G0 Z5
G0 X-5.00 Y0.00 Z5
G1 X5.00 Y0.00 Z0
G0 Z5
```

Existing samples use a broader mixture of conventions; their presence is not proof that each file is safe or compatible. In particular, the 11×14-inch mandala uses a lower-left origin, large positive coordinates, comments containing coordinate letters, and ignored F/unit/mode commands. It needs import, coordinate normalization, flattening/validation as appropriate, and a fresh compatible export before execution.

## Findings and remediation order

### Must resolve before introducing unattended or host-triggered motion

- **No verified firmware/calibration baseline.** Empty root sketch and differing motor spacing prevent selecting an authoritative configuration. Preserve original sources; record the physical board, active firmware, measured spacing, spool diameter, pen origin and winding directions before producing a canonical uploadable sketch.
- **No range/format validation.** `nc()`, `line_safe()` and `moveto()` do not enforce workspace or finite inputs (lines 230–340). Add bounded line reading, exact token parsing, explicit allowed commands and calibrated bounds before advertising safe execution.
- **Comments can execute motion.** `nc()` scans every character (lines 318–340). A header alone may move/lower the pen. Host exports must omit comments initially; firmware should later strip supported comment syntax before parsing and reject malformed input.
- **No responsive stop/pause.** `drawfile()`, `moveto()`, `line_safe()` and blocking library calls prevent `KeyCheck()` or a future serial receiver being serviced during drawing (lines 230–299, 361–377, 499–518; TinyStepper `.cpp`, lines 225–231). A future job state machine needs cooperative motion slices and input service between bounded steps. A host Stop button cannot promise immediate cessation until this is implemented and measured.
- **Startup origin is assumed.** `teleport()` has no sensors or verification (lines 217–224, 410–411). Connecting USB can reset some boards; host connections must treat position as unknown after reset/reconnect until origin is deliberately established.
- **Completion releases both motor coils.** `beep()` calls `disableMotor()` before checking the beep setting (lines 454–459). On a hanging machine this may allow the carriage to drift; gearbox friction/real loads determine the outcome. Bench-test and define a holding policy independently of buzzer preference before enabling remote jobs.
- **Pen raising has no settle wait.** `pen_down()` waits 300 ms; `pen_up()` does not wait at all (lines 139–156). An immediate travel move can begin before the servo physically raises. Add calibrated settle timing for both transitions in the firmware rather than assuming ignored G4 delays solve it.

### Reliability and execution correctness

- **Final unterminated line is lost.** Execute a valid residual line at EOF; handle LF and CRLF explicitly (lines 361–378).
- **Unbounded heap use.** Repeated `String` growth and substring allocation create memory pressure, especially on small AVR boards. Replace with fixed-size, checked buffers and predictable numeric parsing (lines 310–340, 351–375).
- **No observable file/read/job errors.** Opening errors only display `Nofile`; the caller still emits the completion beep, and there is no status interface (lines 379–385, 516–518). Distinguish failed, aborted and completed jobs; report bytes/lines and fail closed on read/parse errors.
- **Single-step blocking motion resets acceleration.** Every cable step calls `moveRelativeInSteps(±1)`, which reinitializes the library's ramp and waits for completion. The configured initial step period at acceleration 100,000 is about 2,236 µs per motor call, before math and GPIO overhead (`TinyStepper_28BYJ_48.cpp`, lines 225–231, 271–330, 340–434). The configured 10,000 steps/s is not an achieved Cartesian feed rate. Coordinate motion and benchmark the actual machine before offering precise duration or speed control.
- **Potential SD/SPI/motor D10 interaction.** Inspect selected Arduino core SPI initialization and bench-test before changing pins, as described above.
- **No keypad debounce/state timing.** ADC polling waits for key release but uses no measured debounce or calibration. The menu blocks while a key is held (lines 419–452, 477).
- **SET top move crosses the anchor line.** `(0,251)` is not a valid homing strategy (line 523). Replace with a calibrated setup/origin flow and constrained jog distances.
- **Dormant arc/FK helpers are defective.** In `arc()`, theta is computed before wrap correction and not recomputed; equal start/end coordinates do not create a full circle; pen state is changed internally regardless of the caller (lines 169–210). Fix only if needed, otherwise remove unused functionality from the canonical firmware. Neither helper is currently dispatched by `nc()`.
- **Misleading dead declarations.** `feed_rate`, `mode_scale`, `MAX_BUF`, `sofar`, `posz`, and `actuatorPos` do not implement their implied features. Remove or implement deliberately to avoid designing host features around unused names.

## Bundled dependencies

Both library folders report the same versions in `library.properties`:

- TinyStepper_28BYJ_48 **1.0.0**, MIT. Drives 28BYJ-48/ULN2003 full-step phases through digital writes. Its cooperative `processMovement()` and `setupStop()` functions exist, but the current sketch uses blocking moves instead.
- Servo **1.1.6**, Arduino Servo implementation. Check board-core/timer behavior before upgrading.
- SD **1.2.4**, Arduino/SparkFun. The sketch uses read access; installed library write support does not constitute a file-transfer endpoint. This bundled implementation is FAT-oriented and uses short-file naming internally; keep `main.nc` as the simple 8.3-compatible entry file. Confirm physical card format and reader mounting separately.
- U8g2 **2.28.10**, BSD-2-Clause. The sketch uses its **U8x8 text API**, not a full-frame graphics buffer.

The bundled Windows installer is not needed to analyze the code. Retain vendored libraries for reproducibility, record licenses, and compile against them first after choosing the exact board/core. Upgrade one library at a time with flash/SRAM measurements and a hardware regression check. A newer library version is not automatically a more compatible baseline.

## Feasible integration progression

1. **Mounted-card export with unchanged hardware:** host generates and validates a job, stages `SdCard/main.nc`, and copies that file to an explicitly selected, mounted physical card with backup/hash verification. The card is then returned to Arduino and the existing SD menu starts it. A directory named `SdCard` is not evidence of a mounted physical card.
2. **USB serial streaming after a firmware phase:** if the machine has a usable USB-UART connection, no new radio hardware is normally required. Add capability/version handshake, line IDs, bounded input, acknowledgement after actual execution, state/error reporting and backpressure. The host must not stream into the currently supplied firmware because it never reads serial.
3. **Serial upload-to-SD after firmware and memory validation:** receive a selected file into a temporary short-named file, verify size/checksum, close and activate it only while idle. Implement separately from streaming. Avoid `FILE_WRITE` append surprises: the bundled SD header defines it with `O_APPEND`, so replacement must be deliberate (`SD/src/SD.h`, line 24).
4. **Wireless later:** an ESP32/ESP8266 bridge or a small host such as a Raspberry Pi can expose a network API, but it still requires a real device protocol and correct electrical interface. Replacing the Arduino would require pin, voltage, library and timing revalidation. Do not make this a prerequisite for the first usable application.

USB streaming bypasses removable-card swapping; it does not synchronize a card installed on the Arduino into the computer filesystem. Do not permit the computer and Arduino to write the same SD storage concurrently through improvised dual connections.

## Verification completed and next gates

Completed in Phase 1: read both complete firmware variants; compared their diff; traced setup, menu, file reader, parser, pen, kinematics and motion; checked used library metadata and relevant motor/SD/Servo internals; recorded empty root and SHA-256 fingerprints. No source firmware changes, build, upload or motor movement were performed.

Compile and hardware verification remain **unperformed**. Arduino CLI is not available in this environment, the board/core/FQBN is unknown, and no connected hardware was tested. Later firmware work must provide:

1. Exact board/core and vendored-library compile with flash/SRAM report.
2. Parser cases for LF/CRLF/EOF, comments, oversize lines, malformed/missing/reordered coordinates, unknown opcodes and numeric overflow.
3. Host-generated export roundtrip and IK/FK numerical cases with both calibration references.
4. Pen-up jog and axis-sign validation, origin reset/reconnect behavior, SD init interaction and confirmed travel bounds.
5. Small physical square/circle with measured dimensions, pen lift/settle, rope tension and coil holding checks.
6. SD read failures/removal, serial reset/dropout, abort behavior and measured stop latency once those features exist.

These are implementation gates, not claims of completed hardware functionality.
