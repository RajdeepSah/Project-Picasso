#!/usr/bin/env python3
"""Install locked project dependencies and build the studio; never touches hardware."""

import argparse
import subprocess
import sys

from runtime import FRONTEND, PYTHON, ROOT, VENV, npm_command, prerequisites


def run(command: list[str], *, frontend: bool = False):
    subprocess.run(command, cwd=FRONTEND if frontend else ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-install", action="store_true", help="Rebuild using dependencies already installed locally.")
    args = parser.parse_args()
    try:
        prerequisites()
        if not args.skip_install:
            if not PYTHON.is_file():
                print("Creating project virtual environment…", flush=True)
                run([sys.executable, "-m", "venv", str(VENV)])
            print("Installing locked Python dependencies…", flush=True)
            run([str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check",
                 "--index-url", "https://pypi.org/simple", "--cache-dir", str(ROOT / ".cache" / "pip"),
                 "-r", str(ROOT / "backend" / "requirements.lock")])
            print("Installing locked frontend dependencies…", flush=True)
            run(npm_command("ci", "--no-audit", "--no-fund", "--cache", str(ROOT / ".cache" / "npm")), frontend=True)
        if not PYTHON.is_file():
            raise RuntimeError("No project virtual environment. Rerun without --skip-install.")
        print("Generating shared contracts…", flush=True)
        run(npm_command("run", "contracts"), frontend=True)
        print("Building the studio…", flush=True)
        run(npm_command("run", "build"), frontend=True)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"\nSetup failed: {exc}\nFix the reported issue, then run python3 scripts/setup.py again.", file=sys.stderr)
        return 1
    print("\nStudio ready. Start it with: python3 scripts/picasso.py", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
