# Picasso canonical firmware

`firmware/WallDrawingMachine/` is the single maintained sketch for the wall drawing machine. It replaces neither reference copy: `Drawbot_C/02 arduino code/Walldraw/Walldraw.ino` (350 mm) and `SdCard/02 arduino code/Walldraw/Walldraw.ino` (400 mm) stay byte-for-byte unchanged, and the root `WallDrawingMachine.ino` remains the original **empty placeholder**. Open this folder, not the repository root, when you build or upload.

Version **0.6.0**, SD dialect `picasso-fw-v1`, serial protocol **1** ([docs/SERIAL_PROTOCOL.md](../docs/SERIAL_PROTOCOL.md)). Nothing in the studio or the scripts uploads firmware. The studio opens a serial port only when the operator connects explicitly, and moves the machine only through an explicitly started, acknowledged USB run. Uploading is an explicit maintenance step, described under **Build and upload** below.

## What stays the same

Same libraries (vendored TinyStepper 1.0.0, Servo 1.1.6, SD 1.2.4, U8g2 2.28.10), the same pin map, the same direction constants, the same TinyStepper speed and acceleration, and the same keypad thresholds. Rope kinematics, sub-millimetre line subdivision and the two-motor step interleave are equivalent to the reference sketch. A host test replays the reference `line_safe()`/`moveto()` loops and checks that the new cooperative planner emits **the identical step sequence** for both 350 and 400 mm geometries.

| Signal | Pin |
| --- | --- |
| Left motor IN1–IN4 | D7, D8, D9, D10 (D10 is also hardware SS) |
| Right motor IN1–IN4 | D2, D3, D5, D6 |
| Pen servo | A0 |
| Keypad ladder | A1 (down 330, enter 90, esc 517, ±10) |
| Buzzer | A2 |
| SD chip select | D4 (hardware SPI) |
| OLED | SSD1306 128×64, hardware I²C |

D10 remains a motor output. The bundled SD library uses the SPI-library branch, whose `SPI.begin()` leaves an already-output SS pin alone. That makes a conflict unlikely, but it still needs a bench check (see the commissioning guide).

## What changed, and why

| Legacy behaviour (firmware audit) | Canonical firmware |
| --- | --- |
| Reset assumes the pen is at `(0,0)` | Origin is **unset** at boot. It becomes valid only through *Setup → Set origin* and a confirmation. Every job also needs a **fresh** confirmation, because any motion consumes it. |
| `SET → Top` moved to `(0,251)`, above the anchor line | Removed. Setup offers per-rope jogs, set origin, a validated *Go to origin*, a pen test, a 20 mm test square and an explicit motor release. |
| `String` line reader, unbounded heap, final line dropped | Fixed 63-byte payload buffer. LF and CRLF are accepted; a bare CR, NUL, non-ASCII byte or overflow fails the job. A final line without LF is executed. |
| First X/Y/Z anywhere in the line, including comments | Strict parser: `;` and `( )` comments are removed first. Words may appear in any order, each at most once. Unknown words or opcodes, malformed numbers, missing Z and lone X or Y are rejected. |
| No bounds | Every segment, including the first travel from `(0,0)`, is checked against the compiled workspace, the anchor branch and the minimum and maximum rope lengths, within a 0.01 mm float tolerance. |
| Errors found mid-drawing | **The whole file is validated before any motion.** The machine shows the move count and CRC-32, then waits for Enter. It re-validates while running and compares the CRC at the end. |
| Blocking `moveto()`; keys ignored while drawing | Cooperative state machines. **Enter pauses** (finishes at most one ≈0.054 mm sub-target, raises and settles the pen, holds the coils). Enter resumes and restores the pen. **Esc stops** (raises the pen and holds the coils). |
| No pen-up settle | Configurable settle time for both directions (300 ms each to start; bench-measure them). |
| `beep()` released both motors | Coils stay energized after every job (`PICASSO_RELEASE_AFTER_JOB 0`). Only *Release motors* de-energizes them, and it invalidates the origin. The buzzer is independent: 5 beeps when completed, 2 when aborted, 1 long beep on failure. |
| Missing file still beeped "done" | Distinct **COMPLETED / ABORTED / FAILED** screens with a reason code, the line number and whether any motion happened. |
| Unused, incorrect `FK()`/`arc()`, built-in DEMO | Removed. The DEMO drew fixed coordinates outside any configured workspace. G2/G3 are not supported. |

## SD dialect `picasso-fw-v1`

```text
G0 [X<n> Y<n>] Z<positive>     travel / raise pen (Z>0 = up)
G1 [X<n> Y<n>] Z<zero-or-neg>  draw / lower pen   (Z<=0 = down)
```

- `G00`/`G01` are accepted synonyms, and letters may be lowercase.
- Numbers are fixed decimal with an optional sign, at most 4 integer and 5 fraction digits, and no exponent.
- Z is mandatory on every command and is applied **before** the XY move, as in the legacy firmware. A G0 must raise and a G1 must lower; for example, `G0 Z0` is rejected.
- Blank and comment-only lines are ignored. Coordinate letters inside comments never act.
- The studio's exports (`GCODE_CONTRACT.md`) are a strict subset. The raw vendor samples are **rejected** (long comment headers, modal pen state, `F`, `G21`/`G90`). Import them in the studio and export a fresh job instead.

## Configuration

Hardware wiring and timing live in `picasso_config.h`. Calibration lives in a **generated** `machine_config.h`, which is git-ignored and never edited by hand. Without it, the sketch stops with an `#error` that explains how to generate it.

```bash
# From a saved measured profile (its id appears in the studio's machine dialog):
python3 scripts/firmware.py config --profile <profile-id>
# Jog/pen/origin-only build from a bundled reference (no workspace, so SD jobs are disabled):
python3 scripts/firmware.py config --reference reference-350
```

The studio's machine dialog can also download the file (*Picasso canonical firmware → Download machine_config.h*). The header carries a 16-hex **configuration ID**: a SHA-256 fingerprint of exactly the compiled values (spacing, anchor height, spool, steps, pen angles, workspace, margin and rope limits). The machine shows it on its *Info* screen and in its boot serial line:

```text
PICASSO FW 0.5.0 DIALECT picasso-fw-v1 CFG 7952f3f4e3fc5016 REGION SET ORIGIN UNSET
```

To verify a profile whose values differ from both reference sketches:

1. Save the profile unverified.
2. Generate the header, then build and upload it.
3. Read the ID on the machine.
4. Enter that ID and your check results in the dialog.

The backend rejects an ID that does not match the saved values. Changing any compiled value later invalidates the ID until you rebuild.

## Build and upload

There is no automatic upload. Use Arduino CLI 1.3.1 with the `arduino:avr@1.8.6` core:

```bash
arduino-cli core install arduino:avr@1.8.6
python3 scripts/firmware.py build --profile <profile-id> --fqbn <your-board-fqbn>
```

The build compiles a temporary copy against the vendored libraries in `Drawbot_C/02 arduino code/Library` and prints flash and SRAM use. `--fqbn` defaults to `arduino:avr:uno`, a **reference** board: compiling for it does not establish the machine's actual board. On Linux the script adds `firmware/shims/`, because TinyStepper 1.0.0 includes `<arduino.h>` with a lowercase `a`. `--fixture` compiles a synthetic workspace for CI checks only and never writes into the sketch folder.

To upload, after confirming the board and port yourself, with the motors' supply off or the gondola supported:

```bash
python3 scripts/firmware.py config --profile <profile-id>
cp -r firmware/shims /tmp/picasso-shims   # build properties split on spaces in paths
arduino-cli compile --upload -p <port> --fqbn <your-board-fqbn> \
  --libraries "Drawbot_C/02 arduino code/Library" \
  --build-property "compiler.cpp.extra_flags=-I/tmp/picasso-shims" firmware/WallDrawingMachine
```

Omit the `extra_flags` property and the copy on Windows and macOS. In the Arduino IDE, install the four vendored libraries and open `firmware/WallDrawingMachine/WallDrawingMachine.ino`. Then follow [the commissioning guide](../docs/FIRMWARE_COMMISSIONING.md) before trusting any drawing.

## Operating the keypad

DOWN moves to the next item, ENTER selects and ESC goes back.

- **SD job**: checks `main.nc` without moving, then shows `N moves OK` and `CRC xxxxxxxx`. Compare the CRC with the studio's prepared job. ENTER starts, but only when the origin was freshly confirmed. While running, ENTER pauses and resumes and ESC stops.
- **Setup**:
  - *Set origin*: confirm that the pen is at the physical origin and the ropes are taut.
  - *Jog ropes*: pen up, ±64 steps on one rope; this invalidates the origin.
  - *Go to origin*: validated pen-up travel; you still confirm the origin afterwards.
  - *Pen test*.
  - *Test square*: 20 mm centred on the origin; needs a fresh origin.
  - *Release motors*: de-energizes the coils and invalidates the origin.
- **Info**: firmware version, configuration ID and whether a workspace is compiled in.

Serial output at 115200 baud mixes informational log lines (`PICASSO ...`) with protocol frames (`@...*CRC`). Protocol v1 lets a host stream a job one acknowledged command at a time after the same validation as SD jobs. The details:

- **Origin.** A host can never set the origin.
- **Starting.** BEGIN requires an idle device, a referenced origin, the current boot ID (an EEPROM counter, new on every reset) and origin revision, and the exact commanded start position.
- **Duplicates.** Repeated sequence numbers are never executed twice.
- **Stopping.** ESC on the keypad always stops. A host job stops by itself (`HOST_LOST`) after 3 s without any frame from the host.
- **Exclusivity.** SD and USB jobs cannot overlap, because BEGIN is refused unless the menus are idle.

## Host tests

```bash
python3 scripts/firmware.py host-test     # core unit tests + simulator smoke run
.venv/bin/python -m pytest tests/test_firmware.py tests/test_firmware_config.py
```

`firmware/host/` builds three programs with `g++ -Wall -Wextra -Werror`:

- `core_tests`: reader, parser, geometry, legacy step-sequence equivalence and CRC.
- `picasso_tool`: parser and geometry cross-checks against the backend.
- `simulator`: the **real sketch** linked with the unmodified TinyStepper library, against simulated time, pins, keypad, servo, SD card, EEPROM, serial port and a 400 kHz I²C display model. `bridge <speed>` mode turns stdin and stdout into the serial port in scaled real time, so the Python host controller can drive the sketch; the studio exposes it as a labelled *Simulated Picasso firmware* port when `PICASSO_SIMULATED_DEVICE=1`.

Simulator results are logic evidence only. They are not motor, servo, SD or timing measurements on the machine.
