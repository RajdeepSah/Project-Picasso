"""HTTP surface of USB control with an injected fake device."""

import threading
import time

from backend.app.main import create_app
from machine_fakes import FakeDevice, canonical_calibration
from test_phase4_api import connect


def test_usb_control_endpoints_and_status_while_an_ack_is_pending(tmp_path):
    device = FakeDevice(canonical_calibration().firmware_config_id)
    device.hold_ack[3] = threading.Event()
    with connect(create_app(frontend_dir=tmp_path, machine_transport=device.transport)) as client:
        assert client.get("/api/capabilities").json()["serial_control"]["available"] is True
        assert client.get("/api/machine").json()["connection"] == "disconnected"
        profile = client.post("/api/profiles", json={"calibration": canonical_calibration().model_dump(), "select_for_preparation": True}).json()
        draft = client.post("/api/drawings/generate", json={"prompt": "Draw a rectangle 30 x 20 mm"}).json()
        job = client.post("/api/jobs/prepare", json={"revision_id": draft["revision_id"], "profile_id": profile["id"], "profile_revision": profile["revision"]}).json()
        state = client.post("/api/machine/connect", json={"port": "fake0"}).json()
        assert state["connection"] == "connected" and state["status"]["position_source"] == "commanded"
        assert client.get("/api/status").json()["machine"]["state"] == "connected"
        request = {"expected_boot_id": state["status"]["boot_id"], "expected_origin_revision": state["status"]["origin_revision"],
                   "expected_config_id": state["hello"]["config_id"], "area_clear_confirmed": True}
        assert client.post(f"/api/jobs/{job['id']}/usb-start", json={**request, "area_clear_confirmed": False}).json()["code"] == "CONFIRMATION_REQUIRED"
        run = client.post(f"/api/jobs/{job['id']}/usb-start", json=request).json()
        assert run["state"] == "streaming" and run["measured_feedback"] is False
        deadline = time.monotonic() + 5
        while device.in_flight != 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        started = time.monotonic()
        snapshot = client.get("/api/machine").json()
        assert time.monotonic() - started < 0.5 and snapshot["run"]["acknowledged_seq"] == 2
        assert client.post("/api/machine/stop").json()["run"]["state"] in ("stopping", "aborted")
        while client.get("/api/machine").json()["run"]["state"] != "aborted" and time.monotonic() < deadline + 5:
            time.sleep(0.02)
        assert client.get("/api/machine").json()["recent_runs"][0]["state"] == "aborted"
        assert client.post("/api/machine/resume").json()["code"] == "RUN_STATE"
        assert client.post("/api/machine/disconnect").json()["connection"] == "disconnected"


def test_only_listed_ports_can_be_opened(tmp_path):
    with connect(create_app(frontend_dir=tmp_path, simulated_device=False)) as client:
        ports = client.get("/api/machine/ports").json()
        assert all(not port["simulated"] for port in ports["ports"])
        refused = client.post("/api/machine/connect", json={"port": "/etc/passwd"})
        assert refused.status_code == 404 and refused.json()["code"] == "PORT_NOT_LISTED"
        assert client.post("/api/machine/stop").json()["code"] == "NOT_CONNECTED"


def test_ports_report_access_without_opening_and_permission_errors_explain_the_fix(tmp_path, monkeypatch):
    import errno
    import os
    from types import SimpleNamespace

    import pytest
    import serial
    from serial.tools import list_ports as serial_ports

    from backend.app.machine import transport

    denied = tmp_path / "ttyUSB9"
    denied.write_bytes(b"")
    denied.chmod(0)
    if os.access(denied, os.R_OK):
        pytest.skip("permission bits are not enforced for this user (root)")
    listed = [SimpleNamespace(device=str(denied), description="USB Serial", hwid="USB VID:PID=1A86:7523", vid=0x1A86)]
    monkeypatch.setattr(serial_ports, "comports", lambda: listed)
    monkeypatch.setattr(serial, "Serial", lambda *args, **kwargs: pytest.fail("listing must never open a port"))
    with connect(create_app(frontend_dir=tmp_path, simulated_device=True)) as client:
        ports = client.get("/api/machine/ports").json()["ports"]
    assert [(port["likely_arduino"], port["accessible"]) for port in ports] == [(True, False), (False, True)]

    def refuse(*args, **kwargs):
        raise serial.SerialException(errno.EACCES, f"could not open port {denied}: [Errno 13] Permission denied")
    monkeypatch.setattr(serial, "Serial", refuse)
    with pytest.raises(transport.TransportClosed, match="usermod -aG dialout"):
        transport.SerialTransport(str(denied))
