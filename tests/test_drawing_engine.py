import hashlib
import math
from pathlib import Path
import re
from threading import Event
import xml.etree.ElementTree as ET

import pytest

from backend.app.drawing.commands import resolve_command
from backend.app.drawing.errors import DrawingError
from backend.app.drawing.gcode import encode, parse, verify_roundtrip
from backend.app.drawing.geometry import Budget, generate_geometry, segment_distance
from backend.app.drawing.service import DraftService
from backend.app.models import DrawingSpec, DrawingTransform, GenerateRequest, RevisionRequest


def generate(prompt="Draw a circle", service=None):
    return (service or DraftService()).generate(GenerateRequest(prompt=prompt), Event())


@pytest.mark.parametrize("prompt,name", [
    ("Draw a circle", "circle"), ("Create an ellipse 100 x 60 mm", "circle"),
    ("Draw a square", "rectangle"), ("Make a rectangle", "rectangle"),
    ("Draw a spiral with 8 turns", "spiral"), ("Draw a butterfly", "butterfly"),
    ("Create a beautiful mandala", "mandala"), ("Create a complex geometric pattern", "pattern"),
])
def test_supported_subjects_are_deterministic_and_roundtrip(prompt, name):
    first, second = generate(prompt), generate(prompt)
    assert first.spec.generator == name
    assert first.gcode == second.gcode
    assert first.gcode_sha256 == hashlib.sha256(first.gcode.encode()).hexdigest()
    assert first.gcode_sha256 == second.gcode_sha256
    assert first.revision_id != second.revision_id
    verify_roundtrip(first.geometry, parse(first.gcode))
    assert first.preview.pen_lifts == len(first.geometry.strokes)
    assert first.preview.expected_start_mm == (0, 0)
    assert first.execution_ready is False
    assert all(len(line.encode()) <= 63 for line in first.gcode.splitlines())
    assert "-0.000" not in first.gcode
    assert first.gcode.endswith("G0 Z5\nG0 X0.000 Y0.000 Z5\n")
    last = first.preview.segments[-1]
    assert tuple(last.end) == (0, 0) and not last.pen_down
    box = first.preview.bounds
    assert abs(box.min_x_mm + box.max_x_mm) <= .002 and abs(box.min_y_mm + box.max_y_mm) <= .002


@pytest.mark.parametrize("prompt", ["Draw a butterfly", "Draw a spiral with 3 turns"])
def test_rotated_drawings_stay_centred_on_the_page(prompt):
    service = DraftService()
    draft = generate(prompt, service)
    rotated = service.revise(draft.revision_id, RevisionRequest(transform={"rotation_degrees": 37}), Event())
    box = rotated.preview.bounds
    assert abs(box.min_x_mm + box.max_x_mm) <= .002 and abs(box.min_y_mm + box.max_y_mm) <= .002
    assert rotated.gcode.endswith("G0 Z5\nG0 X0.000 Y0.000 Z5\n")


@pytest.mark.parametrize("prompt", ["Draw a cat", "Draw a circle and a butterfly", "Draw a red circle",
    "Draw a circle in inches", "Draw a circle 10", "Draw a mandala with 3.5 petals",
    "Draw a circle with 12 petals", "Draw a circle width -10", "Draw a circle width 1000000",
    "Draw a circle width 10 width 20", "Draw a simple intricate mandala", "Draw a circle radius 10 diameter 20",
    "Draw a circle width", "Draw a mandala with petals"])
def test_unsupported_ambiguous_and_invalid_commands_do_not_fake_results(prompt):
    with pytest.raises(DrawingError):
        generate(prompt)


def test_dimensions_parameters_seed_and_detail_grammar():
    spec = resolve_command("Draw an intricate mandala with 16 petals, 140 mm wide, seed 7")
    assert spec.dimensions.width_mm == spec.dimensions.height_mm == 140
    assert spec.seed == 7 and spec.detail == "dense" and spec.parameters.petals == 16
    spec = resolve_command("Draw a circle radius 25 mm")
    assert spec.dimensions.width_mm == spec.dimensions.height_mm == 50


def test_circle_accuracy_and_rectangle_bounds():
    circle = generate("Draw a circle diameter 100")
    bounds = circle.preview.bounds
    assert bounds.width_mm == bounds.height_mm == 100
    for a, b in zip(circle.geometry.strokes[0].points, circle.geometry.strokes[0].points[1:]):
        assert abs(math.hypot(*a) - 50) <= .000708
        midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        assert 50 - math.hypot(*midpoint) <= circle.chord_tolerance_mm + circle.rounding_tolerance_mm
    rectangle = generate("Draw a rectangle 100 x 60 mm")
    assert rectangle.preview.bounds.width_mm == 100
    assert rectangle.preview.bounds.height_mm == 60
    assert rectangle.preview.drawing_distance_mm == 320


def test_mandala_rotational_symmetry_and_seed_variation():
    draft = generate("Draw a mandala with 12 petals, seed 5")
    # First four strokes are rings, followed by one rotated copy of each petal.
    a, b = draft.geometry.strokes[4:6]
    assert len(a.points) == len(b.points)
    angle = math.tau / 12
    for point, expected in zip(a.points, b.points):
        x, y = point
        rotated = (x * math.cos(angle) - y * math.sin(angle), x * math.sin(angle) + y * math.cos(angle))
        assert math.dist(rotated, expected) < .002
    assert generate("Draw a mandala seed 5").gcode_sha256 != generate("Draw a mandala seed 6").gcode_sha256


def test_transforms_aspect_fit_initial_travel_and_immutable_revisions():
    service = DraftService()
    original = generate("Draw a rectangle 100 x 60 mm", service)
    transformed = service.revise(original.revision_id, RevisionRequest(transform=DrawingTransform(
        rotation_degrees=90, offset_x_mm=10, offset_y_mm=-20)), Event())
    bounds = transformed.preview.bounds
    assert bounds.width_mm == 60 and bounds.height_mm == 100
    assert (bounds.min_x_mm + bounds.max_x_mm) / 2 == 10
    assert (bounds.min_y_mm + bounds.max_y_mm) / 2 == -20
    assert transformed.preview.segments[0].start == (0, 0)
    assert transformed.preview.segments[0].end == transformed.geometry.strokes[0].points[0]
    assert not transformed.preview.segments[0].pen_down
    assert transformed.parent_revision_id == original.revision_id
    assert transformed.revision == 2
    original.spec.dimensions.width_mm = 999
    assert service.get(original.revision_id).spec.dimensions.width_mm == 100
    fit = generate_geometry(DrawingSpec(generator="rectangle", dimensions={"width_mm": 100, "height_mm": 60}), DrawingTransform(preserve_aspect=True), Budget())
    assert parse(encode(fit)).bounds.width_mm == parse(encode(fit)).bounds.height_mm == 60


def test_regeneration_seed_lock_and_memory_eviction():
    service = DraftService(max_drafts=2)
    original = generate("Draw a butterfly seed 8", service)
    same = service.revise(original.revision_id, RevisionRequest(regenerate=True, seed_locked=True), Event())
    assert same.gcode == original.gcode and same.spec.seed == 8
    changed = service.revise(same.revision_id, RevisionRequest(regenerate=True), Event())
    assert changed.spec.seed == 9 and changed.gcode != same.gcode
    with pytest.raises(DrawingError, match="expired"):
        service.get(original.revision_id)


def test_budgets_cancel_deadline_complexity_and_post_rounding_collapse():
    event = Event(); event.set()
    with pytest.raises(DrawingError, match="cancelled"):
        generate_geometry(resolve_command("Draw a circle"), DrawingTransform(), Budget(event))
    with pytest.raises(DrawingError, match="too long"):
        generate_geometry(resolve_command("Draw a circle"), DrawingTransform(), Budget(seconds=-1))
    with pytest.raises(DrawingError, match="too small"):
        generate("Draw a circle diameter .00001")
    with pytest.raises(DrawingError, match="20,000 points"):
        generate("Draw an intricate mandala with 64 petals, 2000 mm wide")
    service = DraftService()
    assert service._workers.acquire(False) and service._workers.acquire(False)
    try:
        with pytest.raises(DrawingError, match="already being generated"):
            generate(service=service)
    finally:
        service._workers.release(); service._workers.release()


@pytest.mark.parametrize("code", [
    "G0 Z5\n; X10 Y20\nG0 Z5\n", "G0 Z5\nG1 X10.000 Z0\nG0 Z5\n",
    "G0 Z5\nG0 Y0.000 X0.000 Z5\nG0 Z5\n", "G0 Z5\nG2 X0.000 Y0.000 Z0\nG0 Z5\n",
    "G0 Z5\nG1 XNaN Y0.000 Z0\nG0 Z5\n", "G0 Z5\nG0 X0.000 Y0.000 Z5 F100\nG0 Z5\n",
    "G0 Z5\nG0 X0.000 Y0.000 Z5\nG1 X1.000 Y0.000 Z0\nG0 Z5",
    "G0 Z5\nG0 X0.000 Y0.000 Z5\nG1 X-0.000 Y1.000 Z0\nG0 Z5\n",
    "G0 Z5\nG0 X1e2 Y0.000 Z5\nG0 Z5\n", "G0 Z5\n" + " " * 64 + "\nG0 Z5\n",
    "G0 Z5\nG0 X0.000 Y0.000 Z5\nG1 X1.000 Y0.000 Z0\nG0 Z5\n",  # never returns to the page centre
    "G0 Z5\nG0 X0.000 Y0.000 Z5\nG1 X1.000 Y0.000 Z0\nG1 X0.000 Y0.000 Z0\n",  # returns with the pen down
])
def test_strict_parser_rejects_unsafe_or_noncanonical_input(code):
    with pytest.raises(DrawingError):
        parse(code)


def test_supplied_mandala_header_cannot_execute_through_strict_parser():
    code = (Path(__file__).resolve().parents[1] / "SdCard/01 Test GCode/mandala_11x14.gcode").read_text()
    assert re.search(r";[^\n]*X[^\n]*Y", code)
    with pytest.raises(DrawingError):
        parse(code)


def test_svg_uses_exported_y_orientation_and_metadata():
    service = DraftService()
    draft = generate("Draw a butterfly", service)
    xml = ET.fromstring(service.export(draft.revision_id).svg_bytes)
    metadata = xml.find('{http://www.w3.org/2000/svg}metadata')
    assert '"execution_ready": false' in metadata.text
    first = next(segment for segment in draft.preview.segments if segment.pen_down)
    path = xml.find('{http://www.w3.org/2000/svg}path')
    assert path.attrib['d'].startswith(f'M{first.start[0]:.3f},{-first.start[1]:.3f}')


def test_roundtrip_detects_unexpected_initial_travel():
    draft = generate()
    tampered = draft.gcode.replace('G0 Z5\n', 'G0 Z5\nG0 X10.000 Y10.000 Z5\n', 1)
    with pytest.raises(DrawingError, match="do not match"):
        verify_roundtrip(draft.geometry, parse(tampered))


def test_cubic_flattening_respects_control_hull_tolerance():
    from backend.app.drawing.geometry import cubic_value, flatten_cubic
    controls = ((0, 0), (30, 80), (80, -30), (100, 0))
    points = [controls[0]]
    flatten_cubic(*controls, .04, points, Budget())
    for i in range(1001):
        t = i / 1000
        p = tuple(cubic_value(*(point[axis] for point in controls), t) for axis in (0, 1))
        assert min(segment_distance(p, a, b) for a, b in zip(points, points[1:])) <= .04
