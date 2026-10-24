# Phase 1 completion report

Completed 2026-10-24: source analysis, architecture, phased roadmap and a runnable read-only audit. Application implementation begins with Phase 2.

## Findings that determine the implementation

1. **The named root firmware file is empty.** Both actual reference sketches live under vendor/SD folders and use different motor spacing, 350 versus 400 mm. Neither can be assumed to be installed on the machine.
2. **Current “G-code support” is coordinate scanning.** The parser ignores G/M opcodes and feed rates, requires explicit X before Y, interprets Z by sign, and can execute coordinate letters inside comments. The existing mandala's header can itself trigger motion/pen changes. Its origin also differs from the centered reference drawings.
3. **USB control does not exist yet.** Serial initialization is present, but there is no receive loop, file transfer, acknowledgement or live status protocol. The firmware executes only root `main.nc` through its physical SD menu.
4. **The SD mirror is a local directory named `SdCard`.** No mounted removable SD volume or common Arduino USB serial device was visible during inspection. Host-mounted card export is the realistic first transport; USB streaming requires a firmware phase.
5. **Firmware requires correctness and responsiveness work.** Input is unbounded, a final line without LF is dropped, origin is assumed, workspace limits are unenforced, pen-up has no settle delay, drawing blocks input, and completion releases both motors. These need explicit implementation and bench validation.

See [FIRMWARE_AUDIT.md](FIRMWARE_AUDIT.md) and [ASSETS_AND_SD_AUDIT.md](ASSETS_AND_SD_AUDIT.md) for exact source references, pin map, library versions and all sample measurements.

## Analysis coverage

- Inventoried and SHA-256 hashed **543 files**, totaling **702,555,707 bytes**, across both source trees and the empty root sketch.
- Compared **257** shared paths; **256** are identical and the only changed shared file is the firmware.
- Read both complete sketches and traced the used motor, SD and servo implementations and display setup. Inspected library metadata for TinyStepper 1.0.0, Servo 1.1.6, SD 1.2.4 and U8g2 2.28.10.
- Scanned all **26 drawing-code files**, including duplicates and the logo saved as `.txt`; parsed all unique SVG root metadata and measured the binary STL structure/bounds.
- Reviewed the Inkscape extension, archive contents and relevant Processing export source, and all six unique bundled PDFs. These explain the legacy bitmap-to-path-to-`main.nc` workflow. Bundled Windows binaries were not run.
- Selected the future stack and specified coordinates, versioned drawing/profile/job models, exact G-code export, immutable preview/export artifacts, API boundaries, SD ownership, serial-state requirements and interface direction.
- Defined eight phases, their dependency order, ordered work, tests and completion gates. Physical validation is explicitly separate from compilation and software simulation.

This is an audit of supplied source and artifacts. It does not establish the installed firmware, actual wiring, active card contents or mechanical calibration.

## Files added

- `README.md`: current state, navigation and working Phase 1 commands.
- `docs/ARCHITECTURE.md`: implementation design and proposed repository layout.
- `docs/DEVELOPMENT_PLAN.md`: phase-by-phase Codex implementation handoff.
- `docs/FIRMWARE_AUDIT.md`: actual hardware settings, interpreter behavior and defects.
- `docs/ASSETS_AND_SD_AUDIT.md`: source data, tooling, file formats and transfer options.
- `docs/GCODE_CONTRACT.md`: restricted legacy export grammar and validation rules.
- `docs/project-inventory.json`: reproducible complete original-file manifest and lexical job statistics.
- `scripts/audit_project.py`: dependency-free inventory, G-code statistics and preservation verification.
- `tests/test_audit_project.py`: audit regression cases.
- This phase report.

No original file was modified, renamed, removed, compiled, uploaded or sent to physical hardware. The `.git` entry is an empty restricted directory rather than a usable Git repository in this environment, so preservation is verified through content hashes instead of Git diff.

## Verification

Executed successfully:

```bash
python3 -B scripts/audit_project.py --output docs/project-inventory.json
python3 -B -m unittest discover -s tests -v
python3 -B scripts/audit_project.py --verify docs/project-inventory.json
```

Results:

- Inventory completes and produces the full source manifest.
- **4 tests pass**: explicit coordinate/comment interpretation, missing final LF and axis order, empty-file behavior, and duplicate-tree/calibration-change detection. The fixture also verifies that an asset change changes the manifest.
- Preservation verification passes for every original file against the recorded SHA-256 manifest.
- Markdown local-link targets and reported inventory counts are checked before handoff.
- Independent architecture review completed. The plan now explicitly validates each job's initial travel/starting-position precondition, permits status during motion, and requires a host transport that can send stop while awaiting a motion acknowledgement.

Runtime observed: Python **3.14.4**, Node **22.22.1**, npm **9.2.0**, and Poppler `pdftotext`. No application dependencies were installed. The audit supports Python 3.10+; future application dependencies must be pinned and tested during Phase 2.

Not run: frontend/backend application tests (no application yet), Arduino compile (CLI/core unavailable and board unconfirmed), firmware upload, real-card write, real motor/servo tests, AI provider calls, voice input or UI browser checks. They belong to the relevant later phase.

The audit's G-code statistics are lexical and strip customary comments for reporting. The actual old firmware does not strip comments. Its statistics do not certify compatibility, resolve modal state, or prove physical reachability.

## Next milestone

Phase 2 creates the real local application shell, typed backend schemas, health/capability APIs, modern studio interface and installer/one-command launcher. It requires no machine/card access. Phase 3 adds deterministic offline shapes, mandalas, adjustments, live execution-path preview and restricted G-code generation.

Confirming board identity, motor separation, origin and workspace is required for physical commissioning, not for beginning the application work.
