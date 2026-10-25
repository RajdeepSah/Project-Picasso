# Phase 3 completion report

Completed 2026-10-24. Application version **0.3.0** provides the first complete offline command → drawing → adjustment → path preview → draft download workflow.

## Implemented

- A documented offline English resolver for circles/ellipses, rectangles/squares, spirals, butterflies, mandalas and geometric patterns. It accepts millimetre dimensions, supported motif parameters, seed and detail vocabulary. Unknown subjects, unsupported modifiers and ambiguous values return structured errors rather than fabricated artwork.
- A standard-library geometry engine independent of the legacy Inkscape/Processing code. Analytic circles and cubic contours are transformed, flattened to bounded tolerance, rounded to three-decimal millimetres, deduplicated and checked for finite coordinates, nonzero strokes, complexity and length.
- Strict legacy-dialect G-code emission and parsing. Every move contains X before Y and explicit pen state; the file starts/ends pen-up, has a final LF, and contains no comments, unsupported modal commands, feed words or arcs.
- Full round-trip verification of every travel and drawing segment, stroke count and pen lift, including the initial travel from the declared simulation start. Unexpected pen-up detours are rejected too.
- Immutable in-memory draft revisions with generator/exporter versions, prompt/spec, transform, rounded geometry, parsed execution path, warnings and exact G-code SHA-256. Earlier revisions cannot be changed by mutating a later response. Cache limits are 16 drafts / 32 MB.
- Live controls for fit dimensions, aspect lock, rotation, center placement, detail, seed and motif parameters; a 450 ms debounce creates a new revision. Regeneration supports seed locking. The UI retains the last eight revisions in this window and can revisit them without claiming durable history.
- Actual SVG path previews from parsed exported bytes, correct Y orientation, real bounds/distance/stroke metrics, travel/grid toggles, zoom/fit and simulation playback/scrubbing.
- JSON, SVG and exact `.nc` draft downloads, clearly labeled `UNVERIFIED`, with false execution-ready state and per-download checksums. The SVG has no untrusted imported markup or external resources.
- Cooperative engine cancellation and a three-second deadline, with at most two builders. ASGI disconnect monitoring signals the worker. Request-version checks and AbortControllers prevent old results from replacing a newer selection or a cleared drawing.
- Updated API contracts, generated frontend types, launcher banner, package version, README, architecture and roadmap. No new runtime dependencies were added.

## Run and try

The app is built in this workspace. Launch:

```bash
python3 scripts/picasso.py
```

Then enter:

```text
Draw a beautiful mandala
Draw a circle diameter 100
Draw a butterfly seed 7
Create an intricate mandala with 16 petals, 140 mm wide, seed 7
```

Change dimensions/detail or seed in the inspector; use simulation playback; download a draft. Full grammar, limits and coordinate details are in [OFFLINE_DRAWING_COMMANDS.md](OFFLINE_DRAWING_COMMANDS.md).

## Validation

Final Python suite: **60 tests passed**. Coverage includes the retained Phase 1/2 tests and new checks for:

- Every supported subject, deterministic seeded output and exact export hashes.
- Unsupported subjects/modifiers, multiple subjects, contradictory/missing dimensions, parameter ranges and inappropriate generator parameters.
- Known circle/rectangle dimensions, analytic circle chord error and cubic flattening error.
- Mandala rotational symmetry and visible seed variation.
- Rotation/placement/aspect transforms, first travel, pen transitions, immutable revisions and seed retention/regeneration.
- Cancellation, deadline, busy capacity, path budget, rounded-stroke collapse and cache eviction.
- Strict parser rejection of comments, missing/reordered axes, NaN/exponents, feed words, arcs, negative zero, oversized lines and missing final LF.
- Rejection of the supplied mandala header unchanged and detection of unexpected initial travel in a tampered export.
- API generation/revision/retrieval/downloads; SVG orientation/metadata; exact download checksums; missing drafts; invalid export formats; and unavailable physical preparation, SD or motion endpoints.
- An ASGI disconnect during a deliberately slow test worker, confirming cancellation and no stored result.
- Real built/development launchers, proxy requests and clean shutdown with both ports released.

Frontend: **5 component tests passed**, covering real preview display, supported submission, unavailable hardware controls, prior-drawing retention on an unsupported command, automatic dimension/aspect updates, ignored obsolete responses, keyboard behavior, offline recovery, grid and zoom.

Browser: **4 tests passed** against the built application. The primary journey generated a 100 mm circle, resized it to 140 mm, created a mandala, regenerated seed 7 to 8, retained seed 8 on a locked regeneration, and downloaded JSON/G-code. The exact downloaded G-code hash matched the active preview artifact. Other checks covered unsupported-request recovery, mobile generation/adjustment without horizontal overflow, and API outage/reconnect with command preservation. Profile inspection, disabled physical controls, playback, zoom and modal keyboard behavior were also exercised.

The production build, TypeScript check and generated-contract drift check pass. The original 543-file SHA-256 baseline and local documentation links/whitespace checks were verified. Tests requiring loopback/headless Chromium were run outside the agent sandbox because it blocks local sockets.

Executed commands:

```bash
python3 scripts/setup.py --skip-install
.venv/bin/python -m pytest -q
python3 -B scripts/audit_project.py --verify docs/project-inventory.json
```

From `frontend/`:

```bash
npm run contracts:check
npm run build
npm test
PICASSO_BROWSER_PATH=/home/rajdeep/.cache/ms-playwright/chromium-1187/chrome-linux/chrome npm run test:e2e
```

Test environment remains Linux, Python 3.14.4, Node 22.22.1 and npm 9.2.0, with the Phase 2 locked dependencies. The upstream Starlette/httpx TestClient deprecation warning remains; it does not fail the tests. Browser installation/path is environment-specific as documented in the README. macOS/Windows remain unverified.

## Visual verification

- [Desktop generated mandala](screenshots/phase-3-studio.png)
- [Mobile generated mandala](screenshots/phase-3-mobile.png)

Both screenshots show the real running application and generated paths. They were inspected for rendering, readable controls and layout. Historical Phase 2 screenshots were preserved.

## Current boundaries

Physical preparation is **disabled**. Neither reference calibration is active/verified, no workspace is approved, and no machine position is measured. Preview initial travel assumes `(0,0)` and is labeled accordingly. Playback is a fixed-cadence visual simulation, not hardware progress or a duration estimate.

There is no durable database/history, file import, physical-card mount discovery/sync, serial protocol, firmware change, AI provider or voice recognition. Downloading JSON keeps a file copy; importing that file back is planned for Phase 4. Circles and rectangles intentionally do not change shape when a seed changes.

All original assets, root sketch, both firmware copies and `SdCard/main.nc` remain unchanged. No firmware upload, physical SD write, motor movement, external deployment or AI request occurred. Prepared jobs will need verified profile/start conditions and complete path validation in Phase 4, rather than treating these unverified draft exports as execution-ready.

## Next phase

Phase 4 adds durable SQLite drawing history, revision/artifact recovery, sample import and normalization, measured-profile preparation, and verified allowlisted export of the selected `main.nc` to a configured host-mounted card. Preserve the current card data before any managed replacement. USB and firmware work remain Phases 5–6.
