import json
from pathlib import Path

from .models import MachineProfile


def load_reference_profiles(root: Path) -> list[MachineProfile]:
    paths = sorted((root / "config" / "machine-profiles").glob("*.json"))
    if len(paths) != 2:
        raise RuntimeError("Expected both unverified reference profiles in config/machine-profiles")
    return [MachineProfile.model_validate(json.loads(path.read_text(encoding="utf-8"))) for path in paths]
