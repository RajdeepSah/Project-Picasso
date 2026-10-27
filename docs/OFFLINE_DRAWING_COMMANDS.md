# Offline drawing commands and drafts

Phase 3 implements a small English command grammar. It selects deterministic generators; it is not a chatbot or a general AI illustration service. No API key, hardware connection or internet service is needed.

## Try these commands

```text
Draw a circle
Draw a circle diameter 100
Draw a circle radius 25 mm
Draw an ellipse 120 x 80 mm
Draw a rectangle width 140 mm height 90 mm
Draw a square 100 x 100 mm
Draw a spiral with 5 turns, 150 mm wide
Draw a butterfly seed 7
Draw a beautiful mandala
Create an intricate mandala with 16 petals, 140 mm wide, seed 7
Create a complex geometric pattern with symmetry 8
```

Use one subject per command: circle, ellipse/oval, rectangle/square, spiral, butterfly, mandala or geometric pattern/pattern. `draw`, `create`, and `make` are interchangeable. Case does not matter, and `×` can replace `x`.

Dimensions are in **millimetres**. Supported forms are `W x H mm`, `120 mm wide`, `width 120 mm`, `height 80 mm`, `diameter 100`, or `radius 50`. Radius/diameter apply to circles/ellipses only. Do not combine contradictory dimension forms. Bare numbers and parameters missing a value are rejected with an explanation.

For a width-only command, circles, squares, spirals, mandalas and patterns use the same height. Rectangles/ellipses use height = two-thirds of width, and butterflies use height = three-quarters of width. A height-only command uses the inverse ratio. Explicit width and height override those defaults; a circle with unequal dimensions is displayed as an ellipse.

Detail vocabulary: `simple`/`sparse`, `standard`, or `intricate`/`complex`/`dense`. Choose one level. Detail changes flattening tolerance and, for decorative generators, motif density.

Generator parameters:

- Mandala: `3–64 petals` or `symmetry 3–64`. If both are supplied, they must agree.
- Pattern: `symmetry 2–64`.
- Spiral: positive `turns` up to 100; excessive size/detail may hit the path budget.
- Every subject: integer `seed 0–4294967295`.

Extra objects, colors, unsupported adjectives/modifiers, relative requests such as “make it bigger”, inches, raw SVG and raw G-code are not interpreted here. Use the inspector for edits. Broader language interpretation is planned for Phase 7; file import/normalization is available in Phase 4 through the Import drawing dialog.

## Adjust and regenerate

After generation, the inspector enables fit width/height, aspect-ratio lock, rotation, X/Y center placement, detail, seed, and subject-specific parameters. Valid edits are applied after a 450 ms pause, creating a new revision. Actual occupied bounds can differ slightly from requested fit dimensions because curves are flattened and coordinates rounded; rotation also changes those bounds. The displayed bounds always come from the final exported path.

Aspect lock couples width/height using the selected revision's ratio. Unlock it to stretch a shape. The backend also exposes `transform.preserve_aspect` for fitting a generator's native aspect ratio into a requested box; the regular UI instead couples the numeric dimensions explicitly.

**Regenerate drawing** increments the seed by one. **Keep seed when regenerating** retains it and produces identical G-code for the same settings. Seeds vary butterflies, mandalas, patterns and spirals; mathematical circles and rectangles keep their geometry when the seed changes.

New commands, parameter edits, selecting a saved revision, cancellation and “New drawing” invalidate older pending UI responses. An obsolete response cannot replace the active drawing. Unsupported commands retain the prior successful drawing.

## Preview and simulation

The backend emits exact restricted G-code, parses those bytes back, and verifies the full travel/drawing sequence against its rounded geometry. The preview renders those parsed segments. SVG display/export flips Y for screen coordinates; the G-code remains centered Cartesian Y-up millimetres.

Grid, zoom/fit, travel toggle, playback/pause and scrubbing are available. Playback has a fixed visual cadence and is **not a physical drawing-time estimate**. No speed/feed control is offered because the legacy firmware ignores F.

The initial travel is included, assuming a simulation start of `(0,0)` mm. That is not a position reading. Bundled references are never verified or selected automatically, and the preview view box is not an approved machine envelope.

## Keep a copy

Choose **Export G-code** in the top bar, or open its menu (the arrow beside it) for **G-code**, **SVG** or **PNG**. Downloads use the exact selected revision and never regenerate it. Filenames say what the drawing is, its size and its revision, for example `picasso-butterfly-120x90mm-rev3.gcode` (imported drawings use the source file's name). The HTTP response also reports `X-Picasso-Execution-Ready: false` and a SHA-256 checksum of the downloaded bytes.

- `.gcode` uses only `G0 Z5`, explicit `G0 X... Y... Z5` travel, and explicit `G1 X... Y... Z0` drawing. It is ASCII with three-decimal XY values and a final LF. See [GCODE_CONTRACT.md](GCODE_CONTRACT.md). Import drawing reads it back as a new draft.
- `.svg` contains the pen-down path, correctly oriented for a screen, with millimetre dimensions/view box and the drawing's title. Travel moves stay in the G-code rather than being drawn into the artwork.
- `.png` is the same pen-down path rendered black on white at 10 px/mm (about 254 dpi), scaled down so the longest side is at most 4000 px.

The full draft record is still available from the API as `GET /api/drawings/{revision_id}/export?format=json`; the studio no longer offers it as a download.

Downloads are not prepared physical jobs. A download itself does not replace files or start the machine. Measured-profile preparation and reviewed SD export are separate API workflows; see [STORAGE_AND_COMMISSIONING.md](STORAGE_AND_COMMISSIONING.md). Actual board/calibration/workspace/start and pen behavior must be verified before physical operation.

## Storage and computational limits

Phase 4 automatically saves each completed revision to local SQLite and immutable files. History survives restart and supports search, pagination and checksummed repair. The backend's **16 drafts / 32 MB** LRU is only a working cache; eviction does not remove saved artifacts. The browser shows eight recent shortcuts and opens the full saved history separately. Failed or interrupted saves are not reported as saved. Cancellation can race with a save already committed; completed work may appear in history.

Per-operation computational limits:

- Three-second cooperative deadline; two simultaneous builders.
- 20,000 points, 1,000 strokes, 1 MB G-code and 250 metres of combined drawing/travel.
- Finite positive fit dimensions no larger than 2000 mm; coordinates restricted to ±5000 mm for computational preview only.
- Rotation −360° to 360° and center offsets ±2000 mm.
- Curve chord tolerance: simple 0.2 mm, standard 0.08 mm, intricate 0.025 mm; coordinate rounding adds at most approximately 0.000708 mm per point.
- Cancellation is cooperative at engine checkpoints. Disconnects signal the worker; the UI also ignores obsolete responses. Work already completed at the instant of cancellation may have been saved to history.

Circles/ellipses are sampled analytically with a sagitta bound. Other organic paths are defined by cubic Béziers and flattened with a control-hull distance bound after transformation. Spirals are defined by Hermite cubic segments approximating an Archimedean motif; the recorded flattening tolerance is relative to those stored generator curves. These are geometric approximation limits, not measured mechanical accuracy.
