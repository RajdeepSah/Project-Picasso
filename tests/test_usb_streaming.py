"""Host controller <-> simulated firmware (real sketch, simulator bridge) end to end.
Simulated time runs at 4x wall time; host polling is scaled so the firmware's
3 s watchdog sees a live host. Not hardware evidence."""

import json
import shutil
import time

import pytest

from backend.app import firmware
from backend.app.machine.controller import MachineController
from backend.app.machine.transport import ProcessTransport
from backend.app.models import CalibrationInput, CalibrationSaveRequest, GenerateRequest, HomeRequest, PreparationRequest, UsbStartRequest
from backend.app.drawing.service import DraftService
from backend.app.profiles import load_reference_profiles
from backend.app.storage.preparation import JobManager, ProfileManager
from backend.app.storage.repository import Repository
from threading import Event

pytestmark = pytest.mark.skipif(shutil.which("g++") is None and shutil.which("c++") is None, reason="host C++ compiler unavailable")

SET_ORIGIN = "key enter\nkey enter\nkey enter\nuntil main 3000\n"  # USB-only main menu: Setup first
TERMINAL = {"completed", "aborted", "failed", "fault", "interrupted"}
SPEED = 4


class BridgeController(MachineController):
    POLL_INTERVAL = 0.25  # 1 s of simulated time between polls


class Bench:
    def __init__(self, build, profile, tmp_path):
        self.repo = Repository(tmp_path / "data")
        self.profiles = ProfileManager(self.repo, load_reference_profiles(firmware_root()))
        values = {key: value for key, value in profile.model_dump().items() if key in CalibrationInput.model_fields}
        values.update(firmware="picasso-canonical", firmware_config_id=firmware.config_id(profile), verified=True,
                      firmware_matches_measurements=True, pen_lift_and_holding_tested=True, workspace_tested=True)
        self.profile = self.profiles.save(CalibrationSaveRequest(calibration=CalibrationInput(**values), select_for_preparation=True))
        self.drafts = DraftService(repository=self.repo)
        self.jobs = JobManager(self.repo, self.drafts, self.profiles)
        self.report = tmp_path / "simulator-report.json"
        self.transports = []
        prelude = f"boot_counter 99\nboot\n{SET_ORIGIN}bridge {SPEED} {self.report}\n".encode()

        def open_port(port):
            transport = ProcessTransport([str(build["simulator"])], prelude, "test simulator")
            self.transports.append(transport)
            return transport
        self.controller = BridgeController(self.repo, self.jobs, self.profiles, open_port, simulated=True)

    def job(self, prompt):
        draft = self.drafts.generate(GenerateRequest(prompt=prompt), Event())
        return draft, self.jobs.prepare(PreparationRequest(revision_id=draft.revision_id, profile_id=self.profile.id, profile_revision=self.profile.revision))

    def start(self, job):
        state = self.controller.state()
        return self.controller.start(job.id, UsbStartRequest(expected_boot_id=state.status.boot_id, expected_origin_revision=state.status.origin_revision,
                                                              expected_config_id=state.hello.config_id, area_clear_confirmed=True))

    def wait(self, predicate, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(self.controller.state()):
                return self.controller.state()
            time.sleep(0.05)
        raise AssertionError(f"timed out: {self.controller.state()}")

    def finish(self):
        return self.wait(lambda state: state.run.state in TERMINAL).run

    def device_report(self):
        self.controller.disconnect()
        for transport in self.transports:
            transport.close()
        return json.loads(self.report.read_text())


def firmware_root():
    from pathlib import Path
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def bench(usb_build, profile, tmp_path):
    bench = Bench(usb_build, profile, tmp_path)
    yield bench
    bench.controller.disconnect()
    for transport in bench.transports:
        transport.close()


def test_prepared_job_streams_to_completion_on_the_simulated_firmware(bench):
    state = bench.controller.connect("sim")
    assert state.hello.boot_id == "00000064" and state.status.origin == "FRESH"
    draft, job = bench.job("Draw a circle diameter 40")
    bench.start(job)
    run = bench.finish()
    lines = job.gcode.splitlines()
    assert run.state == "completed" and run.acknowledged_seq == len(lines) == run.total_commands
    end = tuple(float(word[1:]) for word in lines[-2].split()[1:3])
    assert run.position_mm == pytest.approx(end, abs=1e-3)
    report = bench.device_report()
    assert report["outcome"] == "completed" and report["position"] == pytest.approx(end, abs=2.5e-4)
    assert report["pen_down"] is False and report["coils_energized"] == [True, True]
    assert report["min_gap_after_pen_down_ms"] >= 300
    assert sum(1 for _, angle in report["servo_writes"] if angle == bench.profile.pen_down_degrees) == draft.preview.strokes


def test_stop_then_validated_home_then_a_second_job(bench):
    state = bench.controller.connect("sim")
    _, job = bench.job("Draw a circle diameter 80")
    bench.start(job)
    bench.wait(lambda state: state.run.acknowledged_seq >= 5)
    stopped_at = time.monotonic()
    bench.controller.stop()
    run = bench.finish()
    assert run.state == "aborted" and "HOST_STOP" in run.message and time.monotonic() - stopped_at < 2
    status = bench.wait(lambda state: state.status.state == "IDLE" and state.status.result == "ABORTED").status
    assert status.position_mm != (0.0, 0.0) and not status.pen_down
    with pytest.raises(Exception, match="Go to origin"):
        bench.start(job)  # never an implicit travel
    bench.controller.home(HomeRequest(expected_boot_id=status.boot_id, expected_origin_revision=status.origin_revision, route_confirmed=True))
    bench.wait(lambda state: state.status.state == "IDLE" and state.status.position_mm == (0.0, 0.0) and state.status.job == "-")
    _, second = bench.job("Draw a circle diameter 20")
    bench.start(second)
    assert bench.finish().state == "completed"
    assert bench.device_report()["outcome"] == "completed"


def test_pause_and_resume_complete_the_same_drawing(bench):
    bench.controller.connect("sim")
    _, job = bench.job("Draw a circle diameter 60")
    bench.start(job)
    bench.wait(lambda state: state.run.acknowledged_seq >= 3)
    bench.controller.pause()
    paused = bench.wait(lambda state: state.run.state == "paused")
    acknowledged = paused.run.acknowledged_seq
    time.sleep(0.5)
    assert bench.controller.state().run.acknowledged_seq <= acknowledged + 1 and not bench.controller.state().status.pen_down
    bench.controller.resume()
    assert bench.finish().state == "completed"


def test_a_frozen_host_is_stopped_by_the_firmware_watchdog(bench):
    bench.controller.connect("sim")
    _, job = bench.job("Draw a circle diameter 80")
    bench.start(job)
    bench.wait(lambda state: state.run.acknowledged_seq >= 3)
    transport = bench.transports[-1]
    transport.write = lambda data: None  # the host process hangs: nothing more reaches the device
    run = bench.wait(lambda state: state.run.state in TERMINAL, timeout=30).run
    # Replies still arrive, so the host records the firmware's own watchdog abort.
    assert run.state == "aborted" and "HOST_LOST" in run.message
    report = bench.device_report()
    assert report["outcome"] == "aborted" and report["reason"] == "Host lost" and report["pen_down"] is False
