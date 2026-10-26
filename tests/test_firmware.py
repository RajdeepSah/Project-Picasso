"""Canonical firmware host checks: core unit tests, cross-checks against the
backend and simulated runs of the real sketch. Simulation is not hardware evidence."""

import json
import math
from pathlib import Path
import random
import shutil
import subprocess
from threading import Event

import pytest

from backend.app import firmware
from backend.app.drawing.errors import DrawingError
from backend.app.drawing.gcode import parse
from backend.app.drawing.service import DraftService
from backend.app.models import DrawingBounds, ExecutionPreview, ExecutionSegment, GenerateRequest, ImportRequest
from backend.app.storage.preparation import validate_physical_path
from backend.app.storage.repository import Repository

from conftest import firmware_script as script

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("g++") is None and shutil.which("c++") is None, reason="host C++ compiler unavailable")

SET_ORIGIN = ["key down", "key enter", "key enter", "key enter", "until main 3000"]
START_SD = ["key enter", "until ready 60000", "key enter"]
SQUARE = "G0 Z5\nG0 X-10.000 Y-10.000 Z5\nG1 X10.000 Y-10.000 Z0\nG1 X10.000 Y10.000 Z0\nG1 X-10.000 Y10.000 Z0\nG1 X-10.000 Y-10.000 Z0\nG0 Z5\n"


@pytest.fixture(scope="session")
def drafts(tmp_path_factory):
    return DraftService(repository=Repository(tmp_path_factory.mktemp("firmware-drafts")))


def draw(drafts, prompt):
    return drafts.generate(GenerateRequest(prompt=prompt), Event())


def simulate(build, tmp_path, script_lines, card=None, expect_exit=0):
    lines = list(script_lines)
    if card is not None:
        path = tmp_path / f"card-{len(list(tmp_path.iterdir()))}.nc"
        path.write_bytes(card.encode() if isinstance(card, str) else card)
        lines.insert(0, f"card {path}")
    result = subprocess.run([str(build["simulator"])], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=120)
    assert result.returncode == expect_exit, result.stdout + result.stderr
    return [json.loads(line) for line in result.stdout.splitlines()]


def ik(profile, x, y):
    tps = profile.spool_diameter_mm * 3.1416 / profile.steps_per_turn
    half = profile.separation_mm / 2
    return [round(math.dist((x, y), (side * half, profile.anchor_y_mm)) / tps) for side in (-1, 1)]


def last_point(code):
    line = [line for line in code.splitlines() if " X" in line][-1].split()
    return float(line[1][1:]), float(line[2][1:])


def test_core_unit_tests_pass(build):
    result = subprocess.run([str(build["core_tests"])], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().endswith("0 failures")


def tool_parse(build, data):
    result = subprocess.run([str(build["picasso_tool"]), "parse"], input=data, capture_output=True)
    assert result.returncode == 0
    return result.stdout.decode().splitlines()


@pytest.mark.parametrize("prompt", ["Draw a circle diameter 60", "Draw a rectangle", "Draw a spiral", "Draw a butterfly", "Create a beautiful mandala"])
def test_firmware_parser_accepts_every_backend_export_exactly(build, drafts, prompt):
    code = draw(drafts, prompt).gcode
    results = tool_parse(build, code.encode())
    assert results[-1] == "EOF"
    lines = code.splitlines()
    assert len(results) == len(lines) + 1
    for number, (line, result) in enumerate(zip(lines, results), start=1):
        words = result.split()
        assert words[:2] == [str(number), "OK"], (line, result)
        expected = line.split()
        assert words[2] == expected[0] and words[3] == ("UP" if expected[-1] == "Z5" else "DOWN")
        if len(expected) == 4:
            assert abs(float(words[4]) - float(expected[1][1:])) < 2.5e-4 and abs(float(words[5]) - float(expected[2][1:])) < 2.5e-4


def test_imported_sample_is_reexported_into_the_firmware_dialect(build, drafts):
    source = (ROOT / "SdCard" / "01 Test GCode" / "mandala_11x14.gcode").read_text()
    draft = drafts.import_drawing(ImportRequest(filename="mandala_11x14.gcode", content=source,
                                                center_on_origin=True, fit_width_mm=120), Event())
    results = tool_parse(build, draft.gcode.encode())
    assert results[-1] == "EOF" and all(" OK G" in line for line in results[:-1])


def test_raw_vendor_samples_are_rejected_before_any_motion(build):
    mandala = tool_parse(build, (ROOT / "SdCard" / "01 Test GCode" / "mandala_11x14.gcode").read_bytes())
    assert mandala == ["1 ERR LINE_LONG"]  # the long header comment overflows the 63-byte line buffer
    circle = tool_parse(build, (ROOT / "SdCard" / "01 Test GCode" / "circle.nc").read_bytes())
    assert circle[:2] == ["1 OK G0 UP", "2 ERR MISSING_Z"]  # legacy modal pen state is not accepted
    hazard = tool_parse(build, b"; Centre = X139.7 Y177.8\n; Pen up = Z3.0\nG0 Z5\n")
    assert hazard == ["1 OK EMPTY", "2 OK EMPTY", "3 OK G0 UP", "EOF"]


def test_firmware_geometry_agrees_with_backend_validation(build, profile):
    region = profile.allowed_region
    arguments = [str(value) for value in (profile.separation_mm, profile.anchor_y_mm, profile.spool_diameter_mm, profile.steps_per_turn,
                                          region.min_x_mm, region.max_x_mm, region.min_y_mm, region.max_y_mm, region.margin_mm,
                                          profile.rope_min_mm, profile.rope_max_mm)]
    rng = random.Random(5)
    points = [(rng.uniform(-170, 170), rng.uniform(-120, 175)) for _ in range(300)]
    points += [(0, 0), (145, 145), (-145, -95), (145.004, 0), (0, -95.03), (-150, 140)]
    segments = [(points[i], points[(i * 7 + 3) % len(points)]) for i in range(len(points))]
    queries = [f"ik {x} {y}" for x, y in points] + [f"seg {a[0]} {a[1]} {b[0]} {b[1]}" for a, b in segments]
    result = subprocess.run([str(build["picasso_tool"]), "geometry", *arguments], input="\n".join(queries), capture_output=True, text=True)
    assert result.returncode == 0
    output = result.stdout.splitlines()
    lengths, verdicts = output[:len(points)], output[len(points):]
    exact = sum([int(value) for value in line.split()] == ik(profile, *point) for line, point in zip(lengths, points))
    assert exact >= len(points) - 2  # float32 rounding may differ by one step at a half-step tie
    for line, point in zip(lengths, points):
        assert all(abs(int(a) - b) <= 1 for a, b in zip(line.split(), ik(profile, *point)))

    strict = profile.model_copy(update={"verified": True})
    tolerance = 0.02
    relaxed = strict.model_copy(update={
        "allowed_region": region.model_copy(update={"min_x_mm": region.min_x_mm - tolerance, "max_x_mm": region.max_x_mm + tolerance,
                                                    "min_y_mm": region.min_y_mm - tolerance, "max_y_mm": region.max_y_mm + tolerance}),
        "rope_min_mm": profile.rope_min_mm - tolerance, "rope_max_mm": profile.rope_max_mm + tolerance})

    def host_accepts(candidate, a, b):
        bounds = DrawingBounds(min_x_mm=0, min_y_mm=0, max_x_mm=0, max_y_mm=0, width_mm=0, height_mm=0)
        preview = ExecutionPreview(expected_start_mm=a, segments=[ExecutionSegment(start=a, end=b, pen_down=False)], bounds=bounds,
                                   drawing_distance_mm=0, travel_distance_mm=0, strokes=0, pen_lifts=0)
        try:
            validate_physical_path(preview, candidate)
            return True
        except DrawingError:
            return False

    accepted = 0
    for (a, b), verdict in zip(segments, verdicts):
        if host_accepts(strict, a, b):
            assert verdict == "OK", (a, b, verdict)  # never rejects a host-approved segment
        if verdict == "OK":
            accepted += 1
            assert host_accepts(relaxed, a, b), (a, b)  # never accepts beyond the float tolerance
    assert 20 < accepted < len(segments) - 20


def test_reset_has_no_origin_and_jobs_need_a_fresh_confirmation(build, tmp_path, profile):
    boot, ready = simulate(build, tmp_path, ["boot", "report", "key enter", "until ready 60000", "key enter", "wait 300", "report"], card=SQUARE)
    assert boot["origin_valid"] is False and boot["display"][3] == "Origin: unset"
    assert boot["serial"][0][1] == f"PICASSO FW {firmware.FIRMWARE_VERSION} DIALECT picasso-fw-v1 CFG {firmware.config_id(profile)} REGION SET ORIGIN UNSET SD ON"
    assert ready["mode"] == "ready" and ready["display"][2] == "Set origin 1st"
    assert ready["display"][1] == f"CRC {firmware.gcode_crc32(SQUARE)}"
    assert ready["steps"] == [0, 0] and ready["motion_started"] is False


def test_prepared_job_runs_to_completion_with_exact_rope_lengths(build, tmp_path, drafts, profile):
    draft = draw(drafts, "Draw a circle diameter 40")
    validate_physical_path(parse(draft.gcode), profile.model_copy(update={"verified": True}))  # host approves it first
    (result,) = simulate(build, tmp_path, ["boot", *SET_ORIGIN, *START_SD, "until result 3600000", "report"], card=draft.gcode)
    assert result["outcome"] == "completed" and result["motion_started"] is True
    assert result["display"][:2] == ["COMPLETED", f"CRC {firmware.gcode_crc32(draft.gcode)}"]
    end = last_point(draft.gcode)
    assert result["position"] == pytest.approx(end, abs=2.5e-4)
    assert all(abs(a - b) <= 1 for a, b in zip(result["rope"], ik(profile, *end)))
    origin = ik(profile, 0, 0)
    # Lengthening the left rope steps +1, the right rope -1 (legacy constants).
    assert result["motor_positions"] == [result["rope"][0] - origin[0], -(result["rope"][1] - origin[1])]
    assert result["coils_energized"] == [True, True]  # holding policy: never released automatically
    assert result["pen_down"] is False and result["origin_valid"] is True and result["origin_fresh"] is False
    downs = [write for write in result["servo_writes"] if write[1] == profile.pen_down_degrees]
    assert len(downs) == draft.preview.strokes
    assert result["min_gap_after_pen_down_ms"] >= 300 and result["min_gap_after_pen_up_ms"] >= 300
    lines = [line for _, line in result["serial"]]
    assert result["beep_edges"] >= 1 and "PICASSO RESULT COMPLETED LINE 0 REASON NONE MOTION YES" in lines
    assert lines[-1].startswith(f"@EVT COMPLETED SD 0 {end[0]:.3f} {end[1]:.3f} NONE*")  # protocol event for any host


@pytest.mark.parametrize("card, reason, line", [
    (SQUARE + "G2 X0.000 Y0.000 Z0\n", "UNSUP_G", 8),
    (SQUARE + "G0 X500.000 Y0.000 Z5\n", "OUT_REGION", 8),
    (SQUARE + "G0 X0.000 Y0.000 Z5 ; " + "x" * 50 + "\n", "LINE_LONG", 8),
    (SQUARE.replace("G1 X10.000 Y10.000 Z0", "G1 X10.000 Y10.000"), "MISSING_Z", 4),
    ("; X10 Y10 Z0 only a comment\n", "No moves", 0),
])
def test_invalid_jobs_fail_during_validation_without_motion(build, tmp_path, card, reason, line):
    (result,) = simulate(build, tmp_path, ["boot", *SET_ORIGIN, "key enter", "until result 60000", "report"], card=card)
    assert result["outcome"] == "failed" and result["reason"] == reason and result["failed_line"] == line
    assert result["motion_started"] is False and result["steps"] == [0, 0]
    assert len(result["servo_writes"]) == 1 and result["display"][3] == "No motion done"


@pytest.mark.parametrize("setup, reason", [("nocard", "SD init failed"), ("nofile", "No main.nc")])
def test_missing_card_or_file_fails_without_motion(build, tmp_path, setup, reason):
    (result,) = simulate(build, tmp_path, [setup, "boot", "key enter", "until result 5000", "report"], card=SQUARE)
    assert result["outcome"] == "failed" and result["reason"] == reason and result["steps"] == [0, 0]


def test_comments_crlf_and_unterminated_final_line_execute_like_canonical_file(build, tmp_path):
    canonical = SQUARE + "G0 X0.000 Y0.000 Z5\n"
    variant = "; Square X99 Y99 Z0 must not move\r\n" + SQUARE.replace("\n", "\r\n").replace(
        "G0 X-10.000", "(travel X50 Y50 Z0) G0 X-10.000") + "g00 y0 x0 z5"
    reports = [simulate(build, tmp_path, ["boot", *SET_ORIGIN, *START_SD, "until result 600000", "report"], card=card)[0]
               for card in (canonical, variant)]
    for report in reports:
        assert report["outcome"] == "completed" and report["position"] == [0, 0]
    assert reports[0]["steps"] == reports[1]["steps"] and reports[0]["motor_positions"] == reports[1]["motor_positions"] == [0, 0]
    assert reports[1]["validated"]["lines"] == 9


def test_stop_raises_pen_quickly_holds_coils_and_requires_a_new_origin(build, tmp_path, drafts, profile):
    draft = draw(drafts, "Draw a circle diameter 80")
    stopped, homed, refused = simulate(build, tmp_path, [
        "boot", *SET_ORIGIN, *START_SD, "wait 4000", "key esc", "until result 5000", "report",
        "key enter", "key down", "key enter", "key down", "key down", "key enter", "until result 600000", "report",
        "key enter", "key enter", "until ready 60000", "key enter", "wait 500", "report"], card=draft.gcode)
    assert stopped["outcome"] == "aborted" and stopped["reason"] == "Stopped by user" and stopped["failed_line"] > 2
    pressed = stopped["key_presses_ms"][-1]
    raise_time = next(time for time, angle in stopped["servo_writes"] if time > pressed and angle == profile.pen_up_degrees)
    assert raise_time - pressed <= 60  # debounce (<=30 ms) plus one bounded motion slice, simulated
    assert max(stopped["last_step_ms"]) - pressed <= 60
    assert stopped["pen_down"] is False and stopped["coils_energized"] == [True, True]
    origin = ik(profile, 0, 0)
    assert stopped["motor_positions"] == [stopped["rope"][0] - origin[0], -(stopped["rope"][1] - origin[1])]
    assert stopped["position"] != [0, 0] and stopped["origin_fresh"] is False
    # Go to origin: validated pen-up travel back, still needing a fresh confirmation.
    assert homed["outcome"] == "completed" and homed["position"] == [0, 0] and homed["motor_positions"] == [0, 0]
    assert refused["mode"] == "ready" and refused["display"][2] == "Set origin 1st"
    assert refused["steps"] == homed["steps"]


def test_pause_and_resume_execute_the_identical_step_sequence(build, tmp_path, drafts, profile):
    code = draw(drafts, "Draw a circle diameter 30").gcode
    (plain,) = simulate(build, tmp_path, ["boot", *SET_ORIGIN, *START_SD, "until result 600000", "report"], card=code)
    paused, resumed = simulate(build, tmp_path, ["boot", *SET_ORIGIN, *START_SD, "wait 2500", "key enter", "until paused 3000",
                                                 "report", "wait 1000", "key enter", "until result 600000", "report"], card=code)
    assert paused["phase"] == "paused" and paused["pen_down"] is False and paused["coils_energized"] == [True, True]
    assert paused["display"][0] == "PAUSED  pen up"
    assert resumed["outcome"] == "completed"
    assert resumed["steps"] == plain["steps"] and resumed["motor_positions"] == plain["motor_positions"]
    assert len(resumed["servo_writes"]) == len(plain["servo_writes"]) + 2  # one extra raise and lower
    assert resumed["min_gap_after_pen_down_ms"] >= 300


def test_card_removal_during_a_job_fails_with_the_pen_raised(build, tmp_path, drafts):
    code = draw(drafts, "Draw a circle diameter 40").gcode
    (result,) = simulate(build, tmp_path, ["boot", *SET_ORIGIN, "key enter", "until ready 60000", "fail_after 400",
                                           "key enter", "until result 600000", "report"], card=code)
    assert result["outcome"] == "failed" and result["reason"] == "SD read error"
    assert result["motion_started"] is True and result["pen_down"] is False and result["failed_line"] > 0
    assert result["coils_energized"] == [True, True]


def test_jog_release_and_built_in_test_square(build, tmp_path, profile):
    jogged, back, refused, released, square = simulate(build, tmp_path, [
        "boot", *SET_ORIGIN, "key down", "key enter", "key down", "key enter", "wait 400", "key enter", "until jog_idle 5000", "report",
        "key down", "key enter", "until jog_idle 5000", "report",
        "key esc", "key down", "key enter", "report",
        "key enter", "key down", "key down", "key down", "key enter", "key enter", "report",
        *SET_ORIGIN, "key down", "key enter", "key down", "key down", "key down", "key down", "key enter", "until result 600000", "report"])
    assert jogged["motor_positions"] == [64, 0] and jogged["origin_valid"] is False  # L rope + uses the lengthen direction
    assert back["motor_positions"] == [0, 0]
    assert refused["mode"] == "message" and refused["display"][0] == "Origin unknown"
    assert released["coils_energized"] == [False, False] and released["origin_valid"] is False
    assert square["outcome"] == "completed" and square["position"] == [0, 0] and square["motor_positions"] == [0, 0]
    assert sum(square["steps"]) > sum(released["steps"])
    assert [angle for _, angle in square["servo_writes"]].count(profile.pen_down_degrees) == 1


def test_reference_build_has_no_workspace_and_refuses_motion_jobs(tmp_path_factory, tmp_path):
    out = tmp_path_factory.mktemp("firmware-reference")
    profile, kind = script.load_profile(reference="reference-350")
    script.write_config(profile, kind, out / "machine_config.h")
    reference = script.host_build(out, out / "machine_config.h")
    (result,) = simulate(reference, tmp_path, ["boot", "key enter", "report"], card=SQUARE)
    assert result["serial"][0][1].endswith("REGION NONE ORIGIN UNSET SD ON")
    assert result["mode"] == "message" and result["display"][:2] == ["No workspace in", "machine config"]
    assert result["steps"] == [0, 0]
