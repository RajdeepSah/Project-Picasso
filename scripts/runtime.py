"""Shared local paths and prerequisites for setup and launch."""

from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def prerequisites(*, node: bool = True):
    if sys.version_info < (3, 12):
        raise RuntimeError("Python 3.12 or newer is required. Install it and rerun setup.")
    if node:
        if not shutil.which("node") or not shutil.which("npm"):
            raise RuntimeError("Node.js 22.12+ and npm are required for setup/development.")
        version = subprocess.check_output(["node", "--version"], text=True).strip().lstrip("v")
        if tuple(int(part) for part in version.split(".")[:2]) < (22, 12):
            raise RuntimeError(f"Node.js 22.12+ is required; found {version}.")


def npm_command(*args: str) -> list[str]:
    return [shutil.which("npm") or "npm", *args]
