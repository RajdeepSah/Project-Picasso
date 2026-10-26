# Phase 5 report: canonical firmware, parser hardening and commissioning

Date: 2026-10-26. Version: **0.5.0**.

**Phase 5 software is complete. The Arduino CLI compile and memory report and physical commissioning are pending.**

During this phase:

- no firmware was uploaded;
- no board, serial port or motor was touched;
- no physical card was written.

All 543 original files, including both reference sketches, the empty root `WallDrawingMachine.ino` and `SdCard/main.nc`, still match the Phase 1 SHA-256 manifest.

## Implemented

Each item below follows the Phase 5 task list in [the roadmap](DEVELOPMENT_PLAN.md).

1. **Canonical sketch.** The sketch lives at `firmware/WallDrawingMachine/WallDrawingMachine.ino`, with `picasso_config.h` for the preserved hardware settings and a portable `picasso_core.{h,cpp}`.
   - Calibration lives in a **generated, git-ignored** `machine_config.h`. Without it, the build stops with an `#error` that explains how to generate it.
   - The root `.ino` remains the documented empty placeholder.
   - The reference sketches are unchanged.
2. **Calibration and pins.**
   - The pin map, direction constants, TinyStepper speed and acceleration, keypad thresholds and vendored library versions are unchanged.
   - Servo angles come from the profile; the defaults are the reference values, 85°/70°.
   - Compile-time `static_assert`s require the workspace to lie below the anchors and to contain `(0,0)`.
3. **Bounded strict parser** (`picasso-fw-v1`).
   - A fixed 63-byte payload buffer. LF and CRLF are accepted, and an unterminated final line is executed. A bare CR, NUL, non-ASCII byte or overflow is rejected.
   - `;` and `( )` comments are stripped before parsing. Words may appear in any order, each exactly once. Z is mandatory, and X and Y must appear together. G0 must raise the pen and G1 must lower it. `G00`/`G01` are accepted as synonyms.
   - Unknown words or opcodes and malformed, exponent or oversized numbers are rejected.
4. **Second-line validation.**
   - Before any motion, the whole file is read and every segment is checked against the compiled workspace, the anchor branch and the minimum and maximum rope lengths (including interior closest approach). The check includes the first travel from `(0,0)`.
   - The machine then shows the move count and CRC-32 and waits for Enter. It re-validates while running and compares the CRC at end of file.
   - The `(0,251)` top move is removed.
   - The origin is invalid at boot. Setting it requires a confirmation, and every job needs a fresh confirmation.
5. **Cooperative state machines.**
   - Keypad: debounced, with fixed-interval sampling.
   - Buzzer, pen settling and SD reading: non-blocking. SD reading handles 32 bytes per pass.
   - Motion: the legacy `line_safe()` and `moveto()` logic is decomposed into a sub-target planner and a step iterator, driven one TinyStepper single-step move at a time with the same ≈2236 µs per-step ramp as before.
   - A host test proves the step sequence is **identical** to the reference algorithm over 400 random segments on both the 350 mm and 400 mm geometries.
   - Pause and stop are honoured at sub-target boundaries (≤ one TPS of travel), during pen settling and between commands.
6. **Pen, coils and outcomes.**
   - Settle times apply in both directions: 300 ms down (legacy) and 300 ms up (new).
   - Coils are held after every job. Only *Release motors* de-energizes them, and it invalidates the origin. The buzzer is now independent of coil release.
   - Completed, aborted and failed results are distinct, with the reason, line number and whether any motion occurred. A card removed mid-job fails with the pen raised.
7. **Removed code.** The unused, defective `FK()`/`arc()` helpers and the out-of-workspace DEMO are gone. G2/G3 are not added.
8. **Commissioning guide.** [FIRMWARE_COMMISSIONING.md](FIRMWARE_COMMISSIONING.md) covers board and wiring, boot and origin state, pen settling, jog signs, origin repeatability, the square and circle dimension checks, holding and thermal checks, an SD error table, pause and stop latency, the D10/SPI check, and profile verification.

### Firmware and profile reconciliation

Phase 4 could not verify measurements that differed from both bundled sketches. Phase 5 resolves that:

- **Firmware kind on profiles.** `CalibrationInput` now records `firmware` (`legacy-reference` or `picasso-canonical`) and `firmware_config_id`.
- **Configuration ID.** `backend/app/firmware.py` renders `machine_config.h` and a 16-hex **configuration ID**: a SHA-256 over exactly the compiled values. Attestations and notes are excluded, so verifying a profile does not change its ID.
- **Where the ID appears.** The machine shows the ID on its Info screen and in its boot serial line.
- **Verification rules.** Verifying a canonical profile requires the ID, and the backend refuses an ID that does not match the saved values. Editing any compiled value invalidates the ID. Verifying a legacy profile still requires exact equality with the reference values.
- **API.**
  - `GET /api/profiles` returns firmware IDs.
  - `GET /api/profiles/{id}/firmware-config` downloads the header.
  - The new `firmware` capability reports what is available.
  - `PreparedJob.gcode_crc32` is the value the firmware shows. The job dialog presents it as a *machine check*.
- **Studio.** The machine dialog has a firmware selector, the saved configuration ID, a download link and an ID field. The reference inspector shows each reference's jog-only configuration ID.

### Tooling

`scripts/firmware.py` provides three commands:

- `config --profile | --reference` writes `machine_config.h`.
- `host-test` builds and runs the core tests and a simulator smoke test.
- `build` compiles a temporary copy with `arduino-cli` against the vendored libraries and prints memory use.
  - `--fqbn` defaults to the UNO **reference**.
  - `--fixture` compiles a synthetic workspace for CI only and cannot write into the sketch folder.

There is no upload command; uploading is a documented manual step. `firmware/shims/arduino.h` lets the unmodified TinyStepper 1.0.0 (`#include <arduino.h>`) compile on case-sensitive Linux. CI gains a `firmware` job that installs Arduino CLI 1.3.1 and `arduino:avr@1.8.6` and compiles the 350 mm reference, the 400 mm reference and the synthetic-workspace configurations.

## Validation

Completed on Linux with Python 3.14.4, Node 22.22.1, npm 9.2.0 and g++ 15.2.0.

### Python and C++

- **128 Python tests pass.** These are the 99 existing tests plus 24 firmware and 5 configuration tests. One upstream Starlette/httpx deprecation warning remains.
- **117 C++ core checks pass** (`g++ -std=gnu++11 -Wall -Wextra -Werror`). They cover:
  - the reader: LF, CRLF, EOF residual, bare CR, NUL/non-ASCII, the exact 63-byte limit and overflow;
  - 53 parser cases: comments containing X/Y/Z, reordered, missing and duplicate words, pen-mode conflicts, G2/G28/G90/M3/F/N/I/%/checksums, malformed numbers;
  - geometry: tolerance edges, the anchor branch, endpoint rope limits and interior closest approach;
  - legacy step-sequence equivalence;
  - CRC-32.
- **Parser cross-check.** For circle, rectangle, spiral, butterfly and mandala exports, and for the supplied mandala after import, the firmware parser accepts every line with the same opcode, pen state and coordinates (float32, within 2.5×10⁻⁴ mm).
- **Raw vendor samples.** These are rejected before motion:
  - the mandala fails with `LINE_LONG` on its header comment;
  - `circle.nc` fails with `MISSING_Z` on line 2.

  Legacy hazard comments such as `; Centre = X139.7 Y177.8` are ignored.
- **Geometry cross-check** over 306 points and segments:
  - The firmware never rejects a segment the backend accepts.
  - It never accepts one that fails the backend's check by more than 0.02 mm.
  - Its rope lengths in steps equal the backend's, allowing a one-step difference at float32 half-step ties.

### Simulated runs of the real sketch

These runs use the unmodified TinyStepper library and model time, pins, keypad, servo, SD card and a 400 kHz I²C display. They are logic evidence, not measurements.

- **Complete job.** A backend-prepared 40 mm circle completes.
  - The displayed CRC equals the job's `gcode_crc32`.
  - Final rope steps equal the backend IK (±1).
  - Motor counters equal the rope deltas exactly.
  - Coils stay energized.
  - Pen lowerings equal the stroke count, and gaps of at least 300 ms were observed after every pen change.
- **Origin.** Reset leaves the origin unset, and a job is refused without a fresh origin, including after a completed or stopped job.
- **Validation failures.** Unsupported G2, out-of-workspace, oversized-line, missing-Z, comment-only, no-card and no-file cases fail with the correct code and line number and **no steps**.
- **Line endings and comments.** CRLF, comments and an unterminated lowercase final line execute identically to the canonical file.
- **Stop.** Stopping during an 80 mm circle took **25–29 ms** from key press to the last step and to the pen-raise command, at 10 stop points. The pen ends up, coils are held, the position is exactly known and *Go to origin* returns to (0,0).
- **Pause and resume.** These reproduce the uninterrupted step sequence exactly, with one extra raise and lower.
- **Card removal.** A card removed mid-job leads to `SD read error` with the pen raised.
- **Setup actions.** Jogs move exactly ±64 steps and invalidate the origin. Release de-energizes the coils. The 20 mm test square returns to (0,0).
- **Reference builds.** The 350 mm reference build (no workspace) refuses SD jobs.
- **Timing.** The 80 mm circle took 6810 steps over 16.6 s, or 2.44 ms per step including pen settling.

### Frontend, audit and repository

- **5 component tests and 8 Chromium browser journeys pass.** The new journey covers the canonical firmware flow:
  - it saves 362.5 mm / 243 mm measurements unverified;
  - the downloaded header contains them and its ID matches the dialog;
  - a wrong ID is refused and the correct ID verifies;
  - physical preparation then shows the machine-check CRC.
- **Contracts and build.** The contract drift check, typecheck and production build pass.
- **Screenshots.** The Phase 5 screenshots are new files; the Phase 2–4 screenshots are preserved.
- `python3 -B scripts/audit_project.py --verify docs/project-inventory.json` passes, and `git diff --check` passes.

## Not performed and pending

- **Arduino CLI compile and flash/SRAM report.** The toolchain download was not permitted in this development session, so no AVR build has run here. The sketch has only been compiled by host g++ against stubs. The new CI job, or `python3 scripts/firmware.py build`, must produce the first real report.
  - **Unmeasured risk:** an ATmega328P has 2 KB of SRAM. The SD library's 512-byte cache, the Wire and Serial buffers, U8x8 and the sketch's buffers are estimated near 1.5–1.7 KB static, which is tight.
  - If the report shows too little headroom, shrink the built-in program buffer or the serial log first. Do not remove any validation.
- **Physical commissioning** has not been done. This covers:
  - board identification;
  - pen settle times;
  - jog signs and winding;
  - origin repeatability;
  - square and circle dimensions;
  - holding drift and temperature;
  - SD error behaviour on hardware;
  - measured stop latency;
  - the D10/SPI observation.

  [FIRMWARE_COMMISSIONING.md](FIRMWARE_COMMISSIONING.md) defines each step.
- **Phase 4 card check.** The real-card check from Phase 4 is still pending.

## Known limits

- The first step after power-up can pull a motor to its commanded phase, up to about ±2 full steps (≈0.1 mm of rope). The legacy sketch behaves the same way.
- Keypad thresholds and servo angles are reference values until they are checked on the machine.
- The serial output is an informational log only. The firmware ignores serial input.
- The canonical firmware intentionally rejects the vendor samples and the current `SdCard/main.nc`. Import them in the studio and export a fresh job.
- Card changes between validation and start are detected only by re-validation during the run and by the CRC check at end of file. Keep the card in place.

## Handoff to Phase 6

First, commission the machine with the canonical firmware and record a verified profile carrying its configuration ID.

Phase 6 then adds `docs/SERIAL_PROTOCOL.md` and the acknowledged USB transport on top of the existing cooperative loop:

- The executor already exposes safe points, distinct outcomes and a known commanded position.
- The boot serial line already reports the firmware version, dialect and configuration ID.
- These map directly onto the planned handshake, status and stop messages.

Screenshots: [studio](screenshots/phase-5-studio.png), [mobile](screenshots/phase-5-mobile.png), [test export](screenshots/phase-5-test-export.png), [canonical firmware profile](screenshots/phase-5-firmware-profile.png).
