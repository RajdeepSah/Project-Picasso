# Project Picasso architecture

Status: accepted architecture based on the Phase 1 source audit of 2026-10-24. Phases 2–4 implement the local studio, offline engine, durable history/import, operator-recorded profiles, immutable preparation and verified managed SD export. Real-card commissioning remains pending. Serial control, firmware changes, AI and voice are future work. See [PHASE_4_REPORT.md](PHASE_4_REPORT.md).

## Product behavior

The primary interaction is a drawing command followed by a drawing artifact, not a conversational message thread. The workflow is **describe → generate → inspect → adjust → prepare → export or execute**. Regeneration creates a new revision so a prepared job can never silently change beneath an execution request.

A supported offline command such as “Draw a mandala with 12 petals, 120 mm wide” should quickly produce deterministic vector paths. A later optional AI adapter expands language understanding and supported compositions. Arbitrary text-to-art is not promised by the deterministic command recognizer.

## Technology decisions

- **React and TypeScript with Vite:** interactive command input, drawing controls, responsive dashboard, and typed API responses. Use native SVG for the first preview; add canvas rendering only if profiling demonstrates a need for large paths. No 3D or server-rendered framework is necessary.
- **Python with FastAPI and Pydantic:** validate drawing specifications, generate geometry, normalize files, enforce machine constraints, serve APIs, and eventually serve the compiled frontend from one loopback origin. Python's standard `math`, `sqlite3`, `hashlib`, and filesystem modules cover the first engine and persistence needs.
- **pySerial:** a local backend owns one selected port, rather than depending on a browser-specific serial API. Timeouts and exclusive ownership are part of the transport design. See the [pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).
- **SQLite plus ordinary files:** transactional drawing metadata/history with inspectable JSON, SVG, and `.nc` artifacts on disk. No cloud database, container runtime, broker, or account is needed.
- **Tests:** pytest for backend geometry, API, filesystem, and protocol behavior; a small number of Vitest component tests; Playwright for the actual command-to-preview-to-export journey. Arduino CLI compile checks and host-side parser tests are added with firmware work.

Use Python 3.12+ and Node 22.12+; the installed Python 3.14.4/Node 22.22.1 combination passes current checks and dependency versions are locked. Avoid silently installing the old bundled Windows executables. The [Vite guide](https://vite.dev/guide/) describes its Node requirements; [FastAPI static files](https://fastapi.tiangolo.com/tutorial/static-files/) support serving built assets without a separate production frontend server. pySerial remains a planned Phase 6 dependency; current storage uses the Python standard library.

## Component boundaries

```text
Browser command + controls
          |
          v
Local FastAPI service (127.0.0.1)
          |
          +--> Command resolver --> validated DrawingSpec
          |           ^                    |
          |       optional AI              v
          |                         deterministic geometry
          |                                |
          |                         transformed polylines
          |                                |
          |                    machine/profile/path validator
          |                                |
          |                       restricted G-code exporter
          |                                |
          |                    reparse exported bytes for preview
          |                                |
          +--> SQLite + immutable job files + SHA-256
          |
          +--> SD adapter --> selected host-mounted card --> main.nc
          |
          +--> serial adapter --> hardened firmware --> motors + pen
```

Generation, preview, storage, transfer, and execution are separate services. The SD adapter and serial adapter accept validated immutable artifacts, never unchecked prompt text. Generation never starts motion.

## Planned repository layout

```text
README.md
docs/                           # Phase 1 evidence, contracts, roadmap, reports
scripts/
  audit_project.py              # Exists now
  setup.py                     # Implemented: install locked dependencies/build
  picasso.py                   # Implemented: launch app, browser, clean shutdown
frontend/
  src/components/              # command, preview, inspector, history, status
  src/api/                     # generated/shared API types and API client
  src/styles/                  # design tokens and responsive layouts
backend/
  app/main.py                  # HTTP API, static frontend serving, lifespan
  app/models/                  # specs, polylines, profiles, job/status models
  app/services/                # generation, transforms, validation, history
  app/gcode/                   # dialect emitter, parser, round-trip preview
  app/transports/              # SD mount export, serial session/state machine
  app/providers/               # optional AI adapter, server-side credentials
config/
  machine-profiles/            # reference candidates; no verified preset yet
firmware/
  WallDrawingMachine/
    WallDrawingMachine.ino     # Phase 5: canonical matching sketch folder/name
    machine_config.h          # immutable pins, explicitly selected calibration
tests/                         # unit, integration, fixtures, hardware procedures
data/                          # ignored local DB, jobs, preferences, logs
Drawbot_C/                     # preserved vendor reference, not active app code
SdCard/                        # preserved current contents, later managed main.nc
WallDrawingMachine.ino         # preserved empty placeholder until Phase 5 migration
```

Do not delete or rename original trees in early phases. Use `SdCard/` as the configured spelling everywhere. Once Phase 4 implements preparation, preserve its existing `main.nc` in a dated backup before replacing it with an explicitly prepared job. New generated history belongs under `data/`, not scattered through the reference library. Hardware-specific migration is documented before choosing the active firmware.

Arduino requires the primary sketch filename to match its sketch directory; this motivates `firmware/WallDrawingMachine/WallDrawingMachine.ino`. See the [Arduino sketch specification](https://docs.arduino.cc/arduino-cli/sketch-specification/).

## Drawing data contract

Use versioned JSON contracts with explicit millimetres. Generate frontend TypeScript types from the backend schema, and fail CI when generated types drift.

**DrawingSpec v1** contains a generator name (`circle`, `rectangle`, `spiral`, `butterfly`, `mandala`, `pattern`), parameters, requested dimensions, seed, detail setting, and generator version. Accept only recognized parameters with finite, bounded values. Unknown commands get a useful clarification in the drawing workflow and never a fabricated result.

**PolylineDrawing v1** contains ordered strokes of finite `[x_mm, y_mm]` points in a centered Cartesian drawing space, bounds, source spec, transform, and optional closed-stroke flags. It contains geometry, not executable text. Flatten curves to line segments with an explicit chord-error tolerance and configurable total point/byte limits. Remove consecutive duplicate points and preserve pen transitions. Imported SVGs must be stripped of scripts, external references, and unsupported constructs before normalization; initial import can reject unsupported SVG rather than pretending to handle it.

**MachineProfile v1** contains:

- Profile ID, revision/hash, board identity when confirmed, protocol/dialect, and verification status.
- Motor anchor separation, anchor height relative to manual origin, spool diameter, steps per turn, and motor direction constants.
- Allowed Cartesian region and rope-length/tension constraints, margins around anchors and boundaries, and maximum segment/line/job sizes.
- Pen up/down encoding, physical servo angles, settle timing, and speed capabilities.
- Evidence/measurement notes and calibration confirmation. `verified=false` until measured; `allowed_region=null` until established. Do not infer a verified workspace from firmware macros.

Provide 350 mm and 400 mm *reference candidates*, not a silently chosen machine preset. A simulation profile may use a provisional canvas with “Simulation — machine profile unverified” visible. Preparation for physical execution requires a verified matching profile.

**PreparedJob v1** freezes ID/revision, DrawingSpec, original and transformed path geometry, profile hash, expected starting XY position, reference requirements, exporter version, exact G-code bytes and SHA-256, reparsed execution preview, metrics, validation result, and creation time. Saving a draft is allowed without hardware calibration; preparing or sending for hardware is gated. Changing scale, rotation, placement, detail, pen settings, firmware dialect, machine calibration, or expected start invalidates preparation and requires a new job revision. An ExecutionRun binds this artifact to a current boot/session and origin-reference revision after checking its starting-position precondition.

**TransferRecord** records job ID/hash, destination identity, previous-file backup, bytes/checksum read back, transport type, result, and timestamp. A copied file is “Export verified”, never “Drawing complete”.

## Coordinates and preview

Firmware inverse kinematics uses anchors at `(-separation/2, 250)` and `(separation/2, 250)` for the bundled configurations, with origin presumed at `(0,0)`. This is a rope machine, so a rectangle inside nominal X limits alone does not establish safe travel. `LIMYMIN` and `LIMYMAX` names are misleading and are not enforced by the source. See the firmware audit.

Keep drawing geometry centered and Y-up. For SVG only, map `(x,y)` to `(x,-y)` through the view transform; never feed screen coordinates back into the machine. Apply fit, scale, rotation, and translation once on the backend, then round to the exporter precision and validate the rounded path again. Validate every travel move, drawing point, and segment against the approved region and rope constraints. Unsafe proposals should fail with an actionable explanation; never silently clip them.

Use the actual exported G-code, parsed through the same restricted dialect contract and initialized at the job's declared starting position, as the final execution preview. Include the first pen-up travel from that position. Show drawing and travel paths distinctly, paper dimensions, actual bounds, origin, machine envelope when known, stroke count, pen lifts, and total path length. A draft uses a visibly provisional simulation start. Preview playback is a simulation. Legacy F words do not control speed; do not present a working speed slider or exact duration for that firmware. An estimate must be labeled and based on measured calibration if offered.

## API sketch

Paths below are planned contracts; add endpoints only in their assigned phase.

- `GET /api/health`: application version, service readiness, implemented capabilities.
- `GET /api/capabilities`: generator, export, microphone, SD, and serial availability with reasons.
- `GET /api/status`: implemented Phase 2 read-only combined machine/storage status; both explicitly uninspected/unavailable. No hardware connection occurs.
- `POST /api/drawings/generate`: prompt/spec/seed → validated draft + preview/metrics; no hardware access.
- `POST /api/drawings/{id}/revisions`: edits/regeneration → a new revision.
- `GET /api/drawings`, `GET /api/drawings/{id}`: paginated local history and revision details.
- `GET /api/profiles`, `PUT /api/profiles/{id}`: measured configuration with revision checking.
- `POST /api/jobs/prepare`: drawing revision + profile revision → immutable artifact or structured validation errors.
- `GET /api/jobs/{id}/export`: download exact prepared bytes; generation alone cannot write a physical card.
- `GET /api/storage/targets`: discovered mount candidates, availability, read/write state, filesystem and removable evidence where available.
- `POST /api/storage/select`: select and authorize one target identity/root for managed writes.
- `POST /api/jobs/{id}/sd-export`: frozen artifact + target identity → verified transfer result.
- `GET /api/machine/ports`, `POST /api/machine/connect`, `POST /api/machine/disconnect`: explicit selected-port session.
- `GET /api/machine/status`: connection, origin/profile validity, capabilities, session and job state.
- `POST /api/jobs/{id}/start`, `POST /api/machine/pause`, `POST /api/machine/resume`, `POST /api/machine/stop`: supported only after protocol handshake.
- `GET /api/events`: server-sent events for generation, transfer, and observed machine state; bounded polling is an acceptable first implementation if state semantics remain identical.

Use stable error codes (`PROFILE_UNVERIFIED`, `PATH_OUT_OF_BOUNDS`, `UNSUPPORTED_COMMAND`, `TARGET_REMOVED`, `PROTOCOL_MISMATCH`, `ORIGIN_UNKNOWN`) and human-readable explanations. Hardware endpoints have no operational stubs that report success. Before implementation they are absent or explicitly unavailable.

The implemented engine lives in `backend/app/drawing/`: command resolver, analytic-circle/cubic geometry, strict dialect codec, declared linear importer and draft service. `models.py` supplies shared contracts. `backend/app/storage/` separates SQLite/artifact recovery, measured-profile/preparation validation, mount discovery, and managed publication/automatic export.

Phase 4 stores immutable draft JSON, exact G-code and SVG in `data/artifacts/<id>/`, with SQLite schema version 1 metadata, hash manifests and compressed exact recovery copies. Save stages files before publishing/committing; startup quarantines uncommitted directories and marks unfinished transfers interrupted. Artifact reads verify every file even when a draft is cached. The 16-draft/32 MB cache and eight browser shortcuts do not evict persistent history. History is searchable and paginated; profiles preserve prior revisions and prepared jobs freeze their calibration snapshot.

Implemented API extensions include `/api/drawings/import`, history/thumbnail/repair, measured-profile save/select, `/api/jobs/prepare`, job retrieval, `/api/jobs/{id}/stage`, `/api/jobs/{id}/sd-export`, and storage targets/test-target/select/auto-sync/transfers. Draft downloads remain `/api/drawings/{revision_id}/export?format=json|svg|gcode`. There is no separate prepared-download or machine endpoint yet. Polling supplies automatic-export updates; no SSE transport is implemented.

Every mutation requires a random per-launch token from `/api/session`; the UI refreshes an expired token once and retries only the denied request, never a potentially completed transfer. Export/configuration operations share an in-process guard and POSIX file lock. Linux discovery requires a mounted removable/USB FAT filesystem with UUID; it never mounts/formats a drive. A separately labeled test target is always restricted to `data/test-card`. Publication anchors writes to a directory descriptor, verifies volume identity and reviewed hashes, backs up old `main.nc`, stages short FAT-compatible names, flushes/checksums, replaces only managed filenames and reads back final bytes. Automatic sync binds one frozen job and selected target; changed files/profile or IO failures pause for review. Details and actual limits are in [STORAGE_AND_COMMISSIONING.md](STORAGE_AND_COMMISSIONING.md).

## Machine state and execution

Track application availability, SD availability, and machine connectivity independently. “No hardware detected” is a valid state with generation and preview still usable.

Planned serial states are `disconnected → connecting → idle_unreferenced → ready → running → paused → completed`, with `fault` and `stopping/aborted` branches. A board reset creates a new session and invalidates origin and previous sequence state. Opening a serial port may toggle DTR/RTS; accommodate reset and handshake explicitly, as described in the [pySerial documentation](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).

The machine has no observed limit switches or absolute encoders in the code. Manual origin placement and tension confirmation are required. Firmware position is a commanded estimate, not measured physical feedback. Motion or disconnection faults invalidate it; never resume automatically after a reset, lost acknowledgement, or reconnect.

Start requires a verified profile matching the board-reported calibration, a current origin reference, valid immutable job, matching expected starting XY, and exclusive transport ownership. A valid origin reference does not imply the carriage is currently at origin: the previous job may have ended elsewhere. Check actual commanded XY against the prepared start and bind the run to the current boot/session and reference revision. On mismatch, reprepare with the new start or offer an explicit fully validated pen-up preposition procedure; never insert an unpreviewed move. For legacy SD operation without telemetry, the operator must establish the declared origin start and matching firmware coordinate state before every job. No generation, reconnect, page refresh, card insertion, or application startup should start a drawing. User intent to start is a separate visible control in the application.

The versioned USB protocol must support bounded lines, session identity, command sequence IDs, capabilities, profile hash, clear errors, and acknowledgements after command completion. Allow exactly one outstanding motion line initially. Process status/pause/stop cooperatively inside motion and pen settling. The backend uses a dedicated bounded serial worker or async transport so an HTTP request/event loop never blocks awaiting movement. Its priority control queue must service status/pause/stop while a motion ACK is pending; do not hold a transport lock across the entire ACK wait. Handshake and configuration changes are idle-only, while status remains available during motion. On a lost ACK, enter an unknown/fault state rather than blindly repeating a potentially executed move. Full protocol specification and measured stop responsiveness are Phase 6 deliverables.

## SD behavior

The first physical transport is managed, one-way export to an explicitly selected mounted card, with optional refresh of local `SdCard/main.nc` from the same immutable job. Preserve existing contents and back up a replaced `main.nc`. Synchronization applies only to app-managed artifacts, not all the libraries, executables, or system files in `SdCard/`.

On a desktop-mounted card, write a temporary file, flush/fsync, close, verify bytes/hash, then replace the destination and verify `main.nc` again. Detect removal, permission errors, free-space failure, read-only targets, and mount identity changes. Temp-write/rename reduces partial-file exposure but cannot promise power-loss atomicity on all removable filesystems. Never report success before readback. Never write while the Arduino owns/reads the same SPI card.

There is no mass-storage interface in the current firmware. USB line streaming can eliminate card shuffling after the firmware changes. Upload-to-SD over USB is a separate optional capability with its own bounded receiver and integrity protocol; do not imply streaming automatically writes the card. Wireless bridges require additional hardware/firmware and are optional, not prerequisites.

## Local service and data handling

Bind to `127.0.0.1`; serve built UI and API from one origin. During development allow only the actual frontend origin through the proxy/CORS configuration. Reject unexpected Host/Origin on state-changing requests and use a per-launch token for file/serial writes. Map opaque IDs to server-owned paths, reject traversal and symlink escapes, and restrict writes to `data/`, app-managed local SD exports, or the selected mounted root. Do not expose an arbitrary file-write API.

API credentials live only in the backend environment; never in browser bundles, committed files, or prompt logs. AI receives prompt and drawing constraints, not local files, unless a later explicit import feature requires it. Use bounded jobs, cancellation, provider timeouts, and sanitized errors. The deterministic geometry/validation/exporter remains the authority over all AI output.

## Interface design direction

Use a studio workspace: warm neutral background, clear dark typography, restrained indigo accent, generous preview area, and compact operational controls. Do not create a chatbot transcript.

- Left: searchable drawing history with thumbnails and revision labels, empty state only when there are no real drawings.
- Center: SVG drawing preview with zoom, fit, dimensions, origin/grid and travel toggle, playback and current selection.
- Bottom: prominent rounded command composer, generate action, examples, and microphone icon with an explicit “Voice coming in Phase 8” disabled state.
- Right: drawing inspector (size, placement, detail, symmetry/seed), validation results and preparation/export controls.
- Header: independent app, SD, and machine status; no invented live telemetry.

Use keyboard submission, clear focus, accessible labels, reduced-motion support, and a responsive inspector drawer. Disable controls with specific reasons when unsupported. A compact “Why this is not ready” panel should identify unverified calibration or unavailable transport without blocking creative work.

Useful later additions: reusable drawing presets, compare revisions, seed lock, drawing/travel distance comparison, pen-lift optimization, and a pen-up boundary trace after hardware referencing. Optimization must always regenerate and revalidate the final job.
