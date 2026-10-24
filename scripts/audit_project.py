#!/usr/bin/env python3
"""Read-only inspection of the original Picasso assets; never opens hardware.

This is an inventory and lexical G-code audit, not a machine safety validator.
Only --output writes a report; the original assets are never changed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys


ORIGINAL_ROOTS = ("Drawbot_C", "SdCard")
ROOT_SKETCH = "WallDrawingMachine.ino"
FIRMWARE_RELATIVE = "02 arduino code/Walldraw/Walldraw.ino"
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
TOKEN = re.compile(rf"([A-Z])\s*({NUMBER})", re.IGNORECASE)
GCODE_SUFFIXES = {".nc", ".gcode"}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def inspect_gcode(data: bytes) -> dict:
    """Summarize explicit words only; do not interpret modal machine motion."""
    text = data.decode("utf-8-sig", errors="replace")
    commands: Counter[str] = Counter()
    axes: dict[str, list[float]] = {axis: [] for axis in "XYZ"}
    counts: Counter[str] = Counter()
    max_line_bytes = 0
    for raw in text.splitlines():
        max_line_bytes = max(max_line_bytes, len(raw.encode("utf-8")))
        if ";" in raw or "(" in raw or ")" in raw:
            counts["lines_with_comments"] += 1
        # Strip customary comments for *lexical* statistics. Legacy firmware
        # does not strip them, which is why their presence is reported above.
        code = re.sub(r"\([^)]*\)", "", raw.split(";", 1)[0]).upper()
        words = [(match.group(1).upper(), match.group(2)) for match in TOKEN.finditer(code)]
        letters = [letter for letter, _ in words]
        for letter, value in words:
            if letter in ("G", "M"):
                commands[f"{letter}{float(value):g}"] += 1
            if letter in axes:
                axes[letter].append(float(value))
        has_x, has_y = "X" in letters, "Y" in letters
        if has_x != has_y:
            counts["lines_with_only_one_xy_axis"] += 1
        if has_x and has_y:
            counts["lines_with_both_xy_axes"] += 1
            if code.find("Y") < code.find("X"):
                counts["lines_with_y_before_x"] += 1
        if "F" in letters:
            counts["lines_with_feed_word"] += 1
        if "Z" in letters and not (has_x or has_y):
            counts["standalone_z_lines"] += 1
    return {
        "line_count": len(text.splitlines()),
        "ends_with_lf": data.endswith(b"\n"),
        "max_line_bytes_excluding_terminator": max_line_bytes,
        "commands": dict(sorted(commands.items())),
        "lexical_flags": dict(sorted(counts.items())),
        "explicit_coordinate_bounds_mm_assumed": {
            axis: {"min": min(values), "max": max(values)}
            for axis, values in axes.items() if values
        },
        "interpretation": "Explicit numeric words only; units, offsets, arcs and modal state are not resolved. Not a compatibility or safety certificate.",
    }


def inspect_firmware(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    names = (
        "STEPS_PER_TURN", "SPOOL_DIAMETER", "X_SEPARATION", "LIMYMAX", "LIMYMIN",
        "PEN_UP_ANGLE", "PEN_DOWN_ANGLE", "BAUD", "MAX_BUF", "TPD", "step_delay",
        "M1_REEL_OUT", "M1_REEL_IN", "M2_REEL_OUT", "M2_REEL_IN",
    )
    defines = {}
    for name in names:
        match = re.search(rf"^\s*#define\s+{re.escape(name)}\s+(.+?)\s*$", text, re.MULTILINE)
        if match:
            defines[name] = match.group(1).split("//", 1)[0].strip()
    return {"line_count": len(text.splitlines()), "defines": defines}


def build_report(root: Path) -> dict:
    manifest = []
    symlinks = []
    for folder in ORIGINAL_ROOTS:
        start = root / folder
        if not start.is_dir():
            raise FileNotFoundError(f"Missing original source folder: {start}")
        for path in sorted(start.rglob("*")):
            if path.is_symlink():
                symlinks.append(path.relative_to(root).as_posix())
            elif path.is_file():
                manifest.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)})
    sketch = root / ROOT_SKETCH
    if not sketch.is_file():
        raise FileNotFoundError(f"Missing root sketch: {sketch}")
    manifest.append({"path": ROOT_SKETCH, "bytes": sketch.stat().st_size, "sha256": digest(sketch)})
    manifest.sort(key=lambda entry: entry["path"])
    summaries = {}
    by_tree = {}
    for folder in ORIGINAL_ROOTS:
        entries = [item for item in manifest if item["path"].startswith(folder + "/")]
        summaries[folder] = {
            "files": len(entries), "bytes": sum(item["bytes"] for item in entries),
            "extensions": dict(sorted(Counter(Path(item["path"]).suffix.lower() or "[none]" for item in entries).items())),
        }
        by_tree[folder] = {item["path"][len(folder) + 1:]: item for item in entries}
    first, second = (by_tree[folder] for folder in ORIGINAL_ROOTS)
    shared = sorted(first.keys() & second.keys())
    changed = [name for name in shared if first[name]["sha256"] != second[name]["sha256"]]
    gcode = {}
    for item in manifest:
        path = root / item["path"]
        is_logo = path.name == "Washburn logo.txt"
        if path.suffix.lower() in GCODE_SUFFIXES or is_logo:
            gcode[item["path"]] = inspect_gcode(path.read_bytes())
    firmware = {
        f"{folder}/{FIRMWARE_RELATIVE}": inspect_firmware(root / folder / FIRMWARE_RELATIVE)
        for folder in ORIGINAL_ROOTS
    }
    return {
        "schema_version": 1,
        "scope": [*ORIGINAL_ROOTS, ROOT_SKETCH],
        "summary": {
            "files": len(manifest), "bytes": sum(item["bytes"] for item in manifest),
            "root_sketch_bytes": sketch.stat().st_size, "trees": summaries,
            "shared_relative_paths": len(shared), "identical_shared_files": len(shared) - len(changed),
            "changed_shared_paths": changed,
            "only_in_Drawbot_C": sorted(first.keys() - second.keys()),
            "only_in_SdCard": sorted(second.keys() - first.keys()),
            "gcode_files_including_logo_txt": len(gcode),
        },
        "symlinks_skipped": symlinks,
        "firmware": firmware,
        "gcode": gcode,
        "manifest": manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="Write the full JSON report to this explicit path.")
    parser.add_argument("--verify", type=Path, help="Compare original asset hashes against a saved JSON report.")
    args = parser.parse_args()
    report = build_report(args.root.resolve())
    if args.verify:
        baseline = json.loads(args.verify.read_text(encoding="utf-8"))
        if baseline["manifest"] != report["manifest"]:
            print("FAIL: original asset manifest differs from the baseline.", file=sys.stderr)
            return 1
        print("PASS: every original file matches the saved SHA-256 manifest.")
    if args.output:
        target = args.output.resolve()
        # Never allow a report to overwrite anything in either original tree.
        for folder in ORIGINAL_ROOTS:
            if target.is_relative_to((args.root.resolve() / folder).resolve()):
                parser.error("--output must be outside the original asset trees")
        if target == (args.root.resolve() / ROOT_SKETCH):
            parser.error("--output must not overwrite the root sketch")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Report written: {args.output}")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
