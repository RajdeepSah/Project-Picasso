"""Explicit USB session with acknowledged streaming (docs/SERIAL_PROTOCOL.md).

One reader thread owns incoming bytes. Control requests (STATUS, PAUSE, RESUME,
STOP) are written directly under the write lock, so they never wait for a motion
acknowledgement. One worker streams a run, one command at a time, and never
resends motion unless STATUS proves the device did not receive it.
"""

from collections import defaultdict
from datetime import datetime, timezone
import math
import queue
import secrets
import threading
import time
import uuid

from .. import firmware
from ..drawing.errors import DrawingError
from ..models import DeviceHello, DeviceStatus, MachineState, UsbRun
from . import protocol
from .transport import TransportClosed

ACTIVE = {"starting", "streaming", "pausing", "paused", "resuming", "stopping"}
DEVICE_BUSY = {"RUNNING", "PAUSING", "PAUSED", "RESUMING", "ENDING"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class _Waiter:
    def __init__(self):
        self.event = threading.Event()
        self.tokens = None


class _RunEnded(Exception):
    pass


def machine_error(code, message, status=409):
    return DrawingError(code, message, status)


class MachineController:
    POLL_INTERVAL = 0.5
    REQUEST_TIMEOUT = 1.0
    MISSED_POLLS = 3
    RECEIPT_TIMEOUT = 1.0
    HELLO_ATTEMPTS = 3
    HELLO_TIMEOUT = 2.0
    RETRANSMITS = 2
    ACK_BASE = 2.7  # seconds added to each motion estimate (pen settling plus margin)

    def __init__(self, repository, jobs, profiles, transport_factory, simulated=False):
        self.repository, self.jobs, self.profiles = repository, jobs, profiles
        self.transport_factory = transport_factory
        self.simulated = simulated
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.start_lock = threading.Lock()
        self.request_locks = defaultdict(threading.Lock)
        self.waiters: dict[str, _Waiter] = {}
        self.motion: queue.Queue = queue.Queue()
        self.transport = None
        self.generation = 0
        self.connection = "disconnected"
        self.port = None
        self.message = "Not connected. Select a port and connect explicitly; nothing is opened automatically."
        self.hello: protocol.Hello | None = None
        self.status: protocol.Status | None = None
        self.status_at = None
        self.status_iso = None
        self.run: UsbRun | None = None
        self.frame_errors = 0

    # ------------------------------------------------------------ state view
    def state(self) -> MachineState:
        """Snapshot without I/O: always answers, even while a motion ACK is pending."""
        with self.lock:
            hello = self.hello and DeviceHello(protocol=self.hello.protocol, firmware_version=self.hello.firmware_version,
                                               dialect=self.hello.dialect, config_id=self.hello.config_id,
                                               boot_id=self.hello.boot_id, capabilities=list(self.hello.capabilities))
            status = self.status and DeviceStatus(
                state=self.status.state, job=self.status.job, boot_id=self.status.boot_id, origin_revision=self.status.origin_revision,
                origin=self.status.origin, position_mm=(self.status.x, self.status.y), pen_down=self.status.pen_down,
                received_seq=self.status.received_seq, completed_seq=self.status.completed_seq, result=self.status.result,
                reason=self.status.reason, observed_at=self.status_iso)
            age = time.monotonic() - self.status_at if self.status_at else None
            run = self.run.model_copy() if self.run else None
            return MachineState(connection=self.connection, port=self.port, simulated=self.simulated, message=self.message,
                                hello=hello, status=status, status_age_s=age, run=run,
                                recent_runs=[UsbRun.model_validate(item) for item in self.repository.runs(5)])

    # ----------------------------------------------------------- connection
    def connect(self, port: str) -> MachineState:
        with self.lock:
            if self.connection in ("connecting", "connected"):
                raise machine_error("ALREADY_CONNECTED", "Disconnect the current machine before connecting another port.")
            if self.run and self.run.state in ACTIVE:
                raise machine_error("RUN_ACTIVE", "A run is still active.")
            self.connection, self.port, self.hello, self.status, self.status_at = "connecting", port, None, None, None
            self.message = "Opening the selected port and waiting for the Picasso handshake. No motion is sent."
            self.generation += 1
            generation = self.generation
        try:
            transport = self.transport_factory(port)
        except (TransportClosed, OSError) as exc:
            self._set_disconnected(generation, f"Could not open {port}: {exc}. Check permissions and that no other program owns the port.")
            raise machine_error("PORT_UNAVAILABLE", f"Could not open {port}: {exc}", 503) from exc
        with self.lock:
            self.transport = transport
        threading.Thread(target=self._read_loop, args=(transport, generation), daemon=True, name="picasso-serial-reader").start()
        hello_tokens = None
        for _ in range(self.HELLO_ATTEMPTS):  # HELLO is read-only, so repeating it is safe
            try:
                hello_tokens = self._request("HELLO 1", "HELLO", self.HELLO_TIMEOUT)
                break
            except DrawingError:
                if generation != self.generation:
                    break
        if hello_tokens is None:
            self._close(generation, "disconnected", "No Picasso firmware answered on this port. It may run the legacy sketch or older firmware, or still be resetting.")
            raise machine_error("NO_HANDSHAKE", "No Picasso protocol handshake. Upload canonical firmware 0.6.0+ or check the port.", 502)
        try:
            hello = protocol.parse_hello(hello_tokens) if hello_tokens[0] == "HELLO" else None
        except (protocol.FrameError, ValueError):
            hello = None
        if not hello or hello.protocol != protocol.PROTOCOL_VERSION or hello.dialect != protocol.DIALECT or "STREAM" not in hello.capabilities:
            self._close(generation, "incompatible", f"The device answered with an unsupported protocol ({' '.join(hello_tokens)}). It stays unavailable for drawing.")
            raise machine_error("INCOMPATIBLE_FIRMWARE", "The firmware does not support serial protocol 1 streaming.", 502)
        with self.lock:
            self.hello = hello
        try:
            self._refresh_status()
        except DrawingError as exc:
            self._close(generation, "disconnected", "The device stopped answering after the handshake.")
            raise exc
        with self.lock:
            self.connection = "connected"
            self.message = f"Connected to Picasso firmware {hello.firmware_version}, boot {hello.boot_id}. Position is a commanded estimate, not a measurement."
        threading.Thread(target=self._poll_loop, args=(generation,), daemon=True, name="picasso-status-poll").start()
        return self.state()

    def disconnect(self) -> MachineState:
        with self.lock:
            generation = self.generation
            active = self.run is not None and self.run.state in ACTIVE
        if active:
            self._try_stop()
            self._end_run("interrupted", "Disconnected by the operator during the run. The device stops host jobs it loses; re-check the machine.")
        self._close(generation, "disconnected", "Disconnected. Nothing reconnects or resumes automatically.")
        return self.state()

    shutdown = disconnect

    def _set_disconnected(self, generation, message):
        with self.lock:
            if generation == self.generation:
                self.connection, self.message, self.transport = "disconnected", message, None

    def _close(self, generation, connection, message):
        with self.lock:
            if generation != self.generation:
                return
            self.generation += 1
            transport, self.transport = self.transport, None
            self.connection, self.message = connection, message
            for waiter in self.waiters.values():
                waiter.event.set()
            self.waiters.clear()
        self.motion.put(("CLOSED",))
        if transport:
            transport.close()

    def _lost(self, generation, message):
        with self.lock:
            if generation != self.generation:
                return
            active = self.run is not None and self.run.state in ACTIVE
            transport = self.transport
        if active and transport is not None:
            try:  # best effort: the link may only be half dead
                with self.write_lock:
                    transport.write(protocol.encode("STOP"))
            except Exception:
                pass
        if active:
            self._end_run("fault", f"{message} Position is unknown to the host; the firmware stops a host job after 3 s without frames. Nothing resumes automatically.")
        self._close(generation, "lost", f"{message} Reconnect explicitly; a reset device needs its origin set again on the keypad.")

    # ------------------------------------------------------------- frames in
    def _read_loop(self, transport, generation):
        while generation == self.generation:
            try:
                line = transport.readline(0.2)
            except TransportClosed:
                self._lost(generation, "The serial connection closed.")
                return
            if line is None:
                continue
            try:
                tokens = protocol.decode(line)
            except protocol.FrameError:
                self.frame_errors += 1  # corrupted replies are ignored; missing replies are checked via STATUS
                continue
            if tokens:
                self._dispatch(tokens, generation)

    def _dispatch(self, tokens, generation):
        kind = tokens[0]
        if kind == "ST":
            try:
                status = protocol.parse_status(tokens)
            except protocol.FrameError:
                self.frame_errors += 1
                return
            with self.lock:
                self.status, self.status_at, self.status_iso = status, time.monotonic(), now_iso()
            key = "STATUS"
        elif kind == "HELLO":
            key = "HELLO"
        elif kind in ("OK", "ERR") and len(tokens) >= 2:
            key = tokens[1]
            if key in ("FRAME", "M"):
                self.motion.put(tuple(tokens))
                return
        elif kind == "EVT":
            self._event(tokens)
            return
        elif kind in ("RCV", "ACK", "NAK"):
            self.motion.put(tuple(tokens))
            return
        elif kind == "BOOT":
            self._reset_detected(tokens)
            return
        else:
            self.frame_errors += 1
            return
        with self.lock:
            waiter = self.waiters.pop(key, None)
        if waiter:
            waiter.tokens = tokens
            waiter.event.set()

    def _event(self, tokens):
        try:
            event = protocol.parse_event(tokens)
        except protocol.FrameError:
            self.frame_errors += 1
            return
        with self.lock:
            run = self.run
            own = run is not None and run.state in ACTIVE and event.job == f"USB:{run.token}"
        if own:
            if event.event == "PAUSED":
                self._update_run(state="paused", message="Paused: pen raised and settled, coils held. Resume explicitly.", position_mm=(event.x, event.y))
            elif event.event == "RESUMED":
                self._update_run(state="streaming", message="Resumed by explicit request.")
            elif event.event in ("COMPLETED", "ABORTED", "FAILED"):
                messages = {"COMPLETED": "Completed: every command was acknowledged after motion and pen settling.",
                            "ABORTED": f"Aborted ({event.reason}); pen raised, coils held.",
                            "FAILED": f"Failed ({event.reason}); pen raised, coils held."}
                self._end_run(event.event.lower(), messages[event.event], (event.x, event.y))
        self.motion.put(tuple(tokens))

    def _reset_detected(self, tokens):
        with self.lock:
            changed = self.hello is not None and len(tokens) > 1 and tokens[1] != self.hello.boot_id
            if changed:
                self.message = "The device reset (new boot ID). Its position is unknown: reconnect, then set the origin on the keypad."
            active = self.run is not None and self.run.state in ACTIVE
        if changed and active:
            self._end_run("fault", "The device reset during the run; position unknown. Nothing resumes automatically.")
        self.motion.put(tuple(tokens))

    # ------------------------------------------------------------ frames out
    def _send(self, data: bytes):
        with self.lock:
            transport, generation = self.transport, self.generation
        if transport is None:
            raise machine_error("NOT_CONNECTED", "The machine is not connected.")
        try:
            with self.write_lock:
                transport.write(data)
        except TransportClosed as exc:
            self._lost(generation, "Writing to the serial port failed.")
            raise machine_error("CONNECTION_LOST", "The serial connection was lost.", 503) from exc

    def _request(self, body, key, timeout=None):
        with self.request_locks[key]:
            waiter = _Waiter()
            with self.lock:
                self.waiters[key] = waiter
            self._send(protocol.encode(body))
            if not waiter.event.wait(timeout or self.REQUEST_TIMEOUT) or waiter.tokens is None:
                with self.lock:
                    if self.waiters.get(key) is waiter:
                        del self.waiters[key]
                raise machine_error("MACHINE_TIMEOUT", f"The device did not answer {key}.", 504)
            return waiter.tokens

    def _refresh_status(self) -> protocol.Status:
        self._request("STATUS", "STATUS")
        with self.lock:
            return self.status

    def _poll_loop(self, generation):
        missed = 0
        while generation == self.generation:
            time.sleep(self.POLL_INTERVAL)
            if generation != self.generation:
                return
            try:
                self._refresh_status()
                missed = 0
            except DrawingError:
                missed += 1
                if missed >= self.MISSED_POLLS:
                    self._lost(generation, "The device stopped answering status requests.")
                    return

    def _require_connected(self):
        with self.lock:
            if self.connection != "connected" or self.hello is None:
                raise machine_error("NOT_CONNECTED", "Connect to a machine running Picasso firmware first.")
            return self.hello

    # ----------------------------------------------------------- operations
    def _check_session(self, status, boot_id, origin_revision):
        hello = self._require_connected()
        if status.boot_id != hello.boot_id:
            raise machine_error("SESSION_CHANGED", "The device reset since the handshake. Reconnect and set the origin on the keypad.")
        if status.boot_id != boot_id or status.origin_revision != origin_revision:
            raise machine_error("STALE_SESSION", "The machine session or origin reference changed since you reviewed it. Review the current status first.")
        if status.state in DEVICE_BUSY or status.state == "LOCAL":
            raise machine_error("MACHINE_BUSY", f"The machine is not idle ({status.state}). SD and USB jobs never run together; finish or close the keypad menu first.")
        if status.origin == "UNSET":
            raise machine_error("ORIGIN_REQUIRED", "Set the origin on the machine's keypad first. The host can never set the origin.")

    def home(self, request) -> MachineState:
        if not request.route_confirmed:
            raise machine_error("CONFIRMATION_REQUIRED", "Confirm the pen-up straight route to (0,0) is clear.", 400)
        with self.start_lock:
            if self.run and self.run.state in ACTIVE:
                raise machine_error("RUN_ACTIVE", "A run is active.")
            status = self._refresh_status()
            self._check_session(status, request.expected_boot_id, request.expected_origin_revision)
            tokens = self._request(f"HOME {request.expected_boot_id} {request.expected_origin_revision}", "HOME", 2.0)
            if tokens[0] != "OK":
                raise machine_error("HOME_REFUSED", f"The firmware refused Go to origin: {' '.join(tokens[2:])}. It validates the route against its workspace.")
        return self.state()

    def start(self, job_id, request) -> UsbRun:
        with self.start_lock:
            hello = self._require_connected()
            if self.run and self.run.state in ACTIVE:
                raise machine_error("RUN_ACTIVE", "A run is already active.")
            job = self.jobs.validate_for_export(job_id)
            if job.mode != "physical":
                raise machine_error("SIMULATION_JOB", "Simulation jobs cannot run on hardware. Prepare a physical job.")
            profile = self.profiles.get(job.profile.id)
            expected = firmware.config_id(profile)
            if profile.firmware != "picasso-canonical" or profile.firmware_config_id != expected:
                raise machine_error("FIRMWARE_REQUIRED", "USB streaming needs a verified profile that records canonical Picasso firmware and its configuration ID.")
            if hello.config_id != expected or request.expected_config_id != hello.config_id:
                raise machine_error("CONFIG_MISMATCH", f"The machine reports configuration {hello.config_id}; the verified profile expects {expected}. Upload firmware generated from this profile.")
            if not request.area_clear_confirmed:
                raise machine_error("CONFIRMATION_REQUIRED", "Confirm the drawing area is clear and someone is watching the machine.", 400)
            status = self._refresh_status()
            self._check_session(status, request.expected_boot_id, request.expected_origin_revision)
            start_x, start_y = job.expected_start_mm
            if abs(status.x - start_x) > 0.0005 or abs(status.y - start_y) > 0.0005:
                raise machine_error("POSITION_MISMATCH", f"The machine is at ({status.x:.3f}, {status.y:.3f}) but this job starts at ({start_x:.3f}, {start_y:.3f}). Use Go to origin (validated pen-up travel) or prepare again; nothing moves implicitly.")
            lines = job.gcode.splitlines()
            if any(len(line) > protocol.GCODE_PAYLOAD for line in lines):
                raise machine_error("LINE_TOO_LONG", "A job line exceeds the 63-byte payload.")
            token = secrets.token_hex(4)
            stamp = now_iso()
            run = UsbRun(id=uuid.uuid4().hex, job_id=job.id, title=job.title, port=self.port or "", boot_id=status.boot_id,
                         origin_revision=status.origin_revision, token=token, total_commands=len(lines), state="starting",
                         message="Binding the job to this boot, origin reference and position.", position_mm=(status.x, status.y),
                         started_at=stamp, updated_at=stamp)
            with self.lock:
                self.run = run
                generation = self.generation
            self._drain_motion()
            self.repository.record_run(run)
            try:
                tokens = self._request(f"BEGIN {token} {protocol.coordinate(start_x)} {protocol.coordinate(start_y)} {status.boot_id} {status.origin_revision}", "BEGIN", 2.0)
            except DrawingError:
                self._end_run("fault", "No answer to BEGIN; the device state is unknown. Check the machine before retrying.")
                self._try_stop()
                raise
            if tokens[0] != "OK":
                self._end_run("failed", f"The firmware refused the job: {' '.join(tokens[2:])}. Nothing moved.")
                raise machine_error("BEGIN_REFUSED", f"The firmware refused the job ({' '.join(tokens[2:])}). Nothing moved.")
            self._update_run(state="streaming", message="Streaming one acknowledged command at a time.")
            tps = profile.spool_diameter_mm * 3.1416 / profile.steps_per_turn
            threading.Thread(target=self._stream, args=(run.id, lines, (start_x, start_y), tps, generation),
                             daemon=True, name="picasso-stream").start()
            return self.state().run

    def pause(self) -> MachineState:
        self._control("PAUSE", {"streaming", "resuming"}, "pausing", "Pause requested: the current slice finishes, then the pen rises.")
        return self.state()

    def resume(self) -> MachineState:
        self._control("RESUME", {"paused"}, "resuming", "Resume requested: the pen returns to its previous state after settling.")
        return self.state()

    def stop(self) -> MachineState:
        self._require_connected()
        tokens = self._request("STOP", "STOP")
        if tokens[0] != "OK":
            raise machine_error("NOTHING_RUNNING", "Nothing is running on the machine.")
        self._advance(ACTIVE - {"stopping"}, state="stopping", message="Stop requested: the current slice finishes, the pen rises, the job aborts.")
        return self.state()

    def _control(self, command, allowed, state, message):
        self._require_connected()
        with self.lock:
            if not self.run or self.run.state not in allowed:
                raise machine_error("RUN_STATE", f"{command.title()} is not available in the current run state.")
        tokens = self._request(command, command)
        if tokens[0] != "OK":
            raise machine_error("RUN_STATE", f"The firmware refused {command}: {' '.join(tokens[2:])}.")
        self._advance(allowed, state=state, message=message)

    def _advance(self, expected, **changes):
        """Apply a requested transition unless a device event already moved the run on."""
        self._update_run(only_from=expected, **changes)

    def _try_stop(self):
        try:
            self._request("STOP", "STOP")
        except DrawingError:
            pass

    # ------------------------------------------------------------- streaming
    def _update_run(self, only_from=None, **changes):
        with self.lock:
            if not self.run or self.run.state not in (only_from or ACTIVE):
                return
            self.run = self.run.model_copy(update={**changes, "updated_at": now_iso()})
            run = self.run
        # Durable on every state change; progress is checkpointed every 25 acknowledgements.
        if "state" in changes or ("acknowledged_seq" in changes and run.acknowledged_seq % 25 == 0):
            self.repository.record_run(run)

    def _end_run(self, state, message, position=None):
        with self.lock:
            if not self.run or self.run.state not in ACTIVE:
                return
            changes = {"state": state, "message": message, "updated_at": now_iso()}
            if position is not None:
                changes["position_mm"] = position
            self.run = self.run.model_copy(update=changes)
            run = self.run
        self.repository.record_run(run)
        self.motion.put(("RUN_ENDED",))

    def _drain_motion(self):
        while True:
            try:
                self.motion.get_nowait()
            except queue.Empty:
                return

    def _next(self, run_id, timeout):
        with self.lock:
            if not self.run or self.run.id != run_id or self.run.state not in ACTIVE:
                raise _RunEnded()
        try:
            return self.motion.get(timeout=max(timeout, 0))
        except queue.Empty:
            return None

    def _fault(self, message):
        self._end_run("fault", message)
        self._try_stop()

    def _stream(self, run_id, lines, start, tps, generation):
        position = start
        try:
            for sequence, line in enumerate(lines, start=1):
                if not self._deliver(run_id, sequence, line):
                    return
                target = self._target(line)
                distance = math.dist(position, target) if target else 0.0
                position = target or position
                # Legacy pacing: ~2.24 ms per motor step, up to two steps per sub-target.
                estimate = self.ACK_BASE + distance / tps * 0.0023 * 2
                if not self._await_ack(run_id, sequence, estimate, line):
                    return
            self._finish(run_id)
        except _RunEnded:
            return
        except DrawingError as exc:
            self._fault(f"Streaming stopped: {exc.message} Position unknown to the host; nothing is resent.")

    @staticmethod
    def _target(line):
        words = line.split()
        if len(words) == 4 and words[1].startswith("X") and words[2].startswith("Y"):
            return float(words[1][1:]), float(words[2][1:])
        return None

    def _deliver(self, run_id, sequence, line):
        frame = protocol.motion(sequence, line)
        for attempt in range(self.RETRANSMITS + 1):
            self._send(frame)
            self._update_run(sent_seq=sequence, current_line=line)
            deadline = time.monotonic() + self.RECEIPT_TIMEOUT
            while True:
                message = self._next(run_id, deadline - time.monotonic())
                if message is None or message[0] == "CLOSED" or (message[0] == "ERR" and message[1] == "FRAME"):
                    break
                if message[0] == "RCV" and message[1] == str(sequence):
                    return True
                if message[0] == "NAK" and message[1] == str(sequence):
                    self._await_terminal(run_id, f"The firmware rejected command {sequence} ({message[2]}); it was not executed.")
                    return False
            # No receipt: ask the device instead of guessing.
            try:
                status = self._refresh_status()
            except DrawingError:
                self._fault(f"No receipt for command {sequence} and no status answer; position unknown. Nothing was resent.")
                return False
            with self.lock:
                token = self.run.token if self.run else ""
            if status.job != f"USB:{token}":
                self._await_terminal(run_id, f"The device is no longer running this job ({status.result}:{status.reason}).")
                return False
            if status.received_seq >= sequence:
                return True  # received; the receipt frame was lost
            if status.received_seq != sequence - 1:
                self._fault(f"Sequence mismatch (device received {status.received_seq}, host sent {sequence}).")
                return False
            # Provably not received: retransmitting the identical frame is safe.
        self._fault(f"Command {sequence} could not be delivered after {self.RETRANSMITS + 1} attempts.")
        return False

    def _await_ack(self, run_id, sequence, estimate, line):
        soft = time.monotonic() + estimate
        hard = soft + estimate * 2 + 30
        while True:
            message = self._next(run_id, 0.25)
            if message and message[0] == "ACK" and message[1] == str(sequence) and len(message) >= 4:
                self._update_run(acknowledged_seq=sequence, position_mm=(float(message[2]), float(message[3])))
                return True
            if message and message[0] == "NAK" and message[1] == str(sequence):
                self._await_terminal(run_id, f"Command {sequence} did not complete ({message[2]}).")
                return False
            if time.monotonic() < soft:
                continue
            with self.lock:
                status, age = self.status, time.monotonic() - (self.status_at or 0)
                token = self.run.token if self.run else ""
            if status is None or age > 2.0:
                self._fault(f"No acknowledgement for command {sequence} and no recent status; position unknown. Nothing was resent.")
                return False
            if status.job == f"USB:{token}" and status.completed_seq >= sequence:
                # The ACK frame was lost; the device reports completion.
                self._update_run(acknowledged_seq=sequence, position_mm=(status.x, status.y))
                return True
            if status.job == f"USB:{token}" and status.state in ("PAUSING", "PAUSED", "RESUMING"):
                soft = time.monotonic() + 0.5
                hard = max(hard, soft + estimate * 3 + 30)  # paused time does not count
                continue
            if status.job == f"USB:{token}" and status.received_seq == sequence and status.state == "RUNNING" and time.monotonic() < hard:
                soft = time.monotonic() + 0.5
                continue
            if status.job != f"USB:{token}":
                self._await_terminal(run_id, f"The device ended the job ({status.result}:{status.reason}).")
                return False
            self._fault(f"Command {sequence} exceeded its acknowledgement limit ({line}). Position unknown; stopping.")
            return False

    def _await_terminal(self, run_id, fallback):
        """The device reports the end through EVT; fall back to its status."""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                self._next(run_id, 0.25)
            except _RunEnded:
                return
        try:
            status = self._refresh_status()
            state = {"ABORTED": "aborted", "FAILED": "failed", "COMPLETED": "completed"}.get(status.result, "fault")
            self._end_run(state, f"{fallback} Device result {status.result}:{status.reason}.", (status.x, status.y))
        except DrawingError:
            self._fault(fallback)

    def _finish(self, run_id):
        with self.lock:
            token = self.run.token
        for _ in range(20):
            tokens = self._request(f"END {token}", "END", 2.0)
            if tokens[0] == "OK":
                break
            if tokens[2] != "BUSY":
                self._fault(f"The firmware refused END ({tokens[2]}).")
                return
            self._next(run_id, 0.25)  # paused or settling: wait, never skip
        else:
            self._fault("The job could not be ended cleanly.")
            return
        self._advance({"streaming"}, state="stopping", message="All commands acknowledged; raising the pen.")
        self._await_terminal(run_id, "END accepted but no completion event arrived.")
