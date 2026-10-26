#!/usr/bin/env python3
"""Canonical firmware maintenance: configuration, host tests and Arduino builds.

  python3 scripts/firmware.py config --profile <measured-id> | --reference reference-350
  python3 scripts/firmware.py host-test
  python3 scripts/firmware.py build [--fqbn arduino:avr:uno] (--profile ID | --reference ID)

Nothing here uploads firmware, opens a serial port or moves the machine.
Upload is a separate, explicit operator step documented in firmware/README.md.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKETCH = ROOT / "firmware" / "WallDrawingMachine"
HOST = ROOT / "firmware" / "host"
SHIMS = ROOT / "firmware" / "shims"
LIBRARIES = ROOT / "Drawbot_C" / "02 arduino code" / "Library"
TINYSTEPPER = LIBRARIES / "TinyStepper_28BYJ_48" / "src"
DEFAULT_FQBN = "arduino:avr:uno"
CORE = "arduino:avr@1.8.6"


def load_profile(profile_id=None, reference=None, data_dir=None):
    """Return (profile, kind) for a saved measured profile or a source reference."""
    from backend.app.profiles import load_reference_profiles
    references = {profile.id: profile for profile in load_reference_profiles(ROOT)}
    if reference:
        if reference not in references:
            raise SystemExit(f"Unknown reference {reference!r}; choose one of {', '.join(sorted(references))}.")
        return references[reference], "source reference (no workspace)"
    from backend.app.storage.preparation import ProfileManager
    from backend.app.storage.repository import Repository
    root = Path(data_dir or os.environ.get("PICASSO_DATA_DIR", ROOT / "data"))
    profile = ProfileManager(Repository(root), list(references.values())).get(profile_id)
    return profile, "verified measured" if profile.verified else "unverified measured"


def host_test_profile():
    """Synthetic profile for host builds only; never a hardware measurement."""
    from backend.app.models import CalibrationProfile
    return CalibrationProfile(
        id="host-simulation", revision="host-simulation", version=1, recorded_at="1970-01-01T00:00:00+00:00",
        label="Host simulation fixture (synthetic)", base_reference_id="reference-350", board="simulated",
        separation_mm=350, anchor_y_mm=250, spool_diameter_mm=35, steps_per_turn=2048, pen_up_degrees=85,
        pen_down_degrees=70, allowed_region=dict(min_x_mm=-150, max_x_mm=150, min_y_mm=-100, max_y_mm=150, margin_mm=5),
        rope_min_mm=100, rope_max_mm=600, measured_by="host simulation", measurement_notes="Synthetic values for host tests.",
        origin_procedure="Synthetic: the simulator confirms origin through the keypad flow.")


def write_config(profile, kind, target: Path) -> str:
    from backend.app.firmware import config_id, render
    target.write_text(render(profile, kind=kind), encoding="ascii")
    return config_id(profile)


def compiler():
    found = os.environ.get("CXX") or shutil.which("g++") or shutil.which("c++")
    if not found:
        raise SystemExit("A C++11 compiler (g++) is required for host firmware tests.")
    return found


def host_build(out_dir: Path, config: Path) -> dict:
    """Compile core tests, the parser/geometry tool and the simulator on the host."""
    cxx = compiler()
    strict = [cxx, "-std=gnu++11", "-O1", "-Wall", "-Wextra", "-Werror"]
    core = str(SKETCH / "picasso_core.cpp")
    out_dir.mkdir(parents=True, exist_ok=True)
    binaries = {name: out_dir / name for name in ("core_tests", "picasso_tool", "simulator")}
    commands = [
        strict + ["-I", str(SKETCH), str(HOST / "core_tests.cpp"), core, "-o", str(binaries["core_tests"])],
        strict + ["-I", str(SKETCH), str(HOST / "picasso_tool.cpp"), core, "-o", str(binaries["picasso_tool"])],
        # The vendored library is compiled unmodified, without our warning policy.
        [cxx, "-std=gnu++11", "-O1", "-w", "-I", str(HOST / "stubs"), "-I", str(SHIMS), "-I", str(TINYSTEPPER),
         "-c", str(TINYSTEPPER / "TinyStepper_28BYJ_48.cpp"), "-o", str(out_dir / "tinystepper.o")],
        strict + ["-I", str(HOST / "stubs"), "-I", str(SHIMS), "-I", str(SKETCH), "-I", str(TINYSTEPPER),
                  f'-DPICASSO_MACHINE_CONFIG="{config.resolve()}"', str(HOST / "simulator.cpp"), core,
                  str(out_dir / "tinystepper.o"), "-o", str(binaries["simulator"])],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"Host firmware build failed:\n{' '.join(command)}\n{result.stdout}{result.stderr}")
    return binaries


def arduino_build(fqbn: str, profile, kind: str) -> int:
    cli = os.environ.get("ARDUINO_CLI") or shutil.which("arduino-cli")
    if not cli:
        print("arduino-cli was not found. Install it and the core with:\n"
              f"  arduino-cli core install {CORE}\nthen rerun, or set ARDUINO_CLI.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="picasso-firmware-") as temporary:
        sketch = Path(temporary) / "WallDrawingMachine"
        shutil.copytree(SKETCH, sketch, ignore=shutil.ignore_patterns("machine_config.h"))
        identity = write_config(profile, kind, sketch / "machine_config.h")
        command = [cli, "compile", "--fqbn", fqbn, "--libraries", str(LIBRARIES), "--warnings", "all"]
        if sys.platform.startswith("linux"):
            shims = Path(temporary) / "shims"
            shutil.copytree(SHIMS, shims)
            command += ["--build-property", f"compiler.cpp.extra_flags=-I{shims}"]
        print(f"Compiling {profile.id} ({kind}) configuration {identity} for {fqbn}. No upload is performed.")
        return subprocess.run(command + [str(sketch)]).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("config", "build"):
        sub = commands.add_parser(name)
        source = sub.add_mutually_exclusive_group(required=True)
        source.add_argument("--profile", help="saved measured profile id (see the studio's machine dialog)")
        source.add_argument("--reference", help="bundled source reference id; builds without a workspace")
        if name == "build":  # compiled in a temporary copy, so it can never land in the sketch folder
            source.add_argument("--fixture", action="store_true", help="synthetic workspace for compile checks only")
        sub.add_argument("--data-dir", help="application data directory (default: data/ or PICASSO_DATA_DIR)")
    commands.choices["config"].add_argument("--output", type=Path, default=SKETCH / "machine_config.h")
    commands.choices["build"].add_argument("--fqbn", default=DEFAULT_FQBN,
                                           help="exact board identifier; UNO is a reference build, not the confirmed board")
    commands.add_parser("host-test")
    args = parser.parse_args(argv)

    if args.command == "host-test":
        with tempfile.TemporaryDirectory(prefix="picasso-host-") as temporary:
            config = Path(temporary) / "machine_config.h"
            write_config(host_test_profile(), "synthetic host-test", config)
            binaries = host_build(Path(temporary), config)
            result = subprocess.run([str(binaries["core_tests"])])
            if result.returncode == 0:
                smoke = subprocess.run([str(binaries["simulator"])], input="boot\nkey enter\nwait 200\nreport\n",
                                       capture_output=True, text=True)
                print(f"Simulator smoke test exit {smoke.returncode}: {smoke.stdout.strip()[:160]}...")
                return smoke.returncode
            return result.returncode

    if getattr(args, "fixture", False):
        profile, kind = host_test_profile(), "synthetic compile-check (NOT FOR UPLOAD)"
    else:
        profile, kind = load_profile(args.profile, args.reference, args.data_dir)
    if args.command == "config":
        identity = write_config(profile, kind, args.output)
        print(f"Wrote {args.output} for {profile.id} ({kind}); configuration ID {identity}.")
        print("Build and upload it explicitly, then compare the ID on the machine's Info screen. Generation does not verify hardware.")
        return 0
    return arduino_build(args.fqbn, profile, kind)


if __name__ == "__main__":
    raise SystemExit(main())
