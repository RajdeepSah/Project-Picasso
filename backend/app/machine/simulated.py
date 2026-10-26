"""Optional simulated device: the real firmware sketch in the host simulator.

Enabled only with PICASSO_SIMULATED_DEVICE=1 (tests, demonstrations). It is
labelled as a simulation everywhere and needs a host C++ compiler. The
simulator's keypad script confirms the origin, standing in for the operator.
"""

import hashlib
import importlib.util
import os
from pathlib import Path
import secrets
import threading

from .transport import ProcessTransport

ROOT = Path(__file__).resolve().parents[3]
SET_ORIGIN = "key down\nkey enter\nkey enter\nkey enter\nuntil main 3000\n"
_lock = threading.Lock()


def _script():
    spec = importlib.util.spec_from_file_location("picasso_firmware_script", ROOT / "scripts" / "firmware.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def simulator_profile():
    """The synthetic profile compiled into the simulated firmware."""
    return _script().host_test_profile()


def build_simulator(cache: Path) -> Path:
    script = _script()
    sources = sorted([*(ROOT / "firmware").rglob("*.cpp"), *(ROOT / "firmware").rglob("*.h"), *(ROOT / "firmware").rglob("*.ino")])
    digest = hashlib.sha256(b"".join(path.read_bytes() for path in sources)).hexdigest()[:16]
    folder = cache / f"simulator-{digest}"
    with _lock:
        if not (folder / "simulator").is_file():
            folder.mkdir(parents=True, exist_ok=True)
            config = folder / "machine_config.h"
            script.write_config(script.host_test_profile(), "synthetic host-simulation", config)
            script.host_build(folder, config)
    return folder / "simulator"


def simulated_transport(cache: Path) -> ProcessTransport:
    binary = build_simulator(cache)
    # Above ~5x, the 0.5 s host poll exceeds the firmware's 3 s simulated watchdog.
    speed = float(os.environ.get("PICASSO_SIMULATED_SPEED", "3"))
    report = cache / "last-simulated-run.json"
    # A fresh process has erased EEPROM; seed the counter so every simulated
    # power-up gets a distinct boot ID, as real resets do.
    prelude = f"boot_counter {secrets.randbelow(2**31)}\nboot\n{SET_ORIGIN}bridge {speed} {report}\n".encode()
    return ProcessTransport([str(binary)], prelude, f"simulated firmware ×{speed:g}")
