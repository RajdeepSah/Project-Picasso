"""Every API/launcher test gets isolated application data and SD mirror paths.
Firmware host builds are shared by the firmware test modules."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("picasso_firmware_script", ROOT / "scripts" / "firmware.py")
firmware_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(firmware_script)


@pytest.fixture(scope="session")
def profile():
    return firmware_script.host_test_profile()


@pytest.fixture(scope="session")
def build(tmp_path_factory, profile):
    out = tmp_path_factory.mktemp("firmware-host")
    config = out / "machine_config.h"
    firmware_script.write_config(profile, "synthetic host-test", config)
    return firmware_script.host_build(out, config)


@pytest.fixture(autouse=True)
def isolated_app_storage(tmp_path, monkeypatch):
    monkeypatch.setenv('PICASSO_DATA_DIR', str(tmp_path / 'app-data'))
    mirror = tmp_path / 'sd-mirror'
    mirror.mkdir()
    (mirror / 'main.nc').write_bytes(b'original test mirror\n')
    monkeypatch.setenv('PICASSO_MIRROR_DIR', str(mirror))
