# Phase 2 completion report

Completed 2026-10-24. Version **0.2.0** implements the application foundation and local studio. Phase 3 drawing generation and all hardware operations remain unimplemented.

## Delivered behavior

- A React/TypeScript studio with command composer, example command shortcuts, blank A4 preview, working grid/zoom/reset controls, history view, drawing inspector, profile inspector, disabled microphone, and getting-started/information dialogs.
- A real FastAPI service reporting health, version, implemented capabilities, reference profiles and independent hardware/storage states. The frontend loads these APIs and refreshes every 15 seconds; errors show a reconnect action while preserving the current command.
- Command submission uses the backend. It validates the request and returns HTTP 501 `GENERATION_UNAVAILABLE`, explaining Phase 3. It never fabricates a preview or successful generation. Enter submits; Shift+Enter inserts a new line. Empty/oversize/unknown-field requests are rejected.
- The two source calibrations exist as versioned JSON reference profiles. Both are structurally restricted to `verified=false`, `board=null`, `allowed_region=null`; there is no active profile. Inspecting one in the UI changes no machine configuration.
- Strict versioned Pydantic schemas cover drawing specifications, finite millimetre paths, profiles, capability/status responses and errors. TypeScript definitions are generated from the backend JSON schema, including correctly typed XY tuples. Drift checks verify both schema and TypeScript output.
- Locked dependencies, a project virtual environment, documented installer, production build, one-command launcher and development mode. The launcher waits for the correct backend instance before opening a browser, handles port conflicts, and stops its child processes on normal shutdown.
- Local font files and their license are bundled, so runtime requires no external assets, API keys or cloud service. Loopback binding, trusted-host/origin checks and limited static mounting prevent the interface from exposing the vendor files through the API.
- A GitHub Actions workflow runs setup/build, detects generated-contract drift, and runs backend/component/browser tests when the code is pushed. No remote workflow run has been performed in this session.

## Run it

Already installed and built in this workspace:

```bash
python3 scripts/picasso.py
```

The browser opens at `http://127.0.0.1:8000`. Ctrl+C stops the app. Use `--no-browser` for a terminal-only server, `--port 8001` for another backend port, or `--dev` for the Vite frontend at port 5173 with a backend proxy and live reload. `--frontend-port` changes the development frontend port.

On a fresh checkout, first run:

```bash
python3 scripts/setup.py
```

The full command was executed successfully, using the committed lockfiles and rebuilding the application. Initial Python installation used a newly created local virtual environment; the documented setup then confirmed those exact Python versions and performed a clean `npm ci`. It does not rely on globally installed FastAPI/React packages. Runtime does not need Node after the frontend has been built.

## Validation completed

**16 Python tests passed**, covering:

- Original Phase 1 audit regression cases.
- Health/capabilities, both unverified profiles, independent uninspected hardware states, and explicit generation unavailability.
- Invalid drawing data, nonfinite coordinates, unsupported units/parameters, invalid requests, host/origin rejection, and private project-file boundaries.
- Built frontend serving, missing frontend response, missing configuration startup failure, early backend exit, invalid ports and occupied-port behavior.
- Real production and development launchers, real HTTP requests, frontend serving/proxying, cross-origin development command submission, graceful shutdown and release of both ports.

**3 frontend component tests passed**, covering command submission/preservation, unavailable controls, offline reconnect, keyboard behavior, grid and zoom.

**3 browser tests passed** against the actual built app, covering:

1. Connected desktop studio, command response, profile inspection without activation, zoom, modal opening/Escape, and no JavaScript page errors.
2. A 390-pixel mobile viewport, command submission and no horizontal page overflow.
3. Simulated API outage and reconnect with the drafted command preserved.

Additional checks passed: full installer, production build, TypeScript check, generated-contract drift check, original-file SHA-256 verification, and whitespace/local-documentation-link checks.

Commands used:

```bash
python3 scripts/setup.py
.venv/bin/python -m pytest -q
```

From `frontend/`:

```bash
npm run contracts:check
npm run typecheck
npm test
npm run build
PICASSO_BROWSER_PATH=/home/rajdeep/.cache/ms-playwright/chromium-1187/chrome-linux/chrome npm run test:e2e
```

The browser path above is specific to this environment. Other machines can use `npx playwright install chromium` followed by `npm run test:e2e`. Browser and loopback-dependent Python checks required execution outside the restricted sandbox here. Ordinary terminal use is unaffected by that agent sandbox restriction.

The cached headless browser had no usable fallback font: even a standalone HTML heading measured zero height. Bundled Space Grotesk fixed that independently verified environment issue and ensures consistent offline typography. The test runner was configured to terminate the launcher gracefully so it can clean up its separate backend process group.

The Python suite emits one upstream Starlette deprecation warning about the `httpx` TestClient adapter; all assertions pass. npm reports a deprecated transitive `whatwg-encoding` package used by the test DOM. Neither is hidden or presented as a runtime failure.

## Tested versions

- Linux; Python 3.14.4; Node 22.22.1; npm 9.2.0.
- FastAPI 0.162.0, Pydantic 2.14.1, Uvicorn 0.54.0, pytest 9.1.1.
- React/React DOM 19.3.1, Vite 8.3.5, TypeScript 7.0.2, Vitest 5.0.5, Playwright 1.64.1, jsdom 26.1.0.
- Every resolved Python package is pinned in `backend/requirements.lock`; frontend direct and transitive dependencies are locked in `frontend/package-lock.json`.

The supported setup baseline is Python 3.12+ and Node 22.12+, but only the versions above were executed here. macOS/Windows and other runtime versions are unverified.

## Screenshots

- [Desktop studio](screenshots/phase-2-studio.png)
- [Mobile studio](screenshots/phase-2-mobile.png)

These show the actual running application. The blank preview is intentional: there is no drawing engine yet and no artwork is presented as generated output.

## Boundaries and preservation

There is no drawing generation, G-code export, durable history/database, SD mount discovery/write, serial port discovery/connect/control, firmware update, AI provider or speech recognition. Hardware status means **control unavailable / not inspected**, not a scan asserting that no device exists. The A4 preview page is a visual workspace, not a verified physical drawing region.

No original assets, firmware, current `SdCard/main.nc`, or root empty sketch were modified. All **543 original files** match the Phase 1 SHA-256 manifest. The pre-existing project license and installer/archive ignore rules were preserved. No Arduino upload, SD write, motor movement or external deployment occurred.

Loopback/file/serial write authorization must be added with the future write endpoints; no per-launch write token is claimed today. No physical operation is available for an unverified profile.

## Next: Phase 3

Implement deterministic circle/ellipse, rectangle, spiral, butterfly and mandala/pattern generators; supported command resolution; transform/detail/seed controls; strict legacy G-code emission and parsing; and previews derived from the exact exported path. Continue to preserve the physical preparation gate and the expected-start/initial-travel requirements in the G-code contract.
