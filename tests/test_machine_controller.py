"""Host USB controller against a fake protocol device: handshake, preconditions,
acknowledged streaming, priority stop and fault handling without resending motion."""

import threading
import time

import pytest

from backend.app import firmware
from backend.app.drawing.errors import DrawingError
from backend.app.machine import protocol
from backend.app.models import PreparationRequest, UsbStartRequest
from backend.app.storage.repository import Repository
from machine_fakes import FakeDevice, FastController, machine_system

TERMINAL = {"completed", "aborted", "failed", "fault", "interrupted"}


@pytest.fixture
def rig(tmp_path):
    repo, profiles, jobs, profile, job = machine_system(tmp_path)
    device = FakeDevice(profile.firmware_config_id)
    controller = FastController(repo, jobs, profiles, device.transport)
    yield controller, device, job, repo, jobs, profile
    controller.disconnect()


def start_request(state, **changes):
    values = dict(expected_boot_id=state.status.boot_id, expected_origin_revision=state.status.origin_revision,
                  expected_config_id=state.hello.config_id, area_clear_confirmed=True)
    values.update(changes)
    return UsbStartRequest(**values)


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def finish(controller, timeout=20):
    assert wait_for(lambda: controller.state().run.state in TERMINAL, timeout)
    return controller.state().run


def motions(device):
    return [body for body in device.bodies("M ")]


def test_handshake_sends_only_read_only_frames(rig):
    controller, device, *_ = rig
    state = controller.connect("fake0")
    assert state.connection == "connected" and state.hello.config_id == device.config_id and state.status.state == "IDLE"
    assert state.status.position_source == "commanded"
    assert {body.split()[0] for body in device.bodies()} <= {"HELLO", "STATUS"}


def test_a_non_picasso_device_only_ever_receives_hello(rig):
    controller, device, *_ = rig
    device.answer_hello = False
    with pytest.raises(DrawingError) as error:
        controller.connect("fake0")
    assert error.value.code == "NO_HANDSHAKE" and controller.state().connection == "disconnected"
    assert device.bodies() == ["HELLO 1"] * 3


def test_protocol_version_mismatch_is_incompatible(rig):
    controller, device, *_ = rig
    device.hello_protocol = 2
    with pytest.raises(DrawingError) as error:
        controller.connect("fake0")
    assert error.value.code == "INCOMPATIBLE_FIRMWARE" and controller.state().connection == "incompatible"
    assert not motions(device)


def test_start_refuses_every_unmet_precondition_without_sending_begin(rig, tmp_path):
    controller, device, job, repo, jobs, profile = rig
    state = controller.connect("fake0")
    cases = [
        (dict(area_clear_confirmed=False), "CONFIRMATION_REQUIRED"),
        (dict(expected_boot_id="00000001"), "STALE_SESSION"),
        (dict(expected_origin_revision=7), "STALE_SESSION"),
        (dict(expected_config_id="0" * 16), "CONFIG_MISMATCH"),
    ]
    for changes, code in cases:
        with pytest.raises(DrawingError) as error:
            controller.start(job.id, start_request(state, **changes))
        assert error.value.code == code
    device.x = 5.0
    with pytest.raises(DrawingError, match="Go to origin") as error:
        controller.start(job.id, start_request(state))
    assert error.value.code == "POSITION_MISMATCH"
    device.x, device.origin = 0.0, "UNSET"
    with pytest.raises(DrawingError) as error:
        controller.start(job.id, start_request(state))
    assert error.value.code == "ORIGIN_REQUIRED"
    device.origin, device.state = "FRESH", "LOCAL"  # e.g. SD validation on the keypad
    with pytest.raises(DrawingError) as error:
        controller.start(job.id, start_request(state))
    assert error.value.code == "MACHINE_BUSY"
    device.state = "IDLE"
    simulation = jobs.prepare(PreparationRequest(revision_id=job.revision_id, mode="simulation"))
    with pytest.raises(DrawingError) as error:
        controller.start(simulation.id, start_request(state))
    assert error.value.code == "SIMULATION_JOB"
    device.config_id = "f" * 16
    controller.disconnect()
    state = controller.connect("fake0")
    with pytest.raises(DrawingError) as error:
        controller.start(job.id, start_request(state))
    assert error.value.code == "CONFIG_MISMATCH"
    assert not device.bodies("BEGIN") and not motions(device)


def test_legacy_firmware_profiles_cannot_stream(tmp_path):
    repo, profiles, jobs, profile, job = machine_system(tmp_path, firmware="legacy-reference", firmware_config_id=None)
    device = FakeDevice(firmware.config_id(profile))
    controller = FastController(repo, jobs, profiles, device.transport)
    state = controller.connect("fake0")
    with pytest.raises(DrawingError) as error:
        controller.start(job.id, start_request(state))
    assert error.value.code == "FIRMWARE_REQUIRED"
    controller.disconnect()


def test_streams_each_command_once_in_order_and_completes(rig):
    controller, device, job, repo, *_ = rig
    state = controller.connect("fake0")
    run = controller.start(job.id, start_request(state))
    assert run.state == "streaming" and run.boot_id == "0000002a" and run.measured_feedback is False
    run = finish(controller)
    lines = job.gcode.splitlines()
    assert run.state == "completed" and run.acknowledged_seq == len(lines)
    assert motions(device) == [f"M {seq} {line}" for seq, line in enumerate(lines, start=1)]
    assert all(count == 1 for count in device.executions.values())
    assert device.bodies("END") == [f"END {run.token}"]
    assert repo.runs(1)[0]["state"] == "completed"


def test_stop_is_sent_while_an_ack_is_held_and_status_stays_responsive(rig):
    controller, device, job, *_ = rig
    device.hold_ack[3] = threading.Event()
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    assert wait_for(lambda: device.in_flight == 3)
    started = time.monotonic()
    snapshot = controller.state()
    assert time.monotonic() - started < 0.1 and snapshot.run.acknowledged_seq == 2
    controller.stop()
    run = finish(controller)
    stop_at = next(at for at, body in device.received if body == "STOP")
    assert run.state == "aborted" and "HOST_STOP" in run.message and run.acknowledged_seq == 2
    assert not [body for at, body in device.received if at > stop_at and body.startswith("M ")]
    assert device.executions == {1: 1, 2: 1, 3: 1}


def test_a_lost_ack_is_recovered_from_status_without_resending(rig):
    controller, device, job, *_ = rig
    device.drop_ack = {2}
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    run = finish(controller)
    assert run.state == "completed"
    assert motions(device).count(f"M 2 {job.gcode.splitlines()[1]}") == 1


def test_a_lost_receipt_does_not_cause_a_resend(rig):
    controller, device, job, *_ = rig
    device.drop_rcv = {2}
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    assert finish(controller).state == "completed"
    assert sum(body.startswith("M 2 ") for body in motions(device)) == 1


def test_a_rejected_frame_is_retransmitted_only_after_status_proves_it_was_not_received(rig):
    controller, device, job, *_ = rig
    device.corrupt_once = {3}
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    assert finish(controller).state == "completed"
    assert sum(body.startswith("M 3 ") for body in motions(device)) == 2
    assert device.executions[3] == 1
    statuses = [at for at, body in device.received if body == "STATUS"]
    first, second = [at for at, body in device.received if body.startswith("M 3 ")]
    assert any(first < at < second for at in statuses)


def test_silence_during_motion_faults_and_never_resends(rig):
    controller, device, job, repo, *_ = rig
    device.silent_at = 3
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    run = finish(controller)
    assert run.state == "fault" and "unknown" in run.message.lower()
    assert [body.split()[1] for body in motions(device)] == ["1", "2", "3"]
    assert wait_for(lambda: controller.state().connection == "lost")
    assert "STOP" in device.bodies("STOP")


def test_device_reset_mid_run_faults_and_requires_a_new_session(rig):
    controller, device, job, *_ = rig
    device.reset_at = 3
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    run = finish(controller)
    assert run.state == "fault" and "reset" in run.message
    assert wait_for(lambda: "new boot ID" in controller.state().message)
    with pytest.raises(DrawingError) as error:
        controller.start(job.id, start_request(state))
    assert error.value.code in ("SESSION_CHANGED", "STALE_SESSION", "ORIGIN_REQUIRED")
    assert max(int(body.split()[1]) for body in motions(device)) == 3


def test_unplugging_marks_the_run_fault_and_the_connection_lost(rig):
    controller, device, job, *_ = rig
    device.hold_ack[2] = threading.Event()
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    assert wait_for(lambda: device.in_flight == 2)
    device.closed = True
    run = finish(controller)
    assert run.state == "fault" and controller.state().connection == "lost"
    with pytest.raises(DrawingError):
        controller.start(job.id, start_request(state))


def test_duplicate_acks_and_corrupted_replies_are_ignored(rig):
    controller, device, job, *_ = rig
    device.duplicate_ack = {1, 2}
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    assert finish(controller).state == "completed"
    assert controller.frame_errors >= 2
    assert all(count == 1 for count in device.executions.values())


def test_pause_resume_and_concurrency_rules(rig):
    controller, device, job, *_ = rig
    device.hold_ack[2] = threading.Event()
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    assert wait_for(lambda: device.in_flight == 2)
    with pytest.raises(DrawingError) as error:
        controller.start(job.id, start_request(state))
    assert error.value.code == "RUN_ACTIVE"
    with pytest.raises(DrawingError):
        controller.resume()
    controller.pause()
    assert wait_for(lambda: controller.state().run.state == "paused")
    device.hold_ack[2].set()
    time.sleep(0.5)  # paused: the held command must not be acknowledged or followed
    assert controller.state().run.acknowledged_seq == 1 and len(motions(device)) == 2
    controller.resume()
    assert finish(controller).state == "completed"


def test_home_is_explicit_and_bound_to_the_session(rig):
    controller, device, job, *_ = rig
    state = controller.connect("fake0")
    request = dict(expected_boot_id=state.status.boot_id, expected_origin_revision=state.status.origin_revision)
    from backend.app.models import HomeRequest
    with pytest.raises(DrawingError):
        controller.home(HomeRequest(**request))
    with pytest.raises(DrawingError) as error:
        controller.home(HomeRequest(**{**request, "expected_origin_revision": 9}, route_confirmed=True))
    assert error.value.code == "STALE_SESSION"
    device.x = 12.0
    controller.home(HomeRequest(**request, route_confirmed=True))
    assert device.bodies("HOME") == [f"HOME {state.status.boot_id} {state.status.origin_revision}"] and device.x == 0


def test_restart_marks_an_active_run_interrupted(rig, tmp_path):
    controller, device, job, repo, *_ = rig
    device.hold_ack[2] = threading.Event()
    state = controller.connect("fake0")
    controller.start(job.id, start_request(state))
    assert wait_for(lambda: device.in_flight == 2)
    reopened = Repository(repo.root)  # as if the application had crashed and restarted
    assert reopened.runs(1)[0]["state"] == "interrupted"
    assert "USB run" in " ".join(reopened.recovery_notices)


def test_frame_codec_limits():
    assert protocol.crc(b"123456789") == "29B1"
    frame = protocol.encode("STATUS")
    assert protocol.decode(frame) == ["STATUS"] and protocol.decode(b"PICASSO log\n") is None
    with pytest.raises(ValueError):
        protocol.encode("X" * 91)
    with pytest.raises(ValueError):
        protocol.encode("M 1 G0*Z5")
    with pytest.raises(ValueError):
        protocol.motion(1, "G0 X1.000 Y1.000 Z5" + " " * 50)
    for bad, code in [(b"@ST*0000\n", "CRC"), (b"@ST\n", "FORMAT"), (b"@" + b"X" * 121 + b"*0000\n", "LONG"), (b"@\xffST*0000\n", "BYTE")]:
        with pytest.raises(protocol.FrameError, match=code):
            protocol.decode(bad)
