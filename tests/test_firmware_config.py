"""Profile-generated firmware configuration and firmware/profile reconciliation."""

import importlib.util
from pathlib import Path
import re
import zlib

import pytest

from backend.app import firmware
from backend.app.drawing.errors import DrawingError
from backend.app.main import create_app
from backend.app.models import CalibrationInput, CalibrationSaveRequest
from backend.app.profiles import load_reference_profiles
from backend.app.storage.preparation import ProfileManager
from backend.app.storage.repository import Repository
from test_phase4_api import connect
from test_phase4_storage import calibration

ROOT = Path(__file__).resolve().parents[1]


def canonical(**changes):
    return calibration(**{"firmware": "picasso-canonical", "separation_mm": 362.5, "anchor_y_mm": 243, "verified": False, **changes})


def defines(header):
    return dict(re.findall(r"^#define (\w+) (.+)$", header, re.M))


def test_measured_header_compiles_exact_values_and_id_ignores_attestations():
    profile = canonical(firmware_matches_measurements=False)
    values = defines(firmware.render(profile, kind="unverified measured"))
    assert values["PICASSO_SEPARATION_MM"] == "(362.5f)" and values["PICASSO_ANCHOR_Y_MM"] == "(243.0f)"
    assert values["PICASSO_STEPS_PER_TURN"] == "2048L" and values["PICASSO_PEN_DOWN_DEGREES"] == "70"
    assert values["PICASSO_HAS_REGION"] == "1" and values["PICASSO_REGION_MIN_X_MM"] == "(-150.0f)"
    assert values["PICASSO_REGION_MARGIN_MM"] == "(5.0f)" and values["PICASSO_ROPE_MAX_MM"] == "(600.0f)"
    identity = firmware.config_id(profile)
    assert re.fullmatch(r"[0-9a-f]{16}", identity) and values["PICASSO_CONFIG_ID"] == f'"{identity}"'
    same = canonical(label="renamed", measurement_notes="Different notes, same calibration values.")
    assert firmware.config_id(same) == identity
    assert firmware.config_id(canonical(rope_min_mm=101)) != identity
    region = dict(min_x_mm=-150, max_x_mm=150, min_y_mm=-100, max_y_mm=150, margin_mm=6)
    assert firmware.config_id(canonical(allowed_region=region)) != identity


def test_reference_header_has_no_workspace_and_origin_outside_region_is_refused():
    reference = {profile.id: profile for profile in load_reference_profiles(ROOT)}["reference-400"]
    values = defines(firmware.render(reference, kind="source reference"))
    assert values["PICASSO_HAS_REGION"] == "0" and values["PICASSO_SEPARATION_MM"] == "(400.0f)"
    assert "PICASSO_REGION_MIN_X_MM" not in values
    outside = calibration(verified=False, allowed_region=dict(min_x_mm=10, max_x_mm=150, min_y_mm=-100, max_y_mm=150, margin_mm=5))
    with pytest.raises(DrawingError, match="origin"):
        firmware.render(outside, kind="unverified measured")


def test_canonical_firmware_reconciles_measurements_that_differ_from_both_references(tmp_path):
    manager = ProfileManager(Repository(tmp_path), load_reference_profiles(ROOT))
    with pytest.raises(DrawingError) as legacy:
        manager.save(CalibrationSaveRequest(calibration=calibration(separation_mm=362.5)))
    assert legacy.value.code == "FIRMWARE_PROFILE_MISMATCH"
    draft = manager.save(CalibrationSaveRequest(calibration=canonical()))
    identity = firmware.config_id(draft)
    with pytest.raises(DrawingError) as wrong:
        manager.save(CalibrationSaveRequest(calibration=canonical(firmware_config_id="0" * 16, verified=True), expected_revision=draft.revision), draft.id)
    assert wrong.value.code == "FIRMWARE_CONFIG_MISMATCH"
    verified = manager.save(CalibrationSaveRequest(calibration=canonical(firmware_config_id=identity, verified=True), expected_revision=draft.revision), draft.id)
    assert verified.verified and verified.version == 2 and firmware.config_id(verified) == identity
    # Editing a compiled value invalidates the recorded ID until firmware is rebuilt.
    with pytest.raises(DrawingError, match="does not match"):
        manager.save(CalibrationSaveRequest(calibration=canonical(firmware_config_id=identity, verified=True, rope_max_mm=590), expected_revision=verified.revision), draft.id)
    with pytest.raises(ValueError, match="configuration ID shown"):
        canonical(verified=True)
    with pytest.raises(ValueError, match="only to canonical"):
        calibration(firmware_config_id=identity)


def test_api_lists_ids_downloads_headers_and_prepares_crc(tmp_path):
    with connect(create_app(frontend_dir=tmp_path)) as client:
        assert client.get("/api/health").json()["phase"] == 5
        assert client.get("/api/capabilities").json()["firmware"]["available"] is True
        saved = client.post("/api/profiles", json={"calibration": canonical().model_dump(), "select_for_preparation": True}).json()
        profiles = client.get("/api/profiles").json()
        ids = profiles["firmware"]["config_ids"]
        assert profiles["firmware"]["version"] == firmware.FIRMWARE_VERSION
        assert set(ids) == {"reference-350", "reference-400", saved["id"]}
        download = client.get(f"/api/profiles/{saved['id']}/firmware-config")
        assert download.status_code == 200 and download.headers["x-picasso-firmware-config-id"] == ids[saved["id"]]
        assert download.headers["x-picasso-hardware-verified"] == "false"
        assert 'filename="machine_config.h"' in download.headers["content-disposition"]
        assert f'#define PICASSO_CONFIG_ID "{ids[saved["id"]]}"' in download.text
        assert "PICASSO_HAS_REGION 0" in client.get("/api/profiles/reference-350/firmware-config").text
        assert client.get("/api/profiles/missing/firmware-config").json()["code"] == "PROFILE_NOT_FOUND"
        values = {key: value for key, value in saved.items() if key in CalibrationInput.model_fields}
        verified = client.put(f"/api/profiles/{saved['id']}", json={"calibration": {**values, "verified": True, "firmware_config_id": ids[saved["id"]],
                                                                                   "firmware_matches_measurements": True, "pen_lift_and_holding_tested": True,
                                                                                   "workspace_tested": True}, "expected_revision": saved["revision"],
                                                                    "select_for_preparation": True}).json()
        assert verified["verified"] is True
        draft = client.post("/api/drawings/generate", json={"prompt": "Draw a circle diameter 40"}).json()
        job = client.post("/api/jobs/prepare", json={"revision_id": draft["revision_id"], "profile_id": verified["id"], "profile_revision": verified["revision"]}).json()
        assert job["gcode_crc32"] == f"{zlib.crc32(draft['gcode'].encode()):08x}"
        assert any(job["gcode_crc32"] in warning for warning in job["warnings"])


def test_config_command_writes_header_and_build_reports_missing_cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("picasso_firmware_cli", ROOT / "scripts" / "firmware.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    target = tmp_path / "machine_config.h"
    assert script.main(["config", "--reference", "reference-350", "--output", str(target)]) == 0
    assert defines(target.read_text())["PICASSO_SEPARATION_MM"] == "(350.0f)"
    monkeypatch.delenv("ARDUINO_CLI", raising=False)
    monkeypatch.setattr(script.shutil, "which", lambda name: None)
    assert script.main(["build", "--reference", "reference-350"]) == 2
