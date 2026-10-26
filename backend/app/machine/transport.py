"""Byte transports for the serial protocol. Discovery lists ports without opening them."""

from dataclasses import dataclass
import os
import queue
import subprocess
import threading
import time

from .protocol import BAUD

MAX_LINE = 256
SIMULATED_PORT = "sim://picasso-firmware"


class TransportClosed(OSError):
    pass


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str
    hwid: str
    likely_arduino: bool
    simulated: bool = False


# CH340 (vendor clone), FTDI and Arduino LLC/SRL USB IDs.
ARDUINO_VIDS = {0x1A86, 0x0403, 0x2341, 0x2A03}


def list_ports(simulated=False) -> list[PortInfo]:
    from serial.tools import list_ports as serial_ports
    ports = [PortInfo(port.device, port.description or port.device, port.hwid or "", port.vid in ARDUINO_VIDS)
             for port in sorted(serial_ports.comports(), key=lambda item: item.device)]
    if simulated:
        ports.append(PortInfo(SIMULATED_PORT, "Simulated Picasso firmware (host simulation, not hardware)", "simulator", False, True))
    return ports


class LineReader:
    """Bounded LF-delimited lines; oversized lines are dropped, never truncated into frames."""

    def __init__(self):
        self.buffer = bytearray()
        self.overflow = False

    def feed(self, data: bytes) -> list[bytes]:
        lines = []
        for byte in data:
            if byte == 0x0A:
                if not self.overflow:
                    lines.append(bytes(self.buffer) + b"\n")
                self.buffer.clear()
                self.overflow = False
            elif not self.overflow:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_LINE:
                    self.buffer.clear()
                    self.overflow = True
        return lines


class SerialTransport:
    """The operator-selected port only, opened exclusively where supported."""

    def __init__(self, device: str):
        import serial
        self.description = device
        try:
            self.port = serial.Serial(device, BAUD, timeout=0.1, write_timeout=1, exclusive=True)
        except (ValueError, serial.SerialException) as exc:
            raise TransportClosed(str(exc)) from exc
        self.lines = LineReader()
        self.ready: list[bytes] = []

    def write(self, data: bytes):
        import serial
        try:
            self.port.write(data)
            self.port.flush()
        except (serial.SerialException, OSError) as exc:
            raise TransportClosed(str(exc)) from exc

    def readline(self, timeout: float) -> bytes | None:
        import serial
        deadline = time.monotonic() + timeout
        while not self.ready:
            try:
                chunk = self.port.read(self.port.in_waiting or 1)
            except (serial.SerialException, OSError, TypeError) as exc:
                raise TransportClosed(str(exc)) from exc
            self.ready.extend(self.lines.feed(chunk))
            if not self.ready and time.monotonic() >= deadline:
                return None
        return self.ready.pop(0)

    def close(self):
        try:
            self.port.close()
        except Exception:
            pass


class ProcessTransport:
    """Serial bytes over a child process's stdin/stdout (the firmware simulator bridge)."""

    def __init__(self, command: list[str], prelude: bytes, description: str):
        self.description = description
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.queue: queue.Queue[bytes | None] = queue.Queue()
        self.lines = LineReader()
        self.process.stdin.write(prelude)
        self.process.stdin.flush()
        threading.Thread(target=self._pump, daemon=True, name="picasso-sim-reader").start()

    def _pump(self):
        while True:
            chunk = os.read(self.process.stdout.fileno(), 4096)
            if not chunk:
                self.queue.put(None)
                return
            for line in self.lines.feed(chunk):
                self.queue.put(line)

    def write(self, data: bytes):
        try:
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            raise TransportClosed(str(exc)) from exc

    def readline(self, timeout: float) -> bytes | None:
        try:
            line = self.queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if line is None:
            self.queue.put(None)
            raise TransportClosed("simulator exited")
        return line

    def close(self):
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
