# Project Picasso development plan

Baseline: 2026-10-24. Revised: 2026-10-28. **Phases 1–5 and the Phase 6 software are complete. The original Phase 7 (AI) and Phase 8 (voice) features are implemented as optional extras. Real USB drawings currently stop on a USB disconnect that the machine reports as `HOST_LOST`. All remaining work is in the consolidated roadmap below: A stop the disconnect, B commission and calibrate the machine, C release readiness.** This plan is the implementation handoff for Codex. Read the architecture, G-code contract, and relevant audit before changing the associated subsystem.

## Outcome and sequencing

The target is a real local drawing studio: launch once, type, speak or import a drawing, inspect and adjust the resulting paths, then draw it on the machine over USB as an immutable, verified job. The offline workflow, history, import, firmware, USB protocol, voice input and optional AI are built. What remains is making the real machine draw reliably and accurately, and closing the release gaps.

```text
1 analysis                                   [complete]
2 runnable local application                 [complete]
3 offline drawing engine + preview + G-code  [complete]
4 history/import                             [complete]  SD export: software only, removed from the studio
5 canonical firmware                         [complete]  USB-only UNO build fits
6 acknowledged USB execution                 [software complete]  real runs stop on a USB disconnect
7 optional AI line art                       [implemented, optional]
8 voice input                                [implemented, optional]
        |
consolidated roadmap (replaces the open parts of Phases 4-8)
A  stop the USB disconnect behind HOST_LOST  [P0, hardware]
B  commission and calibrate the machine      [P0, hardware, after A]
C  release readiness                         [P1, mostly software, in parallel]
```

Voice and AI only create or fill in a draft; they never prepare, start or resume motion. No phase or step claims completion for a hardware test that was only simulated.

## Rules for implementing each phase

1. Read this phase's inputs and check current phase reports before coding. Preserve user changes and reference assets. Do not assume the top-level empty sketch is the active firmware.
2. Implement the phase in dependency order, including its real backend behaviors. Avoid controls that report fabricated success or telemetry.
3. Add only the tests needed for the new behavior and risk. Run the listed checks, fix failures, and record exact results and untested limitations.
4. Update README installation/run instructions and `docs/PHASE_<n>_REPORT.md` with completed features, commands, tests, hardware dependencies and next steps. Update the milestone status here.
5. Keep hardware-independent functionality available when a device/card/AI credential is absent. Clearly distinguish draft, prepared, export verified, running, and completed.

The existing SHA-256 baseline can verify preservation during early phases. A deliberate Phase 4 managed export can change `SdCard/main.nc`; preserve the original first and record that transition instead of claiming the original manifest still matches afterward. Implementation tests use temporary mirrors; all 543 original files remain unchanged at delivery.

## Phase 1 — inventory, machine contract, and roadmap

**Status: complete.**

Inputs: all original project files, both non-empty sketches, bundled libraries, drawings, manuals, tools and archives.

Completed tasks:

1. Inventory and hash the 543 original files; compare duplicate trees and firmware variants.
2. Trace the current on-device drawing workflow, pin map, rope geometry, parser and motor/servo control.
3. Inspect drawing file conventions, old generator behavior, SVG/STL metadata, manuals, and realistic SD/USB options.
4. Document defects, compatibility contract, hardware unknowns, architecture, stack and phased acceptance criteria.
5. Implement a standard-library-only audit command, tests, and preservation verification.

Artifacts: README, architecture, firmware and asset audits, G-code contract, this roadmap, Phase 1 report, `scripts/audit_project.py`, tests, and JSON inventory.

Checks: four audit tests pass; the inventory command completes; baseline verification confirms every original byte is unchanged. No firmware build, upload, physical SD write, or motor motion was performed.

Exit: all later phases can reference an explicit machine contract and identify which assumptions need hardware evidence. Details are in [PHASE_1_REPORT.md](PHASE_1_REPORT.md).

## Phase 2 — runnable application foundation and studio interface

**Status: complete.** Implementation and checks are recorded in [PHASE_2_REPORT.md](PHASE_2_REPORT.md). The tasks below retain the agreed scope as a reference.

**Goal:** one launch command opens a real local dashboard backed by an actual service.

Inputs: README, architecture, Phase 1 reports. No hardware or AI key required.

Implement in order:

1. Create `frontend/` and `backend/` with React/TypeScript/Vite and FastAPI/Pydantic. Pin compatible dependency versions, commit lockfiles, define Python support, and record the installed versions tested. Use a local virtual environment rather than system package writes.
2. Define versioned DrawingSpec, path, profile, capability, status and error schemas; generate frontend types. Store the two reference calibrations explicitly as unverified candidates. Do not assign a physical allowed region yet.
3. Implement `GET /api/health` and `/api/capabilities`, loopback binding, frontend development proxy, and production build serving. Health must reflect real service availability.
4. Build studio layout: history area, large preview region, command composer, inspector, status header. Include microphone icon as disabled with accessible “Voice planned” help. An initial command can report that generation is unavailable until Phase 3; it must not fake a drawing.
5. Show independent offline/machine/SD statuses and clear capability reasons. Add responsive layout, keyboard focus and submission behavior, and an application error boundary.
6. Add `scripts/setup.py`: check Python/Node versions, create `.venv`, install locked dependencies, build UI and report failures. Add `scripts/picasso.py`: start service on loopback, open browser only after health succeeds, handle occupied ports and clean child shutdown. After first setup, `python3 scripts/picasso.py` is the one-command launch.
7. Add ignore rules for local databases, secrets, caches and generated runtime files. Keep vendor trees outside runtime/build packaging. Document development and built-app launch paths separately.

Checks:

- Backend health/capability API tests and frontend typecheck/build pass.
- Launch the built application and make an actual HTTP health request; verify UI loads in a browser when available. Test backend startup failure and port conflict handling.
- Confirm app works with no USB device, card or credentials, and unavailable controls have truthful states.

Exit: a fresh setup and one-command launcher work; dashboard is connected to the local backend. No generated drawing or hardware capability is claimed yet.

Implementation prompt: “Implement Phase 2 exactly from this plan. Deliver a runnable local app and setup/launcher, test it, preserve the original assets, and write the phase report.”

## Phase 3 — offline commands, geometry, adjustments, G-code, and live preview

**Status: complete.** Implementation, checks and limits are recorded in [PHASE_3_REPORT.md](PHASE_3_REPORT.md). The tasks below retain the agreed scope as a reference.

**Goal:** type a supported drawing command and immediately see a usable, editable drawing and its exported path without AI or hardware.

Inputs: Phase 2 schemas/runtime, G-code contract, both audits.

Implement in order:

1. Create independent millimetre geometry generators for circle/ellipse, rectangle, spiral, butterfly and mandala/geometric patterns. Record seed, generator version and bounded detail. Start with plain `math`; avoid importing the defective legacy extension.
2. Add an offline command resolver for supported subjects and parameters: “Draw a circle”, “Draw a butterfly”, “Draw a beautiful mandala”, and a defined vocabulary for symmetry, dimensions and complexity. Document the supported grammar. Unknown/ambiguous requests receive an actionable unsupported/clarification response.
3. Implement transforms for size, aspect ratio, rotation, center placement, seed lock, and regeneration. Create immutable revisions in memory initially. Every transform recomputes bounds and complexity limits.
4. Add path checks: finite values, dimensions, point/segment/byte caps, duplicate points, zero-length strokes, flattening tolerance and timeout/cancellation. A visibly provisional simulation profile permits preview while hardware remains unverified.
5. Implement restricted ASCII LF G-code emitter and strict parser following `GCODE_CONTRACT.md`. Every XY motion has explicit X/Y/Z; comments, modal axes, raw arcs and unsupported commands never enter final exports. Pen state and final LF are mandatory.
6. Round-trip emitted bytes to execution geometry. Render that geometry for the execution preview, with pen-down/travel distinction, dimensions, origin/grid, zoom, fit, and playback. Show path length, bounds, strokes and pen lifts. Playback is labeled simulation.
7. Wire preview/adjust/regenerate/save-draft actions to the backend. A draft download may include JSON/SVG and explicitly unverified G-code; it must not be called ready for machine execution. Physical preparation is disabled until a measured profile is verified. Speed controls stay unavailable for the legacy dialect.

Checks:

- Seeded generators produce deterministic results; circle/rectangle bounds match known dimensions and mandala symmetry is checked numerically.
- Transform tests include Y orientation, rotation, aspect-fit and post-rounding bounds. Reject nonfinite, huge or excessively complex requests.
- Export/parser tests cover pen transitions, explicit axes/order, final LF, line limits, unsupported words, malformed numbers, and exact preview/export path agreement within rounding tolerance.
- Browser journey: circle → size change → mandala → regenerate seed → inspect path → download draft; no API key/device is needed.
- Use a source sample with coordinate letters inside comments as a rejection/normalization regression case; do not execute it.

Exit: the offline creative workflow works in the running app. Physical execution remains unavailable when profile/origin/transport requirements are unmet.

## Phase 4 — durable history, import, preparation, and mounted SD export

**Status: software complete. Physical-card verification is no longer planned: the SD workflow left the studio in `b5f5b2a`, and the UNO firmware build excludes SD (see the consolidated roadmap).** See [PHASE_4_REPORT.md](PHASE_4_REPORT.md) and [STORAGE_AND_COMMISSIONING.md](STORAGE_AND_COMMISSIONING.md).

**Goal:** save/reopen drawings, prepare verified jobs, and automatically copy the selected artifact when an approved physical card is mounted.

Inputs: Phase 3 drawing artifacts, asset audit, approved-profile validation contract. Hardware-free tests must cover all copy behavior.

Implement in order:

1. Add SQLite migrations, paginated drawing history, revisions, thumbnails and immutable job files under `data/`. Use transactional metadata writes, atomic file staging and restart recovery. Save prompts/specs, exporter/generator versions and profile hashes.
2. Implement profile editing and explicit measurement notes/verification. Store both reference candidates, but require operator measurement of the actual machine and approved workspace before hardware preparation. Profile edits invalidate prior preparation; never silently upgrade a prepared job.
3. Add strict G-code import first. Then add a separately specified absolute-mm linear importer for current sample conventions, with comments stripped, modal X/Y resolved, Z mapping documented and unknown semantics rejected. Normalize mandala page coordinates to the selected drawing origin and fit only by an explicit transform. Reject unsupported arcs/relative units until correctly supported. Limit/sanitize SVG import if included; it can follow as a separately documented subtask.
4. Implement preparation: frozen drawing revision + verified profile + expected starting XY/reference requirements → transformed and revalidated paths → final bytes/hash + execution preview + validation report. Validate all travel segments and rope constraints, including the initial travel from the declared start. Legacy SD jobs use a documented origin-start procedure before every job, establishing both physical and firmware coordinates; origin validity alone does not mean current position is zero. Draft saving remains possible without hardware.
5. Add local managed export: back up the original `SdCard/main.nc` before the first replacement. Keep unique artifacts in `data/`; update only the selected managed `main.nc` and a small app-owned manifest in the local SD mirror.
6. Discover mount candidates on the supported host OS. Select an explicit target identity and verify that it remains the same filesystem/root before writes. Clearly distinguish a removable card from a user-selected test directory. Do not silently select a drive based on its label/path alone.
7. Implement one-way selected-job synchronization: stage on destination → flush/close → checksum verify → back up previous `main.nc` → activate → final readback. Handle absence, removal, read-only media, disk full, hash mismatch, symlinks, collisions, external edits and retry. No recursive mirror or unrelated file deletion. Auto-sync on insertion is opt-in for the selected prepared artifact, with no auto-start of drawing.
8. Show `prepared locally`, `card unavailable`, `copying`, `export verified`, and `failed` states separately. Explain that stock firmware still needs card insertion into Arduino and the SD menu start. Provide safe-eject guidance without pretending a file close alone guarantees OS ejection.

Checks:

- Restart app and reopen history/revisions with matching bytes/hash; test interrupted save and corrupt/missing artifact recovery.
- Import known sample variants, normalize the mandala, and compare intended bounds/pen state. Unknown commands fail rather than being silently dropped.
- Use temporary directories and a fake mount adapter to test card replacement/removal, permission/disk-full failures, checksum mismatch, original backup and unrelated-file preservation. Simulate failures directly rather than relying on chmod behavior under privileged test users.
- Confirm profile changes reject stale preparation and that unverified profiles cannot trigger a physical export/start.
- Test two consecutive jobs ending at different positions: include/validate the second job's actual starting travel or require its declared start procedure; do not assume the previous job returned to origin.
- When a real card is available, verify only a prepared small test file is copied/read back. Record actual card identity/filesystem. Physical drawing remains a separate commissioning check.

Exit: complete offline-to-card workflow is real and tested in software. If hardware is absent, mark the real-card check pending and describe the working simulated filesystem tests accurately.

## Phase 5 — canonical firmware, parser hardening, and machine commissioning

**Status: software complete. The compile and memory report exists (USB-only UNO build, 87% flash and 64% SRAM; CI compiles it). Physical commissioning moved to Step B of the consolidated roadmap.** See [PHASE_5_REPORT.md](PHASE_5_REPORT.md), [firmware/README.md](../firmware/README.md) and [FIRMWARE_COMMISSIONING.md](FIRMWARE_COMMISSIONING.md). The tasks below retain the agreed scope as a reference.

**Goal:** establish a known firmware baseline and reliable local SD execution without changing the existing hardware pin map.

Inputs: firmware audit, exact board/core/FQBN, confirmed 350/400/other spacing, power/wiring inspection, manual origin procedure. Software work can proceed before all measurements, but physical acceptance cannot.

Implement in order:

1. Preserve reference sketches and hashes. Create `firmware/WallDrawingMachine/` with a matching primary sketch name and separate configuration header. Document the empty root placeholder and canonical upload path; avoid maintaining divergent active copies.
2. Record measured calibration and preserve all pin assignments, direction constants and servo angles unless an observed problem requires an explicitly documented adjustment. Compile reference profiles against the selected core and bundled library versions first; report flash/SRAM headroom. UNO-style reference compilation is not evidence of the actual board identity.
3. Replace `String` line accumulation with a fixed bounded reader, explicit LF/CRLF/EOF handling and overflow rejection. Implement precise G0/G1 and Z semantics for the agreed subset; strip supported comments before parsing and reject unknown, malformed, duplicate or missing fields. Support legacy file synonyms such as G00/G01 only when specified and tested.
4. Enforce finite values, calibrated path bounds and geometric branch constraints in firmware as a second check. Remove the `(0,251)` top move and replace it with a constrained setup/jog flow. Keep origin invalid until deliberately referenced; reset cannot create a valid physical origin.
5. Refactor motion, pen settling, file reading and keypad processing into cooperative state machines. Preserve Cartesian path fidelity and validate motor direction, timing and step sequencing. Service stop/pause requests during long moves and pen delays.
6. Add settling in both pen directions and a deliberate coil-holding policy independent of buzzer settings. Distinguish completed, aborted and failed SD jobs. Keep motors energized when required for gondola stability; measure the actual load behavior and thermal limits.
7. Remove unused defective FK/arc helpers unless an implemented feature needs them; if retained, correct and numerically test them. Do not add G2/G3 simply because an old helper exists.
8. Add a commissioning guide: identify board and pins → set physical origin/tension → pen-up sign/jog checks → small square/circle dimensions → pen-up/down settling → SD completion and error cases → measured stop response. Record measurements and approved region in the machine profile.

Checks:

- Arduino CLI build with warnings, exact core/libraries and memory report. Parser unit/host tests include comments containing X/Y/Z, overflow/truncation, CRLF/EOF, reordered/missing/duplicate axes, nonfinite values and unsupported opcodes.
- Numerical rope geometry tests for chosen profile, origin and permitted boundary region.
- Hardware bench checks start with pen raised and small travel. Verify D10/SPI interaction, direction signs, origin reset, pen settling, rope tension/coil holding, SD removal/error behavior and actual stop latency.
- Photograph or measure a small known square/circle as evidence of dimensions/orientation; no claim of accuracy from compile success alone.

Exit: firmware builds and software tests pass. Mark hardware commissioning complete only when the physical checks and profile measurements are recorded; otherwise leave that part pending. No automatic upload occurs on application startup.

## Phases 6–8 — consolidated roadmap

**Status (2026-10-28): Phase 6 software is complete, but real USB drawings stop on a USB disconnect (Step A). The original Phase 7 (AI) and Phase 8 (voice) features are implemented as optional extras and are closed. Physical commissioning (Step B) and release work (Step C) remain.**

This section replaces the original Phase 6, 7 and 8 task lists. Those lists remain in git history (`3309c68`), and the Phase 6 work is reported in [PHASE_6_REPORT.md](PHASE_6_REPORT.md) and [SERIAL_PROTOCOL.md](SERIAL_PROTOCOL.md). The review used the code, the test suites, the CI results, the local run records in `data/picasso.sqlite3` and the Linux kernel log. No source code was changed for it.

Priorities:

- **P0** blocks any real-world drawing.
- **P1** is required before release.
- **P2** is optional; do it only if time allows.

### Evidence snapshot

| Check | Result on 2026-10-28 |
| --- | --- |
| Python tests: backend, firmware host, simulated device, launcher | **216 pass** locally. |
| Frontend | 27 component tests, the typecheck and the contract-drift check pass locally. |
| CI on `main` | **Failing on the last two pushes.** `3309c68` fails a stale browser assertion: the export menu now also lists TXT (`frontend/e2e/studio.spec.ts:69`). `0450613` failed an intermittent `VoiceButton` component test that passed on the next run. The firmware compile job passes. |
| Original-file manifest (`audit_project.py --verify`) | **FAIL.** Only the root `WallDrawingMachine.ino` differs (R1). |
| Real hardware | CH340-based UNO with firmware 0.6.1, USB-only build, and profile *Picasso test01* (configuration ID `15d5c47b142d0344`). On 2026-10-27, two USB runs of a 120 mm circle (116 commands) both stopped at command 20 (Step A). |

### Completed

| Feature | Evidence | Physical status |
| --- | --- | --- |
| One-command setup and launcher; loopback-only service | `test_launcher.py`, `test_runtime_integration.py` | n/a |
| Offline shapes (circle, ellipse, rectangle, spiral, butterfly, mandala, pattern), live adjustments, regeneration, immutable revisions | `test_drawing_engine.py`, `test_draft_api.py`; 92 offline revisions in local history | n/a |
| Preview built from the exported G-code; simulation playback; every job starts at the page centre and returns there pen up | `test_drawing_engine.py`, `timeline.test.ts`, [GCODE_CONTRACT.md](GCODE_CONTRACT.md) | Not yet checked on paper (B5) |
| Durable history, search, thumbnails, integrity repair | `test_phase4_storage.py`, `test_phase4_api.py`; 124 local artifacts | n/a |
| Image import (OpenCV trace at Low, Medium or High detail) and absolute-mm G-code import | `test_image_import.py`, `ImportDialog.test.tsx`; 26 imported revisions in local history | n/a |
| Export as `.nc`, `.txt`, `.svg` or `.png` with descriptive names | `test_draft_api.py`; the browser journey needs updating (C1) | n/a |
| Measured profiles, generated `machine_config.h`, configuration ID check | `test_firmware_config.py`; the real board reported the matching ID | Values not physically verified (R2, B9) |
| Canonical firmware 0.6.1; the USB-only UNO build uses 87% flash and 64% SRAM | 133 C++ core checks; CI compile job | Flashed to the real UNO |
| Serial protocol v1: handshake, one acknowledged command at a time, pause, resume, stop, *Go to origin*, 3 s host watchdog; Execute sheet with its start checks | 18 fake-device controller tests, 9 protocol tests on the simulated sketch, 4 simulated end-to-end runs | Real board: handshake, configuration match, keypad origin, `BEGIN` and 19 acknowledged commands worked. **No real run has completed** (Step A). |
| Voice input: local Faster-Whisper, fills the command box only | `test_voice.py`, `VoiceButton.test.tsx` (one flaky test, C1) | Real microphone checked in Chromium on Linux |
| Optional AI line art: OpenAI image, traced locally by OpenCV; Auto, Offline and AI modes; the key stays in the backend | `test_ai.py` (mocked provider) | Two real provider requests in local history on 2026-10-27 |

### Removed or not needed

Do not reintroduce these.

| Item (original phase) | Decision and reason |
| --- | --- |
| SD-card export in the studio, automatic card sync, real-card readback (4) | Removed from the studio in `b5f5b2a`. The UNO cannot hold the SD code and the protocol together, so the USB-only build compiles SD out, and drawing over USB replaces the card. The API endpoints remain dormant; do not extend them (R4). |
| SD-specific commissioning: guide §5.2 (SD circle), §7 (SD errors), §9 (D10/SPI during card start-up) | Not applicable to the USB-only UNO build. A circle drawn over USB replaces §5.2 (B5). |
| USB-to-SD file upload (6) | Not needed: line-by-line USB streaming is the execution path. |
| A provider that returns a schema-checked DrawingSpec; composition from vetted primitives (7.1, 7.4) | Superseded by the implemented image-and-trace pipeline, which never executes provider output. |
| A documented AI prompt-set evaluation (Phase 7 checks) | Too heavy for an optional feature. A three-prompt smoke test replaces it (C7). |
| Follow-up commands such as "make it smaller" (7.6) | Not implemented. The inspector's size, rotation and placement controls do this with no AI cost. Recommended drop (R6). |
| Browser Web Speech API adapter (8.1) | Replaced by the implemented local Faster-Whisper adapter, which also works offline. |
| Desktop packaging (8.5) | Not needed: the one-command local browser app is the release form. |
| Cross-browser and macOS/Windows verification (Phase 8 checks) | Recommended out of scope: release on Linux with Chromium, the tested pair (R5). |
| Feed/speed control, G2/G3 arcs, automatic reconnect or resume after a fault, measured position feedback | Excluded by design: legacy dialect, safety rules, no encoders. |

### Decisions needed

These are flagged rather than assumed. Record each answer here.

- **R1. Root `WallDrawingMachine.ino`.** The README and firmware audit call it an empty placeholder. Commit `1f8c738` ("Voice input integrated") added 646 lines to it.
  - The contents look like the vendor sketch with translated comments and lost characters, for example `( X_SEPARATION0.5)` and an unterminated `/* reset=/`. It would not compile.
  - It is the only file that fails the original manifest.
  - Was it intentional? Either restore the empty placeholder, or move the file to a reference folder and re-baseline the manifest with a recorded reason.
  - Never flash it. The maintained sketch is `firmware/WallDrawingMachine/`.
- **R2. Profile *Picasso test01* is marked verified,** with all three attestations ticked. Its own notes say motor directions, pen movement, rope tension, workspace limits and drawing accuracy have not been verified. Use it only for supervised bench tests until B9.
- **R3. Power arrangement.** It is not recorded anywhere. Are the two ULN2003 boards and the servo powered from the Arduino's 5 V, which means from USB, or from a separate supply with a common ground? Step A depends on the answer.
- **R4. Dormant SD endpoints.** Recommended: leave the code as it is, with no hardware testing and no studio entry. Removing it would be a separate clean-up.
- **R5. Release platform.** Recommended: Linux with Chromium only, stated in the README.
- **R6. Follow-up adjustment commands.** Recommended: drop.

### Step A — Stop the USB disconnect behind `HOST_LOST` (P0)

**What the evidence shows.** Both real runs on 2026-10-27 (12:32 and 12:34 CDT) stopped at the same point:

- command 20 sent and command 19 acknowledged, about 7.8 s after the start;
- the host message was "The serial connection closed";
- the kernel log records `usb 6-1: USB disconnect` for the CH340 in exactly those seconds, then a new device attaching within the same second.

What this means:

- **The USB-serial chip itself dropped off the bus.** That is an electrical or USB-level event: a dip in the board's 5 V supply, interference, or the cable or port. Nobody unplugged it, because it reattached within a second.
- **`HOST_LOST` is the consequence, not the cause.** Once the computer loses the port it stops sending, and the firmware stops the job after 3 s, as designed.
- **Host timeouts, polling and the watchdog are not involved.** The host polled every 0.5 s right up to the disconnect. Do not lengthen the watchdog or add automatic reconnect: neither fixes a vanishing device, and both weaken safety.
- **The failure repeats at the same command, so it can be tested.** Command 20 is where the right motor first reverses: its rope goes from shortening by 3 steps to lengthening by 1. The left motor reversed at command 3 without a problem, so this is a correlation to test, not a proven cause.
- **Boot IDs went from 6 to 8 between the runs.** That is one more reset than a single reconnect explains, so the disconnect may also have reset the board. Watch for this in A1.

**A1 — Record the power arrangement and reproduce with the kernel log open** · P0 · hardware

- *Purpose:* confirm the failure mode before changing anything.
- *Do:*
  1. Answer R3.
  2. Run `journalctl -kf` in a terminal.
  3. Connect, set the origin and run the same circle again: prepared job `0d8d75df…`, or a fresh 120 mm circle.
  4. With the cable still connected but no run active, run *Setup → Test square* and a few *Jog ropes* moves from the keypad.
- *Done when:* you know whether the disconnect repeats at command 20, and whether keypad-only motion, with no USB traffic, also causes one. If keypad motion alone causes it, the cause is electrical and independent of the app.

**A2 — Isolate the cause, one change at a time** · P0 · hardware

- *Purpose:* find the smallest change that stops the disconnect.
- *Do:* re-run the A1 circle after each change, and stop at the first one that works.
  1. Power the ULN2003 motor boards, and the servo, from a separate 5 V supply rated for at least 2 A. Join its ground to the Arduino's ground. Do not power them from the Arduino's 5 V pin.
  2. Use a short, good-quality USB cable plugged straight into the computer, without a hub. Route it away from the motor wires, and add a ferrite if one is available.
  3. If it still fails at command 20, test the reversal correlation with two short segments that reverse one motor, and with the servo unplugged.
- *Done when:* the change that removes the disconnect is identified and recorded in the commissioning record.

**A3 — Apply the fix and prove stability** · P0 · hardware; firmware only if A2 points there

- *Purpose:* reliable drawing over USB.
- *Do:*
  - Make the A2 change permanent.
  - Add the power requirement to the commissioning guide prerequisites (§0).
  - Change firmware only if A2 shows a firmware cause, and even then keep protocol v1 and the watchdog unchanged.
- *Done when:* these all complete with no `USB disconnect` line in `journalctl -k` and no `HOST_LOST`:
  - three consecutive runs of the 120 mm circle;
  - one drawing that takes at least 10 minutes, such as an imported picture.

**A4 — Keep the cause visible in the app** · P1 · software, small

- *Purpose:* the run record says only "The serial connection closed". The underlying pySerial error is discarded in `_read_loop` in `backend/app/machine/controller.py`. Future failures should be diagnosable without guesswork.
- *Do:* include the transport error text in the run and connection messages. Do not change any behaviour.
- *Done when:* a controller test whose fake transport raises `TransportClosed("device disconnected")` shows that text in the run message, and all existing tests pass.

Optional, P2: ModemManager is active on this computer. It cannot cause a bus-level disconnect, so add a udev rule that makes it ignore the CH340 (`ENV{ID_MM_DEVICE_IGNORE}="1"`) only if A2 finds disconnects that are not electrical.

### Step B — Commission and calibrate the real machine (P0, after Step A)

Follow [FIRMWARE_COMMISSIONING.md](FIRMWARE_COMMISSIONING.md). Every check is a physical observation: record numbers, photos or slow-motion video, not just "OK". The proposed tolerances are starting points; the team confirms them before testing.

**B0 — Update the guide for the USB-only UNO** · P1 · docs

- Replace §5.2's SD circle with a circle drawn with Execute over USB.
- Mark §7 and §9 as applying to USB+SD builds only.
- Add the A3 power requirement to §0.
- *Done when:* the guide no longer asks for an SD job on the UNO.

| Task | Guide | Purpose | Done when |
| --- | --- | --- | --- |
| **B1** Boot and reset on connect | §1, §10.1 | Know when the origin is lost | Boot and reset-on-connect behaviour is recorded. The handshake configuration ID equals the *Info* screen. |
| **B2** Pen servo angles and settling | §2 | Clean lifts, no drag lines | Measured up and down times fit the 300 ms settings, or the settings are raised and the firmware rebuilt. |
| **B3** Rope directions, jog signs, spool | §3 | Correct direction and scale | Each rope moves the expected way. One 64-step jog measures about 3.7 mm with the 38.1 mm spool. |
| **B4** Origin and repeatability | §4 | A trustworthy (0,0) | Three test-square and *Go to origin* cycles bring the pen back within the agreed tolerance of the mark. Proposed: 1 mm or less. |
| **B5** Dimensions, orientation, match with the preview | §5.1, plus the B0 USB circle | Paper matches the preview and the G-code | Test-square sides measure 20 mm and diagonals 28.28 mm, and a 40 mm circle drawn over USB measures 40 mm, within tolerance (proposed ±0.5 mm). +X is right and +Y is up. The shape matches the studio preview. |
| **B6** Holding, drift and heat | §6 | Safe idle between jobs | After a 10-minute hold there is no drift, and motors and drivers are warm, not hot. The `PICASSO_RELEASE_AFTER_JOB` decision is recorded. |
| **B7** Pause and stop latency | §8, §10.3 | A reliable stop | Studio *Stop* and keypad ESC are each measured on video, and the pen clears the paper every time. |
| **B8** USB fault behaviour | §10.4, §10.5 | Faults end safely | Pulling the cable raises the pen and shows `HOST_LOST` within about 3 s. The studio shows the fault and nothing resumes after reconnecting. A USB start is refused while a keypad menu is open. |
| **B9** Re-verify the profile | §11 | The verified flag means something | Profile values are corrected from B3–B5; any change means regenerating the configuration and reflashing. Then the notes are updated with the measurements and the profile is marked verified. This resolves R2. |

### Step C — Release readiness (P1 unless noted)

These are mostly software tasks and can run in parallel with Steps A and B.

**C1 — Make CI green**

- *Purpose:* a trustworthy `main` branch.
- *Do:*
  - Update the export-menu assertion at `frontend/e2e/studio.spec.ts:69` to include TXT.
  - Make the `toHaveValue('Draw a spiral')` wait in `VoiceButton.test.tsx` reliable.
  - Add `--no-voice` to the CI setup step. CI currently downloads the 480 MB speech model on every run, although the tests point voice at an empty model directory.
- *Done when:* two consecutive CI runs on `main` are green.

**C2 — Keep supported shapes offline**

- *Purpose:* in real use, "circle of radius 1 cm" became a billed OpenAI request and came back as a 178 × 183 mm traced drawing instead of a 20 mm circle. The cause is that the grammar accepts only mm. "draw a circle 2 inches wide" and "make it smaller" also go to OpenAI in Auto mode.
- *Do:*
  - Accept `cm` and `in`/`inch(es)` in the offline grammar, converted to mm.
  - In Auto mode, never send a prompt that names an offline shape to the AI; report the parse error instead.
  - Update [OFFLINE_DRAWING_COMMANDS.md](OFFLINE_DRAWING_COMMANDS.md).
- *Done when:* unit tests show "circle of radius 1 cm" becoming a 20 mm offline circle and "circle 2 inches wide" a 50.8 mm one, while a mocked AI transport is never called. The existing AI tests still pass.

**C3 — Resolve the root sketch (after R1)**

- *Done when:* `python3 -B scripts/audit_project.py --verify docs/project-inventory.json` passes, or the manifest has been regenerated with the reason recorded.

**C4 — Documentation pass**

- *Purpose:* the documents describe the app as shipped.
- *Do:* update the README:
  - the status line and "Next phases": Phases 7–8 are done, so point to this roadmap;
  - the export formats: `.nc`, `.txt`, `.svg` and `.png`;
  - the statement about the root sketch (after R1);
  - a short troubleshooting entry for `HOST_LOST` and USB disconnects (power, cable, `journalctl -k`);
  - the supported platform (R5);
  - backup: stop the app, then copy `data/`.
- *Done when:* a teammate can go from the README to setup, a first drawing and Execute without asking questions.

**C5 — Fresh-install check**

- *Purpose:* prove the one-command promise.
- *Do:* in a new clone or a new Linux user, run `python3 scripts/setup.py` and then `python3 scripts/picasso.py`. Draw an offline circle with no `.env` and no device.
- *Done when:* it works, and the time taken is recorded.

**C6 — Final hardware acceptance and report** (after A and B)

- *Purpose:* one honest record of what was proven physically.
- *Do:*
  - On the commissioned machine, over USB, draw an offline mandala, an image imported at Medium detail, a voice-entered command and, if a key is available, one AI drawing. Each must complete.
  - Stop one drawing midway.
  - Write a final report that separates hardware evidence from simulation, with photos.
- *Done when:* the report is written and the release checklist below is complete.

**C7 — Optional** · P2

- A three-prompt AI smoke test with a real key: a supported shape stays offline, an object becomes AI line art, and an invalid key shows its error.
- A keyboard-only pass through generate, adjust and Execute.

### Order

```text
A1 → A2 → A3 → B0–B9 → C6
A4, C1, C2, C3, C4, C5 and C7: software, any time, in parallel with A and B
```

### Release checklist

Project Picasso is ready for real-world use when every item is true and the evidence is recorded.

**Software**

- [ ] CI is green on `main` for two consecutive pushes (C1).
- [ ] Local checks pass: pytest, frontend contracts, typecheck, component tests and browser journeys.
- [ ] The original-file manifest passes, or was re-baselined with a recorded reason (C3).
- [ ] Supported shapes never reach the paid AI path (C2).

**Hardware** (measurements, photos or video for each)

- [ ] The power arrangement is recorded, and the cause of the USB disconnect is found and fixed (A1–A3).
- [ ] Three consecutive 120 mm circles and one drawing of at least 10 minutes complete over USB, with no USB disconnect and no `HOST_LOST`.
- [ ] Commissioning checks B1–B8 are recorded.
- [ ] The profile is re-verified from those measurements, and its notes no longer say calibration is pending (B9).
- [ ] Studio *Stop*, keypad ESC and a cable pull each end a run safely, with the latency measured.

**Usability and documentation**

- [ ] The README and the commissioning guide describe the app as shipped (C4, B0).
- [ ] A fresh Linux install works with one setup command and one launch command (C5).
- [ ] The final report separates hardware evidence from simulation (C6).

## Hardware information needed before commissioning

This does not block Phase 2 or offline drawing work. Collect it when the physical machine is available.

Known as of 2026-10-28: a CH340-based UNO-compatible board (USB ID `1a86:7523`) running canonical firmware 0.6.1, USB-only build. The operator measured 416.56 mm spacing, 304.8 mm anchor height and a 38.1 mm spool; these are not yet physically verified. **Still unknown and needed first: the power arrangement (R3).**

- Board model, processor/USB bridge, exact Arduino core/FQBN and known currently working firmware if available.
- Measured motor-anchor separation and height relative to the manual pen origin; actual spool diameter and winding arrangement.
- Motor/driver type and voltage, external power supply rating and common-ground arrangement.
- Existing pin wiring, servo angles and safe lift/settle times; observed coil holding requirements.
- Reachable paper/work area with margins and tension limits, axis orientation, origin placement and repeatability.
- Card format/capacity, host reader/mount path, and working `main.nc`/menu behavior.
- Whether USB is accessible while motors are powered and whether opening the port resets the board.

Do not fill these values by inference from an installer, drawing filename, STL or source comment. Record measurements and the resulting profile revision.

## Completion criteria for the final product

1. After documented setup, one command opens the working local application.
2. “Draw a beautiful mandala” produces a valid offline preview; supported adjustments and regeneration preserve history.
3. Preview dimensions, pen/travel paths and the exact exported machine instructions agree, in software and on paper (B5).
4. The selected immutable job streams over the verified USB protocol and completes on the real machine. SD-card export is no longer part of the studio.
5. Hardware start requires known profile/origin/state; progress and completion reflect the available transport evidence.
6. Physical calibration, drawing output and stop behavior are measured and recorded.
7. Optional AI and voice add input capability without becoming prerequisites for ordinary drawing. Both are implemented.
