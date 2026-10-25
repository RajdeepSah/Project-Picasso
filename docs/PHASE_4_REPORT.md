# Phase 4 report — durable drawing workflow and managed SD export

Date: 2026-10-24. Version: **0.4.0**. **Phase 4 software is complete; real-card readback and physical commissioning remain pending.** No firmware was uploaded, motor moved or physical card written. All 543 original files, including the empty root sketch and `SdCard/main.nc`, still match the Phase 1 SHA-256 manifest.

## Implemented

The application remains runnable with `python3 scripts/picasso.py`. Existing locked dependencies supply this phase; SQLite, compression, checksums and filesystem publication use the Python standard library. React/TypeScript, FastAPI/Pydantic and the Phase 3 strict G-code format remain in place.

- **Durable drawing history:** SQLite schema version 1 plus immutable draft JSON/G-code/SVG directories. Search, pagination, real thumbnails, saved revision reopening and automatic saving replace session-only storage. File hashes are checked on every read. Staged saves publish before database commit; failed/uncommitted saves are preserved for inspection and never reported as saved.
- **Recovery:** checksummed compressed exact artifact copies in SQLite, history damage indicators and explicit repair, before-repair quarantine, startup orphan recovery and interrupted-transfer records. Newer database schemas are rejected rather than rewritten. There is no automatic history deletion or destructive reset API.
- **Import:** strict Picasso G-code, a declared absolute-mm linear dialect and intact Picasso draft JSON. Modal XY/comment handling, explicit Z sign mapping, known setup/end commands, exact vendor header recognition and unsupported-command rejection are implemented. Original bounds/source hash and normalization notes remain visible; centering/fitting is explicit. Imported paths support geometric adjustments; regeneration/detail/seed are disabled. SVG import is deferred.
- **Measured profiles:** actual board/calibration, approved workspace/margins, rope limits, observer, origin procedure and physical-check attestations can be recorded, edited/versioned and selected. Source references never become verified automatically. Verified calibration must match its bundled firmware reference; differing measurements stay unverified pending Phase 5 firmware reconciliation.
- **Immutable preparation:** frozen code/checksum/preview/profile snapshot, separately labeled physical or simulation jobs, expected `(0,0)` start, mandatory manual origin before each SD job, and explicit false hardware-execution status. Physical preparation validates rounded drawing and travel, initial travel, full segment rope minima, endpoint rope maxima and half-step allowance. Changed/unverified/unselected profiles block export of stale preparations.
- **Managed export:** optional local `SdCard/main.nc` staging; verified previous-file backups before replacement; Linux removable/USB FAT volume discovery with UUID/path/mounted-instance checks; explicit target selection; staged writes/flush/checksum/activation/final readback. Only `main.nc` and `PICASSO.JSN` are managed. Safe-eject guidance and manual SD-menu start remain visible.
- **Hardware-free verification:** an app-owned `data/test-card` target runs the real publication/readback path. Simulation jobs cannot touch physical cards or the local mirror. Test copies are labeled distinctly; saving a measured profile does not disable this workflow.
- **Exact-job automatic export:** opt-in, persisted selection of one immutable job and one approved destination, including immediate availability and reinsertion. Absence waits; external edits, stale profiles and nontransient failures pause for review. It never picks the newest drawing or starts hardware. Selection/configuration/publication share a process guard and POSIX lock to prevent racing an active copy.
- **Local API boundary:** per-launch mutation token, origin/host checks, opaque artifact IDs, bounded regular-file reads, symlink/ancestor rejection and structured storage failures. The UI refreshes expired tokens only after a definite denied request; it does not blindly retry potentially completed writes.

The studio adds saved-history cards, import and measurement dialogs, prepared-job restore, destination review, transfer records, verified-byte/hash feedback and automatic-sync controls. Desktop/mobile screenshots were inspected; original Phase 2/3 screenshots are preserved. [Storage and commissioning](STORAGE_AND_COMMISSIONING.md) documents actual workflows, limitations, backup/restore and card ownership.

## Validation

Completed on Linux with Python 3.14.4, Node 22.22.1 and npm 9.2.0:

- **99 Python tests pass**, covering the original audit, deterministic engine/contracts, API, storage, real built/dev launchers and clean shutdown. A separate-process restart retains the entire exact draft while changing the write token and rejecting its predecessor.
- **5 frontend component tests pass.** Generated JSON/TypeScript contract drift check and TypeScript compilation pass.
- **7 Chromium browser journeys pass:** existing generation/adjustment/regeneration/downloads; unsupported-command retention; mobile layout; reconnect; persistent history plus supplied-mandala import; simulation export/readback/automatic sync; unverified calibration with physical preparation still blocked and simulation preparation still usable.
- `python3 scripts/setup.py --skip-install` regenerates contracts and builds; the final frontend build passes. No fresh dependency download was needed.
- `python3 -B scripts/audit_project.py --verify docs/project-inventory.json` confirms **543 original files unchanged**. `git diff --check` passes.

Import regression checks normalize **15 supplied drawing files** under `SdCard/01 Test GCode`, including the logo `.txt`, modal vendor variants, and the 252 mm mandala explicitly fitted to 120 mm. Tests reject arcs, relative/inch coordinates, offsets, spindle/dwell commands, duplicate axes and unsupported program-end semantics. JSON reimport compares checksums and creates a fresh non-executable draft.

Temporary directories and a fake mounted-volume provider cover physical-export preconditions, verified backups, original-mirror preservation and unrelated-file preservation. Injected read-only, disk-full, permission, staged/final checksum, removal, replaced-root and external-edit failures cannot produce a verified transfer record. Tests also cover artifact/ancestor symlinks, unsafe-card discovery isolation, interrupted saves/transfers, profile invalidation, full-segment rope constraints, explicit origin again for consecutive jobs, lock contention and automatic-sync reinsertion/review behavior. These are **software simulations of failure and volume state**, not actual FAT-card or motion measurements. API/browser suites use temporary data and mirror paths; no synthetic calibration is saved into the user's default data directory.

One upstream Starlette/httpx TestClient deprecation warning remains; it does not fail the tests. Browser checks use an already installed compatible Chromium via `PICASSO_BROWSER_PATH`; normal CI installs its locked Playwright browser.

## Remaining acceptance and limits

The requested reference folders were rechecked. The root sketch is still empty and the two reference sketches specify 350 mm versus 400 mm spacing. No mounted removable card was present. Installed board/firmware, actual spacing, work envelope, rope tension, origin repeatability, pen settling and motor holding cannot be established from these conflicting source copies alone. Physical verification therefore remains pending; the UI collects actual evidence rather than pre-verifying a reference.

A real-card test must record UUID/filesystem/mount and verify a small prepared file before safe eject/manual execution. Stock firmware retains its audited parser/motion/holding defects. A geometrically valid file is not measured proof of drawing accuracy or stop response. The app never reports a run as started/completed and never assumes a preceding SD job ended at origin.

Physical discovery is Linux-only and publication requires POSIX support. No OS eject automation, recursive/bidirectional mirror, arbitrary directory target, SVG import, serial upload/control, AI provider or voice recognition was added. History has no pruning/quota UI yet. Automatic sync persists while enabled, requires the app to run, and should be disabled before external managed-file edits or card-ownership changes. An active copy is not canceled by closing its dialog. Local mirror and card copies are separate journaled operations; either can have changed before a later failure. Final readback failure never claims verified success, even if activation already occurred. Power-loss atomicity on actual media remains unproven.

Arduino USB does not expose the SPI SD card in either sketch. A mounted card reader supplies the realistic Phase 4 transfer path. Eliminating card shuffling requires Phase 5 hardened firmware and Phase 6 acknowledged USB protocol, or separately specified additional hardware/connectivity.

## Handoff to Phase 5

Use [the roadmap](DEVELOPMENT_PLAN.md) to establish a canonical firmware directory/configuration, identify the actual board/core and measured calibration, harden parsing and bounds, remove the unsafe top move, implement cooperative motion/stop and pen/holding behavior, then compile and commission the physical machine. Preserve reference sketches and pin configuration. Physical measurements/bench results remain explicit acceptance requirements; Phase 4 software completion does not authorize inventing them.

Screenshots: [studio](screenshots/phase-4-studio.png), [mobile](screenshots/phase-4-mobile.png), [test export](screenshots/phase-4-test-export.png).
