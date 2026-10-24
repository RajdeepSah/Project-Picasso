# Project Picasso

A local application being developed to turn drawing commands into previewed, machine-compatible paths for an Arduino wall drawing machine.

**Current milestone: Phase 1 complete — project analysis, architecture, implementation roadmap, and a runnable source audit. The dashboard, drawing engine, SD synchronization, AI generation, and USB control are planned; they are not implemented yet.**

## Start here

- [Development plan](docs/DEVELOPMENT_PLAN.md): ordered implementation tasks, dependencies, tests, and completion gates for every phase.
- [Architecture](docs/ARCHITECTURE.md): stack, UI, services, data models, storage, and device state.
- [Firmware audit](docs/FIRMWARE_AUDIT.md): pin map, rope geometry, parser behavior, defects, and hardware questions.
- [Assets and SD audit](docs/ASSETS_AND_SD_AUDIT.md): existing drawings, legacy generation tools, manuals, and transfer options.
- [G-code contract](docs/GCODE_CONTRACT.md): the restricted export format required by the existing firmware.
- [Phase 1 report](docs/PHASE_1_REPORT.md): completed work, verification results, and outstanding hardware checks.

## Run the Phase 1 audit

From the project root, with Python 3.10 or newer:

```bash
python3 -B scripts/audit_project.py
```

No packages, API keys, network access, Arduino, or SD reader are required. This command reads the original project files and prints their inventory. It does not generate a drawing or communicate with hardware.

Verify that all original files still match the Phase 1 baseline:

```bash
python3 -B scripts/audit_project.py --verify docs/project-inventory.json
```

Run the audit tests:

```bash
python3 -B -m unittest discover -s tests -v
```

Regenerate a report intentionally after changing source assets:

```bash
python3 -B scripts/audit_project.py --output docs/project-inventory.json
```

The report contains a SHA-256 manifest of all 543 original files and lexical statistics for the 26 drawing-code files, including the logo stored as `.txt`. Statistics are not a certificate that an input file is safe to draw.

## Existing hardware and files

The actual folder is `SdCard/` (case-sensitive), rather than `sdcard/`. It is a local collection of SD contents, not a detected mounted card.

`WallDrawingMachine.ino` is **empty**. Non-empty reference firmware exists at:

- `Drawbot_C/02 arduino code/Walldraw/Walldraw.ino` — motor separation 350 mm.
- `SdCard/02 arduino code/Walldraw/Walldraw.ino` — motor separation 400 mm.

Neither version has been established as the firmware installed on the machine. Both use the on-device menu to read `main.nc` from the physical card's root. They do not accept drawing commands over USB. The original files, including the current `SdCard/main.nc`, have been preserved.

## Application setup in later phases

The selected stack is React + TypeScript + Vite for the interface and Python + FastAPI + SQLite for local services, with pySerial added for USB control. The proposed development prerequisites are Python 3.12+ and Node.js 22.12+; dependency versions will be pinned and tested in Phase 2. Node 22.22.1 and Python 3.14.4 are present here; Arduino CLI is not installed. Current Vite requirements are documented in the [official Vite guide](https://vite.dev/guide/).

Phase 2 will supply a real installer and a single launcher, with this planned interface:

```bash
python3 scripts/setup.py
python3 scripts/picasso.py
```

**Those two launcher files do not exist in Phase 1.** They are the implementation target, not instructions to run today. After setup, the launcher will serve the local application and open its browser window. The first complete offline drawing workflow arrives in Phase 3; no paid AI service will be required for supported shapes and mandalas.

To continue implementation, use: “Implement Phase 2 from `docs/DEVELOPMENT_PLAN.md`, run its checks, and update the phase report.”
