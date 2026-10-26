"""Picasso serial protocol v1 framing and message parsing (docs/SERIAL_PROTOCOL.md)."""

import binascii
from dataclasses import dataclass
import re

PROTOCOL_VERSION = 1
DIALECT = "picasso-fw-v1"
BAUD = 115200
MAX_HOST_BODY = 90
MAX_DEVICE_BODY = 120
GCODE_PAYLOAD = 63
_BODY = re.compile(r"[\x20-\x29\x2b-\x3f\x41-\x7e]*")  # printable ASCII without '*' and '@'
_TOKEN = re.compile(r"[0-9a-f]{8}")


class FrameError(ValueError):
    """A received line claimed to be a frame but failed validation."""


def crc(body: bytes) -> str:
    return f"{binascii.crc_hqx(body, 0xFFFF):04X}"


def encode(body: str) -> bytes:
    if not _BODY.fullmatch(body) or not body or len(body) > MAX_HOST_BODY:
        raise ValueError(f"Invalid host frame body ({len(body)} bytes); see SERIAL_PROTOCOL.md")
    data = body.encode("ascii")
    return b"@" + data + b"*" + crc(data).encode("ascii") + b"\n"


def decode(line: bytes) -> list[str] | None:
    """Tokens of a valid frame, None for an informational log line."""
    line = line.rstrip(b"\n").rstrip(b"\r")
    if not line.startswith(b"@"):
        return None
    if len(line) < 6 or line[-5:-4] != b"*":
        raise FrameError("FORMAT")
    body, check = line[1:-5], line[-4:]
    if len(body) > MAX_DEVICE_BODY:
        raise FrameError("LONG")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as exc:
        raise FrameError("BYTE") from exc
    if not _BODY.fullmatch(text):
        raise FrameError("BYTE")
    if crc(body).encode() != check:
        raise FrameError("CRC")
    return text.split(" ")


def motion(sequence: int, line: str) -> bytes:
    if len(line) > GCODE_PAYLOAD:
        raise ValueError("G-code payload exceeds 63 bytes")
    return encode(f"M {sequence} {line}")


def coordinate(value: float) -> str:
    return f"{round(value, 3) or 0.0:.3f}"


def valid_token(token: str) -> bool:
    return bool(_TOKEN.fullmatch(token))


@dataclass(frozen=True)
class Hello:
    protocol: int
    firmware_version: str
    dialect: str
    config_id: str
    boot_id: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class Status:
    state: str
    job: str
    boot_id: str
    origin_revision: int
    origin: str
    x: float
    y: float
    pen_down: bool
    received_seq: int
    completed_seq: int
    result: str
    reason: str


@dataclass(frozen=True)
class Event:
    event: str
    job: str
    completed_seq: int
    x: float
    y: float
    reason: str


def parse_hello(tokens: list[str]) -> Hello:
    if len(tokens) != 7 or tokens[0] != "HELLO":
        raise FrameError("FORMAT")
    return Hello(int(tokens[1]), tokens[2], tokens[3], tokens[4], tokens[5], tuple(tokens[6].split(",")))


def parse_status(tokens: list[str]) -> Status:
    if len(tokens) != 12 or tokens[0] != "ST" or ":" not in tokens[11]:
        raise FrameError("FORMAT")
    result, reason = tokens[11].split(":", 1)
    try:
        return Status(tokens[1], tokens[2], tokens[3], int(tokens[4]), tokens[5], float(tokens[6]), float(tokens[7]),
                      tokens[8] == "DOWN", int(tokens[9]), int(tokens[10]), result, reason)
    except ValueError as exc:
        raise FrameError("FORMAT") from exc


def parse_event(tokens: list[str]) -> Event:
    if len(tokens) != 7 or tokens[0] != "EVT":
        raise FrameError("FORMAT")
    try:
        return Event(tokens[1], tokens[2], int(tokens[3]), float(tokens[4]), float(tokens[5]), tokens[6])
    except ValueError as exc:
        raise FrameError("FORMAT") from exc
