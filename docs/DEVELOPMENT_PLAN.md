# Project Picasso development plan

Baseline: 2026-10-24. **Phases 1 and 2 are complete. Phases 3–8 are planned and have not been implemented.** This plan is the implementation handoff for Codex. Read the architecture, G-code contract, and relevant audit before changing the associated subsystem.

## Outcome and sequencing

The target is a real local drawing studio: launch once, type a drawing command, inspect and adjust the resulting paths, then prepare and transfer an immutable drawing job. The first usable offline drawing workflow is the Phase 3 milestone. Mounted SD export arrives in Phase 4. USB execution requires Phases 5 and 6. Broader AI interpretation and voice follow a reliable path/export/transport system.

```text
1 analysis [complete]
        |
2 runnable local application [complete]
        |
3 offline drawing engine + preview + G-code
        |
4 history/import + verified SD export
        |
5 firmware hardening + hardware commissioning
        |
6 acknowledged USB execution
        |
7 optional AI interpretation/composition
        |
8 voice + release polish
```

AI work can proceed after Phase 3 if hardware access delays Phase 5, but must use the same validated contracts. Voice can only submit a drawing request, never bypass preparation/start controls. No phase should claim completion for a hardware test that was only simulated.

## Rules for implementing each phase

1. Read this phase's inputs and check current phase reports before coding. Preserve user changes and reference assets. Do not assume the top-level empty sketch is the active firmware.
2. Implement the phase in dependency order, including its real backend behaviors. Avoid controls that report fabricated success or telemetry.
3. Add only the tests needed for the new behavior and risk. Run the listed checks, fix failures, and record exact results and untested limitations.
4. Update README installation/run instructions and `docs/PHASE_<n>_REPORT.md` with completed features, commands, tests, hardware dependencies and next steps. Update the milestone status here.
5. Keep hardware-independent functionality available when a device/card/AI credential is absent. Clearly distinguish draft, prepared, export verified, running, and completed.

The existing SHA-256 baseline can verify preservation during early phases. Phase 4 intentionally changes managed `SdCard/main.nc`; preserve the original first and record that transition instead of pretending the entire original manifest remains unchanged afterward.

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

## Phase 6 — USB protocol and acknowledged machine control

**Goal:** send drawings over an existing suitable USB serial connection with truthful state, progress, pause and stop.

Inputs: hardened cooperative Phase 5 firmware and measured machine profile. No wireless hardware is assumed.

Implement in order:

1. Write `docs/SERIAL_PROTOCOL.md` before coding both endpoints. Specify protocol version, boot/session ID, firmware capabilities, calibration/profile hash, origin/reference revision, commanded XY, framing, bounded lengths, sequence IDs, errors, job boundaries and completion semantics. Keep framing overhead separate from the 63-byte G-code payload limit and size AVR buffers deliberately.
2. Add idle-only handshake/config-reference messages and status available while idle, running or paused. Design firmware and host together; unsupported/old firmware remains unavailable for start. Handshake must not move motors or assume origin.
3. Implement pySerial port selection with explicit connect, timeouts, selected-port ownership, reset/boot handling and handshake. Never flood every serial port with drawing commands during discovery.
4. Stream exactly one motion command at a time initially, acknowledge after motion/pen completion, and retain sequence identity within a boot session to prevent duplicates. Use a dedicated bounded worker/async transport with a priority control queue, so status/pause/stop can be sent while a motion ACK is pending without blocking the API or waiting for the motion lock. A timeout enters fault/unknown and never blindly resends movement. SD mode and USB mode are mutually exclusive.
5. Implement start/pause/resume/stop state transitions. Before start, check the job's expected XY against current commanded position and bind execution to the current boot/session/reference. A mismatch requires reprepare or an explicit validated preposition route, never a hidden travel. Pause finishes a bounded motion slice, raises/settles pen and keeps required holding torque; resume restores pen state only after explicit user action. Stop aborts the job. Recovery after position uncertainty requires re-reference, not automatic continuation.
6. Report acknowledged progress, currently executing line, commanded position estimate, profile/reference state and faults. Do not call it measured carriage feedback; there are no observed encoders.
7. Test full command-to-preview-to-prepare-to-stream workflow and document OS-specific serial permissions/driver troubleshooting. Firmware flashing remains an explicit maintenance operation.

Checks:

- Fake serial device tests: handshake/version mismatch, profile mismatch, reset/new session, ACK loss/delay, duplicate sequence, oversized line, malformed response, disconnect during motion, application crash and stale job request.
- Hold the first motion ACK in a fake device and prove STOP is sent/handled before that ACK, while the status API remains responsive.
- Prove no automatic duplicate execution/reconnect resume, no concurrent SD/USB job, and no start without origin/profile match.
- On actual hardware, stream a small known drawing, verify observed completion and test pause/stop with measured latency. Record which checks require the physical board.

Exit: real USB operation is complete only with hardware evidence. A simulated protocol demonstration is labeled as such. USB-to-SD file upload is optional later work, separate from line streaming.

## Phase 7 — optional AI command interpretation and composition

**Goal:** understand a broader range of drawing requests while keeping geometry and machine validation deterministic.

Inputs: stable Phase 3 contracts; history stores model/provider/version provenance when used. Can be scheduled while hardware checks are pending.

Implement in order:

1. Introduce a provider interface returning schema-constrained DrawingSpec/composition data, never raw executable G-code, Python, shell or arbitrary SVG markup. Keep supported offline commands first and selectable.
2. Select a currently supported provider/model using its official documentation at implementation time; keep credentials in backend environment configuration. Add setup UI indicating provider availability, optional usage/cost information and explicit network mode.
3. Validate every response against bounded generator/composition schemas: allowed primitives, repetition/symmetry, dimensions, seed, point budgets and recursion/depth limits. Reject unsupported content with a clear request for simplification.
4. Implement richer composition from vetted primitives. Do not promise arbitrary illustrations if only primitive composition exists; expand the drawing vocabulary with evaluated generators/templates and describe its actual limits.
5. Add provider timeout/cancellation, rate-limit/offline errors and deterministic fallback suggestions. Regeneration creates a new saved revision with provenance; it never starts hardware or changes a prepared artifact.
6. Add optional follow-up adjustment commands such as “make it smaller” that resolve against the selected drawing revision and preserve explicit size/placement controls.

Checks:

- Use mocked provider responses to test malformed schemas, unsupported generators, excessive complexity, malicious instruction fields, outages and cancellations.
- Confirm no credentials enter frontend bundles/logs and no provider output bypasses geometry validation.
- Evaluate a documented prompt set: circle, butterfly, mandala, dense geometric pattern, unsupported object, oversized request and contextual size change. Record actual provider checks separately from mocks.

Exit: richer commands produce validated drawings through the same preview/export pipeline, and offline supported drawings continue to work without credentials.

## Phase 8 — voice input, usability, and release preparation

**Goal:** optional voice-to-command input and a documented, maintainable release.

Inputs: stable command pipeline. Review current browser speech capabilities before selecting the implementation.

Implement in order:

1. Implement a speech adapter with permission handling, listening/cancel state and visible transcript. Use a supported browser API only with feature detection and documented privacy/availability behavior; offer manual input always. A local speech model can be an optional later installation rather than a hidden large download.
2. Put recognized words into the drawing composer for inspection/submission. Voice never directly starts motion, resumes a faulted machine or changes hardware calibration.
3. Refine responsive layout, keyboard/accessibility, reduced motion, large-preview performance and meaningful error recovery. Add helpful preset/history workflows only after core interactions are tested.
4. Provide a clean installation guide, supported OS/runtime versions, first-run guide, hardware commissioning/troubleshooting guide, data backup/export procedure and dependency/license notices. Keep secrets and vendor Windows binaries out of runtime packages.
5. Verify the single-command built-app launcher, clean shutdown, startup recovery and offline operation. Optionally evaluate desktop packaging after the local browser application is reliable.

Checks:

- Speech adapter tests for unavailable API, denied permission, cancellation, recognition errors and transcript submission; real microphone tests on supported browser/OS pairs.
- Browser end-to-end suite for supported command → adjustment → save → prepare → SD/serial transport, with real hardware tests distinguished from test adapters.
- Fresh setup/relaunch on supported systems, history migration/backup recovery, accessibility checks and final hardware regression checklist.

Exit: documented release with clear capability status. Any missing physical, provider or microphone test remains listed rather than hidden behind a “fully complete” claim.

## Hardware information needed before commissioning

This does not block Phase 2 or offline drawing work. Collect it when the physical machine is available:

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
3. Preview dimensions, pen/travel paths and the exact exported machine instructions agree.
4. The selected immutable job reaches a mounted card with readback verification, or streams over a verified USB protocol.
5. Hardware start requires known profile/origin/state; progress and completion reflect the available transport evidence.
6. Physical calibration, drawing output and stop behavior are measured and recorded.
7. Optional AI and voice add input capability without becoming prerequisites for ordinary drawing.
