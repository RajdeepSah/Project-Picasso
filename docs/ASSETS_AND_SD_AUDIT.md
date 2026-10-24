# Assets, legacy workflow, and SD card audit

Phase 1, inspected 2026-10-24. This document describes the supplied files, not a verified physical machine. All original assets and firmware remain untouched.

## What is actually present

The directory is named `SdCard`, with that exact capitalization. There is no lowercase `sdcard` directory. On Linux these names are different. The application should configure an explicit local export path rather than silently creating a second directory.

The initial project contains:

- `Drawbot_C`: 275 files, 654,019,252 bytes. Ten sample drawings, nine SVGs, ten JPEGs, firmware, four bundled Arduino libraries, legacy Windows tooling, manuals, and one mechanical STL.
- `SdCard`: 267 files, 48,536,455 bytes. Almost the same firmware, libraries, samples, and STL, plus user-added jobs and root `main.nc`. Most large development tools are absent.
- `WallDrawingMachine.ino`: zero bytes. It is not the operating firmware baseline.

Of 257 shared relative file paths between `Drawbot_C` and `SdCard`, 256 are byte-for-byte identical. The only differing shared file is `02 arduino code/Walldraw/Walldraw.ino`. Do not choose a firmware copy just because it is in the SD mirror: compare calibration and confirm which version is flashed. See `FIRMWARE_AUDIT.md`.

There are ten sample `.nc` files in `Drawbot_C`, fourteen in `SdCard` including its root `main.nc`, one extra `.gcode`, and a `.txt` file whose contents are G-code. That is 26 job files across the initial tree, with duplicated vendor samples. Filename extensions alone are insufficient for import detection.

## Current drawing workflow

The bundled Inkscape manual, `Drawbot_C/03 Tools/1、G code generation tool/Instructions for use.pdf`, describes this workflow:

1. Install Inkscape and copy the `Youzhihui NC` extension into its extensions directory.
2. Import a bitmap, choose edge or centerline tracing, and remove the original bitmap.
3. Save the paths using the YouzhiHui `.nc` export option and name the output `main.nc`.
4. Set the page center values, preview the path, copy `main.nc` onto the TF/SD card, then start drawing from the machine's menu.

The extension UI explicitly says to convert text to paths and that curves become line segments (`unicorn.inx:31`). A4 center is approximately `(105,149)` mm and A3 center approximately `(149,210)` mm (`unicorn.inx:18`). The physical pen origin, page center, and SVG page coordinate system must remain distinct in the new application.

All nine unique SVG files declare an A4 `210mm × 297mm` page and `viewBox="0 0 210 297"`. This describes the page, not the drawing's occupied bounds. Their G-code occupies smaller centered areas. JPEG files are raster references rather than machine instructions. The banana sample has a JPEG and `.nc`, with no SVG in either tree.

## Exact sample inventory and compatibility

Bounds below come from explicit X/Y words in each file, including travel moves and returns to zero. They are in the legacy millimeter coordinate convention. These are static measurements, not assertions that the machine can safely reach each point. The ten vendor `.nc` jobs are identical in both trees.

- Bikini: 1,418 lines; X `-71.90..82.78`, Y `-71.47..70.29`.
- Crab: 1,788 lines; X `-53.41..54.30`, Y `-46.15..28.81`.
- Girl: 1,783 lines; X `-83.32..87.42`, Y `-58.69..72.72`.
- Girl1: 1,664 lines; X `-87.51..84.20`, Y `-105.20..102.55`.
- Hamburger: 282 lines; X `-39.33..32.89`, Y `-13.88..38.83`.
- TOM: 3,070 lines; X `-95.95..95.59`, Y `-114.89..114.78`.
- Airliner: 501 lines; X `-85.09..86.05`, Y `-61.65..47.75`.
- Banana: 2,677 lines; X `-59.88..60.00`, Y `-60.59..60.59`.
- Receding figure: 1,097 lines; X `-76.11..81.58`, Y `-44.93..50.54`.
- Receding figure1: 3,959 lines; X `-94.16..85.07`, Y `-110.43..25.54`.

`SdCard` also contains:

- `main.nc`: 71,716 bytes, 3,868 lines, X/Y each `-105..105`. It begins with a radius-5 circle and contains multiple circular/radial paths; pen state uses Z1/Z0. It ends with a pen-up command but does not return to zero. This is the only path selected by the current firmware's SD menu.
- `01 Test GCode/circle.nc`: 125 lines, X/Y each `-50..50`, Z1/Z0, explicit final pen-up and return to zero.
- `01 Test GCode/cat.nc`: 557 lines, X `-37..37`, Y `-40.30..40.30`, Z1/Z0.
- `01 Test GCode/skeleton.nc`: 1,090 lines, X `-26.90..26.90`, Y `-60..60`, Z1/Z0.
- `01 Test GCode/Washburn logo/Washburn logo.txt`: 263 lines of actual G0/G1 instructions, X `-59.22..59.98`, Y `-46.37..48.12`, Z1/Z0. Import as a job only after content validation, then export as `.nc`.
- `01 Test GCode/mandala_11x14.gcode`: 331,164 bytes, 13,732 lines, maximum line length 96. Header declares an 11×14 inch page (`279.4 × 355.6` mm), lower-left origin, center `(139.7,177.8)`, and maximum radius 126 mm. Explicit coordinates, including the end travel, span X `0..265.7`, Y `0..303.8`. It uses G21/G90/G17, G0/G1, F feed words, M2, semicolon comments, and Z3/Z0.

All supplied job files end with a newline. Vendor NC files use G0/G00/G01, explicitly ordered X before Y, and Z as a logical pen flag; Z20 in the preamble also raises the pen. They use parenthesis comments. The new canonical exporter should follow [GCODE_CONTRACT.md](GCODE_CONTRACT.md): comment-free explicit X/Y/Z moves using Z5/Z0, with initial/final pen-up lines. Existing Z1/Z0 samples need normalization into that contract.

The mandala must **not** be copied unchanged for execution. The current `nc()` function does not interpret G/M command semantics, strip comments, or honor feed rates (`Drawbot_C/.../Walldraw.ino:310`). Its second header comment includes X and Y, so the legacy parser can treat that comment as a real move to `(139.7,177.8)`. The third comment contains Z and can change pen state. Its drawing uses a different origin and exceeds the smaller source profile's nominal X extent. Import should remove comments, understand units/modal state, reject unsupported semantics, translate the intended center to the calibrated drawing origin, fit within a confirmed work area, and regenerate the restricted dialect. A maximum-line policy must be enforced by the future bounded parser; the legacy `MAX_BUF` declaration itself does not bound SD file reads.

## Legacy extension audit

Use these files as historical references and fixtures, not as the foundation for the new drawing engine:

- `unicorn.py:21` imports `inkex` and depends on running inside an appropriate Inkscape extension environment. It is not a standalone Python generator.
- `unicorn/context.py:32` emits a Z20 preamble, and `:119` / `:124` implement the actual logical pen-down and pen-up values. The parameter names say “angle,” but the firmware interprets Z by sign; these are not physical servo angles.
- `unicorn/context.py:148` labels a command “pen down” but formats `pen_up_angle`. The polyline path normally calls `start()` first and therefore avoids that branch, but the helper is defective.
- `unicorn/context.py:129` / `:142` compare transformed coordinates to `self.last`, while `:139` / `:152` store untransformed coordinates. Duplicate-point detection is inconsistent.
- `unicorn/context.py:63` can emit G92 for multiple sheets and `:88` emits M30 for continuous mode. Neither has the intended control meaning in this firmware. Layer pause generates M01 in `svg_parser.py:201`, which also has no implemented pause meaning.
- `unicorn/svg_parser.py:252` hard-codes a `0.28222` pixel-to-mm conversion and applies it even when dimensions already use mm; it does not provide a dependable general `viewBox`/physical-unit conversion pipeline. SVG units and transforms need explicit tests in the new importer.
- `unicorn/svg_parser.py:279` uses `pass` when a node is hidden, then continues processing it. Hidden geometry can still be exported.
- The unused/general entity helpers can emit G3 arcs (`unicorn/entities.py`), but the firmware's file parser does not dispatch its arc function. Flatten all curves to polylines in the application.

The new engine should own millimeter geometry independently of SVG rendering. A preview and machine job must derive from the same validated path set.

## Other tools, archives, and mechanical assets

No bundled executable was run and no archive code was executed. Archive listings and selected plaintext source members were inspected read-only.

- Inkscape 1.0 x86/x64 installers, CIMCOEdit, CH341SER, an offline Arduino library installer, and `Crate GCode.exe` are Windows executables. `Crate GCode.exe` is a .NET assembly and no corresponding source is supplied. None should be an application runtime dependency.
- The CIMCO manual describes a legacy preview tool and includes a third-party activation-patch procedure. The new app should provide its own preview and must not automate that procedure.
- `processing-3.5.4.zip` contains 3,266 archive entries including a bundled Windows Java runtime and license files. It is a legacy tool distribution, not a service or application backend.
- `Drawbot_image_to_gcode_v2.rar` contains 45 entries with Processing `.pde` source, image assets, README, key bindings, and a GPL v3 license file. Its modified `Gcode.pde` writes `gcode\\main.nc`, emits Z1/Z0 plus explicit X/Y, and includes G21/G90 headers that this firmware simply ignores. It offers image-to-line strategies including original, spiral, and square path-finding modules. The bundled manual says some original shortcuts no longer apply. The Windows path separator and legacy Processing environment should not enter the new cross-platform service.
- The archive's upstream project is identified in its local manual as `Scott-Cooper/Drawbot_image_to_gcode_v2`. No upstream source was needed to establish the supplied modified code's behavior.
- Both `04 STL files/Kit.stl` files are identical binary STL files with 5,986 triangles. Mesh-coordinate bounds are X `-56.2716..43.0768`, Y `-84.6852..74.5811`, Z `0..41.9765`. STL does not encode physical units. The mesh describes mechanical parts; it does not establish the assembled machine's calibration or work area.

The six unique bundled PDFs were text-extracted. The one-page TinyStepper hookup PDF has no useful extractable text and was rendered and inspected visually. It shows a generic Arduino UNO, ULN2003 driver, 28BYJ-48 motor, common ground, and external 5V supply; its example pins differ from this sketch and are not instructions to rewire the machine. The stepper documentation discusses blocking versus nonblocking moves and warns of the light-duty motors' low speed. The CH340 datasheet describes a USB-to-serial chip; its inclusion suggests a serial bridge but does not prove the actual board or USB connection.

## Physical SD and Arduino accessibility

Read-only inspection during Phase 1 found only the system NVMe device and snap loop mounts in `lsblk`; no removable SD mount was visible. No `/dev/ttyACM*` or `/dev/ttyUSB*` nodes were visible. This is a point-in-time observation of this environment, not proof that the user has no hardware.

`SdCard` is currently a project directory on the system filesystem. Its name and `System Volume Information` files suggest a copied card image, but do not create a live connection. The existing Arduino SD menu opens literal root `main.nc` (`Drawbot_C/.../Walldraw.ino:516`). Subdirectories and a history folder are not browsable from that menu. `Serial.begin(115200)` is present, but there is no serial command receiver or file-upload implementation.

### Recommended first integration: managed local export and mounted-card copy

1. Preserve the supplied `SdCard` contents and root `main.nc` as original user data. Store generated/history jobs elsewhere; create an explicit export/staging area with an allowlisted job manifest.
2. Configure a specific physical card mount path separately from the local export directory. Detect mounting/removal and surface `not configured`, `unmounted`, `ready`, `copying`, and `verified` states accurately.
3. Publish only a validated selected job as the card's root `main.nc`, since this is what the stock firmware reads. Save a timestamped/hash backup of an existing `main.nc` first. Do not recursively mirror the entire vendor folder or delete unrelated card files.
4. Stage a temporary file on the same filesystem, flush and close, verify length and checksum, then replace the active job. Verify readback of final `main.nc` and report success only after it matches. Handle FAT filesystem rename limitations and interrupted copies; never report a partially written job as ready.
5. Detect source/destination collisions, symlink escapes, insufficient space, permission failures, removal during copy, and changes to an external `main.nc`. Keep the user's local project as the source of truth for app-managed files; offer explicit import of external jobs rather than automatic destructive bidirectional merging.
6. Release handles before safe eject. The card must be owned by one host at a time. A card inside the Arduino's SPI reader does not automatically appear as a disk on the laptop, and it must not be concurrently mounted by both devices.

This gives a realistic initial product: generate and preview locally; copy automatically when the configured card is mounted in a computer reader; safely eject and move the card back to the machine; start with its existing button menu. Copying is not remote execution, and no live machine status should be inferred from a successful copy.

### Later integration: USB serial streaming

If the existing board exposes USB serial, the laptop can stream validated lines after a firmware update; a separate Wi-Fi board is not inherently required. Use a versioned capability handshake, one outstanding command or bounded explicit credits, completion acknowledgments, timeouts, and exclusive device ownership. The app needs a local native service for filesystem and serial access. Opening serial may reset some Arduino boards; never assume the physical origin is retained after a reconnect or reset.

Firmware upload-to-SD is another possible USB protocol, but is separate work from line streaming: it requires framing, length/hash validation, a temporary file, commit semantics, and adequate RAM/flash. Block SD execution during upload. Acknowledging bytes received is different from acknowledging motion complete. A direct USB cable cannot make the stock firmware's SD card appear as USB mass storage without appropriate hardware/firmware.

### Optional future hardware

A Raspberry Pi can run the local service beside the machine and connect to the existing Arduino over USB. An ESP32/Wi-Fi gateway can proxy a serial protocol but requires wiring, correct logic levels, power, firmware, and an ownership design. A switched SD reader needs explicit electrical ownership and is more complex than serial streaming. These are options to evaluate after board identification; none is assumed installed or implemented in Phase 1.

## Preservation and third-party material

Keep the vendor folders unchanged during the initial phases. Deduplicate or relocate them only after recording hashes and updating references. Exclude installers, Processing/Java distributions, archives, card OS metadata, and sample artwork from the new app's runtime package.

`unicorn.py` carries MakerBot Industries' GPL v2-or-later notice; the Processing archive contains GPL v3 text. Arduino libraries carry their own individual license notices. Retain these when redistributing or deriving code, and record provenance rather than applying a single new license to the entire supplied bundle. No standalone reuse license was established for the sample artwork or STL. Prefer an independently implemented geometry pipeline and preserve original notices for historical references.

## Phase 1 validation and implementation handoff

Completed: complete initial file inventory; content hashes for overlapping trees; all supplied job files scanned; all SVG roots parsed; extension Python/XML read; relevant archive listings and Processing export source read; STL structure/bounds checked; all unique manuals inspected; physical mount and common USB serial node availability checked. No physical drawing, Arduino compilation/upload, SD write, or executable installation was performed.

Next implementation priorities: a single millimeter path model and strict legacy exporter; importer normalization for the existing mandala; a real local UI/service; durable job history; managed SD staging and verified copy; then firmware parser hardening and acknowledged USB streaming. Hardware work starts only from a confirmed board, pin map, physical calibration, power arrangement, and origin procedure.
