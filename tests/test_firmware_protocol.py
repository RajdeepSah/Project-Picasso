"""Firmware side of serial protocol v1, exercised through the host simulator of
the real sketch. Simulation evidence only; no board was involved."""

import json
import shutil
import subprocess

import pytest

from backend.app.machine import protocol

pytestmark = pytest.mark.skipif(shutil.which("g++") is None and shutil.which("c++") is None, reason="host C++ compiler unavailable")

SET_ORIGIN = ["key down", "key enter", "key enter", "key enter", "until main 3000"]
BOOT = ["boot_counter 41", "boot"]  # boot ID 0000002a
SESSION = "0000002a 1"  # boot ID and origin revision after one Set origin


def run(build, tmp_path, lines, card=None):
    if card is not None:
        path = tmp_path / "main.nc"
        path.write_text(card)
        lines = [f"card {path}", *lines]
    result = subprocess.run([str(build["simulator"])], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line) for line in result.stdout.splitlines()]


def frames(report):
    """Device-to-host frames, CRC-checked by the host decoder."""
    return [" ".join(protocol.decode(line.encode() + b"\n")) for _, line in report["serial"] if line.startswith("@")]


def keepalive(ms):
    """Wait while polling STATUS like a connected host (keeps the watchdog satisfied)."""
    steps = []
    while ms > 0:
        steps += ["frame STATUS", f"wait {min(ms, 500)}"]
        ms -= 500
    return steps


def test_handshake_boot_identity_and_status_never_move(build, tmp_path):
    (report,) = run(build, tmp_path, [*BOOT, "frame HELLO 1", "frame STATUS", "frame HELLO 2", "frame BOGUS", "wait 100", "report"])
    replies = frames(report)
    assert replies[0] == "BOOT 0000002a 1"
    assert replies[1].startswith("HELLO 1 0.6.0 picasso-fw-v1 ") and replies[1].endswith(" 0000002a STREAM,PAUSE,STOP,HOME")
    assert replies[2] == "ST IDLE - 0000002a 0 UNSET 0.000 0.000 UP 0 0 NONE:NONE"
    assert replies[3:] == ["ERR HELLO VERSION 1", "ERR FRAME UNKNOWN"]
    assert report["steps"] == [0, 0] and len(report["servo_writes"]) == 1


def test_begin_requires_origin_session_reference_position_and_an_idle_device(build, tmp_path):
    (report,) = run(build, tmp_path, [
        *BOOT, "frame BEGIN 0a0b0c0d 0.000 0.000 0000002a 0", "wait 50", *SET_ORIGIN,
        "frame BEGIN 0a0b0c0d 0.000 0.000 00000001 1", "frame BEGIN 0a0b0c0d 0.000 0.000 0000002a 2",
        "frame BEGIN 0a0b0c0d 1.000 0.000 0000002a 1", "frame BEGIN zz 0.000 0.000 0000002a 1",
        "key enter", "until ready 30000",  # SD job validated and waiting on the keypad
        f"frame BEGIN 0a0b0c0d 0.000 0.000 {SESSION}", "wait 100", "report"], card="G0 Z5\nG0 X1.000 Y1.000 Z5\n")
    errors = [reply for reply in frames(report) if reply.startswith("ERR")]
    assert errors == ["ERR BEGIN NO_ORIGIN", "ERR BEGIN SESSION", "ERR BEGIN REFERENCE", "ERR BEGIN POSITION",
                      "ERR BEGIN ARGS", "ERR BEGIN STATE"]
    assert report["mode"] == "ready" and report["steps"] == [0, 0]


def test_commands_are_acknowledged_after_completion_and_never_executed_twice(build, tmp_path):
    (report,) = run(build, tmp_path, [
        *BOOT, *SET_ORIGIN, f"frame BEGIN 0a0b0c0d 0.000 0.000 {SESSION}", "wait 400",
        "frame M 1 G0 Z5", "wait 100",
        "frame M 2 G0 X-5.000 Y-5.000 Z5", "wait 20", "frame M 2 G0 X-5.000 Y-5.000 Z5",  # repeated while running
        "frame M 3 G1 X5.000 Y-5.000 Z0",  # second command while one is pending
        *keepalive(3000),
        "frame M 2 G0 X-5.000 Y-5.000 Z5",  # repeated after completion
        "frame M 3 G1 X5.000 Y-5.000 Z0", *keepalive(3000),
        "frame M 4 G0 Z5 ; comment with X9 Y9", *keepalive(1000),
        "frame END 0a0b0c0d", *keepalive(1000), "frame STATUS", "wait 50", "report"])
    replies = frames(report)
    motion = [reply for reply in replies if reply.split()[0] in ("RCV", "ACK", "NAK")]
    assert motion == ["RCV 1", "ACK 1 0.000 0.000", "RCV 2", "RCV 2 DUP", "NAK 3 BUSY", "ACK 2 -5.000 -5.000",
                      "ACK 2 -5.000 -5.000 DUP", "RCV 3", "ACK 3 5.000 -5.000", "RCV 4", "ACK 4 5.000 -5.000"]
    assert "OK END 0a0b0c0d" in replies
    assert "EVT COMPLETED USB:0a0b0c0d 4 5.000 -5.000 NONE" in replies
    assert replies[-1] == f"ST IDLE - {SESSION} VALID 5.000 -5.000 UP 4 4 COMPLETED:NONE"
    assert report["outcome"] == "completed" and report["pen_down"] is False and report["position"] == [5, -5]
    # ACK 3 only after the pen was down and settled for the drawn segment.
    assert report["min_gap_after_pen_down_ms"] >= 300


def test_gaps_and_invalid_commands_fail_the_job_without_executing_them(build, tmp_path):
    gap, invalid = (run(build, tmp_path, [
        *BOOT, *SET_ORIGIN, f"frame BEGIN 0a0b0c0d 0.000 0.000 {SESSION}", "wait 400",
        "frame M 1 G0 Z5", "wait 100", command, *keepalive(1500), "report"])[0]
        for command in ("frame M 3 G0 X1.000 Y1.000 Z5", "frame M 2 G0 X500.000 Y0.000 Z5"))
    assert "NAK 3 SEQUENCE" in frames(gap) and gap["outcome"] == "failed" and gap["reason"] == "Sequence error"
    assert "NAK 2 OUT_REGION" in frames(invalid) and invalid["reason"] == "OUT_REGION"
    assert "EVT FAILED USB:0a0b0c0d 1 0.000 0.000 OUT_REGION" in frames(invalid)
    for report in (gap, invalid):
        assert report["steps"] == [0, 0] and report["pen_down"] is False


def test_host_stop_aborts_mid_move_and_reports_the_unfinished_command(build, tmp_path):
    (report,) = run(build, tmp_path, [
        *BOOT, *SET_ORIGIN, f"frame BEGIN 0a0b0c0d 0.000 0.000 {SESSION}", "wait 400",
        "frame M 1 G0 X-60.000 Y-60.000 Z5", *keepalive(1500), "frame STOP", *keepalive(1000), "frame STOP", "wait 50", "report"])
    replies = frames(report)
    assert replies.index("OK STOP") < replies.index("NAK 1 ABORTED")
    event = next(reply for reply in replies if reply.startswith("EVT ABORTED"))
    assert event.startswith("EVT ABORTED USB:0a0b0c0d 0 ") and event.endswith(" HOST_STOP")
    assert replies[-1] == "ERR STOP STATE"
    x, y = report["position"]
    assert -60 < x < 0 and -60 < y < 0 and report["pen_down"] is False and report["coils_energized"] == [True, True]


def test_watchdog_stops_a_host_job_when_the_host_goes_silent(build, tmp_path):
    polled, silent = (run(build, tmp_path, [
        *BOOT, *SET_ORIGIN, f"frame BEGIN 0a0b0c0d 0.000 0.000 {SESSION}", "wait 400",
        "frame M 1 G0 Z5", "wait 100", "frame M 2 G1 Z0", *waiting, "report"])[0]
        for waiting in (keepalive(6000), ["wait 6000"]))
    assert polled["mode"] == "executing" and polled["pen_down"] is True  # polling host: job keeps waiting
    assert silent["outcome"] == "aborted" and silent["reason"] == "Host lost" and silent["pen_down"] is False
    assert any(reply.endswith(" HOST_LOST") for reply in frames(silent))


def test_keypad_esc_stops_a_usb_job_and_corrupted_frames_never_act(build, tmp_path):
    (report,) = run(build, tmp_path, [
        *BOOT, *SET_ORIGIN, f"frame BEGIN 0a0b0c0d 0.000 0.000 {SESSION}", "wait 400",
        "raw @M 1 G0 X-20.000 Y-20.000 Z5*0000\\n", "raw @" + "X" * 120 + "\\n", "wait 100",
        "frame STATUS", "frame M 1 G0 X-20.000 Y-20.000 Z5", *keepalive(500), "key esc", *keepalive(1000), "report"])
    replies = frames(report)
    assert replies[replies.index("OK BEGIN 0a0b0c0d") + 1:][:3] == [
        "ERR FRAME CRC", "ERR FRAME LONG", f"ST RUNNING USB:0a0b0c0d {SESSION} VALID 0.000 0.000 UP 0 0 NONE:NONE"]
    assert any(reply.startswith("EVT ABORTED USB:0a0b0c0d") and reply.endswith(" STOPPED") for reply in replies)
    assert report["reason"] == "Stopped by user"


def test_home_is_a_validated_pen_up_route_bound_to_the_session(build, tmp_path):
    (report,) = run(build, tmp_path, [
        *BOOT, *SET_ORIGIN, f"frame BEGIN 0a0b0c0d 0.000 0.000 {SESSION}", "wait 400",
        "frame M 1 G0 X10.000 Y10.000 Z5", *keepalive(2000), "frame END 0a0b0c0d", *keepalive(1000),
        "frame HOME 0000002a 0", f"frame HOME {SESSION}", *keepalive(2000), "frame STATUS", "wait 50", "report"])
    replies = frames(report)
    assert "ERR HOME REFERENCE" in replies and "OK HOME" in replies
    assert "EVT COMPLETED HOME 1 0.000 0.000 NONE" in replies
    assert replies[-1].startswith(f"ST IDLE - {SESSION} VALID 0.000 0.000 UP")
