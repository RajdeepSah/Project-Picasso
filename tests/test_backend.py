from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from backend.app.main import create_app
from backend.app.models import DrawingSpec, MachineProfile, PolylineDrawing


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(frontend_dir=tmp_path, instance_id="test-instance"), base_url="http://127.0.0.1") as session:
        session.headers['X-Picasso-Token'] = session.get('/api/session').json()['write_token']
        yield session


def test_real_capabilities_and_independent_uninspected_hardware_states(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["application"] == "project-picasso"
    assert health.json()["instance_id"] == "test-instance"
    assert health.json()["frontend_ready"] is False
    assert health.headers["cache-control"] == "no-store"
    caps = client.get("/api/capabilities").json()
    assert caps["dashboard"]["available"] is True
    assert caps["generation"]["available"] is True
    assert caps["gcode_export"]["available"] is True
    assert caps["history"]["available"] is True
    assert caps["sd_export"]["available"] is True
    for name in ("serial_control", "ai", "voice"):
        assert caps[name]["available"] is False
        assert caps[name]["reason"]
    status = client.get("/api/status").json()
    assert status["machine"]["discovery_performed"] is False
    assert status["machine"]["position_known"] is False
    assert status["storage"]["state"] == "not_configured"
    assert isinstance(status["storage"]["discovery_performed"], bool)


def test_profiles_cannot_authorize_motion(client):
    response = client.get("/api/profiles").json()
    assert response["active_profile_id"] is None
    assert {profile["separation_mm"] for profile in response["profiles"]} == {350, 400}
    for profile in response["profiles"]:
        assert profile["verified"] is False
        assert profile["allowed_region"] is None
        assert profile["board"] is None
        with pytest.raises(ValidationError):
            MachineProfile.model_validate({**profile, "verified": True})


def test_generation_returns_real_draft_and_checks_input(client):
    response = client.post("/api/drawings/generate", json={"prompt": "Draw a circle"})
    assert response.status_code == 200
    assert response.json()["title"] == "Circle"
    assert response.json()["execution_ready"] is False
    for payload in ({"prompt": ""}, {"prompt": " "}, {"prompt": "x" * 2001}, {"prompt": "ok", "execute": True}):
        assert client.post("/api/drawings/generate", json=payload).status_code == 422
    assert client.post("/api/machine/start").status_code == 404


def test_local_origin_host_and_file_boundaries(client):
    assert client.get("/api/health", headers={"Host": "untrusted.example"}).status_code == 400
    assert client.post("/api/drawings/generate", headers={"Origin": "https://untrusted.example"}, json={"prompt": "circle"}).status_code == 403
    assert client.post("/api/drawings/generate", headers={"Origin": "http://127.0.0.1"}, json={"prompt": "circle"}).status_code == 200
    assert client.get("/SdCard/main.nc").status_code == 404
    assert client.get("/backend/requirements.lock").status_code == 404
    assert client.get("/").status_code == 503


def test_built_frontend_is_served_without_hiding_unknown_api_routes(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>Picasso studio</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log('studio')")
    with TestClient(create_app(frontend_dir=tmp_path), base_url="http://localhost") as client:
        assert "Picasso studio" in client.get("/").text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/health").json()["frontend_ready"] is True
        assert client.get("/api/not-a-route").status_code == 404


def test_missing_reference_configuration_fails_startup(monkeypatch, tmp_path):
    def broken(root: Path):
        raise RuntimeError("Missing source profiles")
    monkeypatch.setattr("backend.app.main.load_reference_profiles", broken)
    with pytest.raises(RuntimeError, match="Missing source profiles"):
        with TestClient(create_app(frontend_dir=tmp_path), base_url="http://localhost"):
            pass


def test_drawing_contracts_reject_bad_units_numbers_and_parameters():
    data = {"generator": "circle", "dimensions": {"width_mm": 100, "height_mm": 100}}
    assert DrawingSpec.model_validate(data).dimensions.width_mm == 100
    for width in (float("nan"), float("inf"), -1, 0, 2001):
        with pytest.raises(ValidationError):
            DrawingSpec.model_validate({**data, "dimensions": {"width_mm": width, "height_mm": 100}})
    with pytest.raises(ValidationError):
        DrawingSpec.model_validate({**data, "parameters": {"petals": 12}})
    with pytest.raises(ValidationError):
        DrawingSpec.model_validate({**data, "parameters": {"shell": "run something"}})
    with pytest.raises(ValidationError):
        PolylineDrawing.model_validate({"source": data, "units": "inches", "strokes": [{"points": [[0, 0], [1, 1]]}]})
    with pytest.raises(ValidationError):
        PolylineDrawing.model_validate({"source": data, "strokes": [{"points": [[0, 0], [float("inf"), 1]]}]})
