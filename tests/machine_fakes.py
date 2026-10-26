"""In-memory Picasso protocol v1 device double with fault injection (host tests only)."""

from pathlib import Path
import queue
import threading
import time
from threading import Event

from backend.app import firmware
from backend.app.drawing.service import DraftService
from backend.app.machine import protocol
from backend.app.machine.controller import MachineController
from backend.app.machine.transport import TransportClosed
from backend.app.models import CalibrationSaveRequest, GenerateRequest, PreparationRequest
from backend.app.profiles import load_reference_profiles
from backend.app.storage.preparation import JobManager, ProfileManager
from backend.app.storage.repository import Repository
from test_phase4_storage import calibration

ROOT = Path(__file__).resolve().parents[1]


class FakeDevice:
    def __init__(self, config_id, boot="0000002a"):
        self.config_id, self.boot = config_id, boot
        self.lock = threading.RLock()
        self.outbox: queue.Queue = queue.Queue()
        self.received: list[tuple[float, str]] = []
        self.executions: dict[int, int] = {}
        self.state, self.job, self.origin, self.origin_rev = "IDLE", "-", "FRESH", 1
        self.x = self.y = 0.0
        self.pen_down = False
        self.rx = self.done = 0
        self.result = "NONE:NONE"
        self.token = None
        self.in_flight = None
        self.answer_hello = True
        self.hello_protocol = 1
        self.hold_ack: dict[int, Event] = {}
        self.drop_ack: set[int] = set()
        self.drop_rcv: set[int] = set()
        self.corrupt_once: set[int] = set()
        self.duplicate_ack: set[int] = set()
        self.silent_at: int | None = None
        self.reset_at: int | None = None
        self.silent = False
        self.closed = False

    # ------------------------------------------------------------- transport
    def transport(self, port):
        if self.closed:
            raise TransportClosed("fake port unavailable")
        return FakeTransport(self)

    def emit(self, body):
        if not self.silent:
            self.outbox.put(protocol.encode(body) if len(body) <= protocol.MAX_HOST_BODY else
                            b"@" + body.encode() + b"*" + protocol.crc(body.encode()).encode() + b"\n")

    def bodies(self, prefix=""):
        return [body for _, body in self.received if body.startswith(prefix)]

    # -------------------------------------------------------------- protocol
    def status_body(self):
        return (f"ST {self.state} {self.job} {self.boot} {self.origin_rev} {self.origin} {self.x:.3f} {self.y:.3f} "
                f"{'DOWN' if self.pen_down else 'UP'} {self.rx} {self.done} {self.result}")

    def handle(self, body):
        with self.lock:
            self.received.append((time.monotonic(), body))
            if self.silent:
                return
            words = body.split(" ")
            command = words[0]
            if command == "HELLO":
                if not self.answer_hello:
                    return
                if self.hello_protocol != 1:
                    self.emit("ERR HELLO VERSION 1")
                else:
                    self.emit(f"HELLO 1 0.6.1 picasso-fw-v1 {self.config_id} {self.boot} STREAM,PAUSE,STOP,HOME")
            elif command == "STATUS":
                self.emit(self.status_body())
            elif command == "BEGIN":
                _, token, x, y, boot, orev = words
                error = ("STATE" if self.state != "IDLE" else "NO_ORIGIN" if self.origin == "UNSET" else
                         "SESSION" if boot != self.boot else "REFERENCE" if int(orev) != self.origin_rev else
                         "POSITION" if (float(x), float(y)) != (round(self.x, 3), round(self.y, 3)) else None)
                if error:
                    self.emit(f"ERR BEGIN {error}")
                    return
                self.token, self.job, self.state, self.rx, self.done = token, f"USB:{token}", "RUNNING", 0, 0
                self.origin = "VALID"
                self.emit(f"OK BEGIN {token}")
            elif command == "M":
                self.motion(int(words[1]), " ".join(words[2:]))
            elif command == "END":
                if self.state != "RUNNING" or self.in_flight:
                    self.emit("ERR END BUSY")
                    return
                self.emit(f"OK END {self.token}")
                self.finish("COMPLETED", "NONE")
            elif command == "PAUSE":
                if self.state != "RUNNING":
                    self.emit("ERR PAUSE STATE")
                    return
                self.state = "PAUSED"
                self.emit("OK PAUSE")
                self.event("PAUSED", "NONE")
            elif command == "RESUME":
                if self.state != "PAUSED":
                    self.emit("ERR RESUME STATE")
                    return
                self.state = "RUNNING"
                self.emit("OK RESUME")
                self.event("RESUMED", "NONE")
                if self.in_flight:
                    self.complete_later(self.in_flight)
            elif command == "STOP":
                if self.state not in ("RUNNING", "PAUSED"):
                    self.emit("ERR STOP STATE")
                    return
                self.emit("OK STOP")
                if self.in_flight:
                    self.emit(f"NAK {self.in_flight} ABORTED")
                    self.in_flight = None
                for hold in self.hold_ack.values():
                    hold.set()
                self.finish("ABORTED", "HOST_STOP")
            elif command == "HOME":
                if self.state != "IDLE":
                    self.emit("ERR HOME STATE")
                    return
                self.x = self.y = 0.0
                self.emit("OK HOME")
            else:
                self.emit("ERR FRAME UNKNOWN")

    def motion(self, seq, line):
        if self.reset_at == seq:
            self.boot, self.state, self.job, self.origin, self.origin_rev = "0000002b", "IDLE", "-", "UNSET", 0
            self.in_flight = None
            self.emit(f"BOOT {self.boot} 1")
            return
        if self.state not in ("RUNNING", "PAUSED"):
            self.emit(f"NAK {seq} STATE")
            return
        if seq in self.corrupt_once:  # the frame arrives damaged: rejected, never executed
            self.corrupt_once.discard(seq)
            self.emit("ERR FRAME CRC")
            return
        if seq <= self.done:
            self.emit(f"ACK {seq} {self.x:.3f} {self.y:.3f} DUP")
            return
        if seq == self.rx and self.in_flight:
            self.emit(f"RCV {seq} DUP")
            return
        if seq != self.rx + 1:
            self.emit(f"NAK {seq} SEQUENCE")
            return
        self.rx = seq
        self.executions[seq] = self.executions.get(seq, 0) + 1
        words = line.split()
        if len(words) == 4:
            self.target = (float(words[1][1:]), float(words[2][1:]))
        else:
            self.target = (self.x, self.y)
        self.pen_down = words[-1] == "Z0"
        if seq not in self.drop_rcv:
            self.emit(f"RCV {seq}")
        self.in_flight = seq
        if self.silent_at == seq:
            self.silent = True
            return
        self.complete_later(seq)

    def complete_later(self, seq):
        hold = self.hold_ack.get(seq)

        def complete():
            if hold:
                hold.wait(10)
            time.sleep(0.01)
            with self.lock:
                if self.in_flight != seq or self.state != "RUNNING":
                    return
                self.x, self.y = self.target
                self.done, self.in_flight = seq, None
                if seq not in self.drop_ack:
                    self.emit(f"ACK {seq} {self.x:.3f} {self.y:.3f}")
                    if seq in self.duplicate_ack:
                        self.emit(f"ACK {seq} {self.x:.3f} {self.y:.3f}")
                        self.outbox.put(b"@ACK 999 0.000 0.000*0000\n")  # corrupted frame: must be ignored
        threading.Thread(target=complete, daemon=True).start()

    def event(self, name, reason):
        self.emit(f"EVT {name} {self.job} {self.done} {self.x:.3f} {self.y:.3f} {reason}")

    def finish(self, outcome, reason):
        self.event(outcome, reason)
        self.state, self.job, self.pen_down = "IDLE", "-", False
        self.result = f"{outcome}:{reason}"


class FakeTransport:
    def __init__(self, device):
        self.device = device
        self.description = "fake"

    def write(self, data: bytes):
        if self.device.closed:
            raise TransportClosed("unplugged")
        tokens = protocol.decode(data)
        self.device.handle(" ".join(tokens))

    def readline(self, timeout):
        if self.device.closed:
            raise TransportClosed("unplugged")
        try:
            return self.device.outbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        pass


class FastController(MachineController):
    POLL_INTERVAL = 0.05
    REQUEST_TIMEOUT = 0.3
    RECEIPT_TIMEOUT = 0.3
    HELLO_TIMEOUT = 0.3
    ACK_BASE = 0.4


def canonical_calibration(**changes):
    probe = calibration(verified=False)
    values = dict(firmware="picasso-canonical", firmware_config_id=firmware.config_id(probe), verified=True)
    values.update(changes)
    return calibration(**values)


def machine_system(tmp_path, prompt="Draw a rectangle 30 x 20 mm", **profile_changes):
    repo = Repository(tmp_path / "data")
    profiles = ProfileManager(repo, load_reference_profiles(ROOT))
    profile = profiles.save(CalibrationSaveRequest(calibration=canonical_calibration(**profile_changes), select_for_preparation=True))
    drafts = DraftService(repository=repo)
    jobs = JobManager(repo, drafts, profiles)
    draft = drafts.generate(GenerateRequest(prompt=prompt), Event())
    job = jobs.prepare(PreparationRequest(revision_id=draft.revision_id, profile_id=profile.id, profile_revision=profile.revision))
    return repo, profiles, jobs, profile, job
