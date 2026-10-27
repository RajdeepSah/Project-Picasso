"""Strict Picasso dialect only. The legacy sketch is not a standards parser."""

import math
import re

from ..models import DrawingBounds, ExecutionPreview, ExecutionSegment, PolylineDrawing
from .errors import DrawingError
from .geometry import MAX_COORDINATE, MAX_PATH_MM, MAX_POINTS, Budget, validate_strokes

MAX_BYTES = 1_000_000
DECIMAL = r"-?(?:0|[1-9]\d*)\.\d{3}"
MOVE = re.compile(rf"G([01]) X({DECIMAL}) Y({DECIMAL}) Z([05])")


def encode(drawing: PolylineDrawing) -> str:
    validate_strokes([stroke.points for stroke in drawing.strokes])
    def number(value):
        return f"{round(value, 3) or 0.0:.3f}"
    lines = ["G0 Z5"]
    for stroke in drawing.strokes:
        x, y = stroke.points[0]
        lines.append(f"G0 X{number(x)} Y{number(y)} Z5")
        lines.extend(f"G1 X{number(x)} Y{number(y)} Z0" for x, y in stroke.points[1:])
        lines.append("G0 Z5")
    code = "\n".join(lines) + "\n"
    if len(code) > MAX_BYTES:
        raise DrawingError("DRAWING_TOO_COMPLEX", "Export exceeds the 2 MB draft limit.")
    return code


def parse(code: str, *, expected_start=(0.0, 0.0), budget: Budget | None = None) -> ExecutionPreview:
    def invalid(message="Only canonical G0/G1 explicit X/Y/Z commands are accepted. Comments, modal axes, feed words and arcs are unsupported."):
        raise DrawingError("INVALID_GCODE", message)
    if not isinstance(code, str) or not code.isascii() or len(code) > MAX_BYTES:
        invalid("G-code must be ASCII and no larger than 2 MB.")
    if not code.startswith("G0 Z5\n") or not code.endswith("G0 Z5\n"):
        invalid("A file must begin and end with G0 Z5 and a final LF.")
    position = tuple(expected_start)
    if len(position) != 2 or any(not math.isfinite(value) or abs(value) > MAX_COORDINATE for value in position):
        invalid("The expected starting position is invalid.")
    pen_down, positioned = False, False
    segments = []
    drawn_points = []
    drawing_length = travel_length = 0.0
    strokes = lifts = motions = 0
    for line in code.split("\n")[:-1]:
        if budget:
            budget.check()
        if not line or len(line) > 63:
            invalid("Empty or oversized G-code line; maximum payload is 63 ASCII bytes.")
        if line == "G0 Z5":
            if pen_down:
                lifts += 1
            pen_down = False
            positioned = False
            continue
        match = MOVE.fullmatch(line)
        if not match:
            invalid()
        mode, x_text, y_text, z = match.groups()
        if (mode, z) not in (("0", "5"), ("1", "0")) or "-0.000" in (x_text, y_text):
            invalid()
        endpoint = (float(x_text), float(y_text))
        if any(not math.isfinite(value) or abs(value) > MAX_COORDINATE for value in endpoint):
            invalid("Coordinate exceeds the computational preview limit.")
        motions += 1
        if motions > MAX_POINTS:
            invalid("Too many movement records.")
        down = mode == "1"
        if down and not positioned:
            invalid("Every stroke needs an explicit pen-up travel to its starting point.")
        if not down and pen_down:
            invalid("Raise the pen explicitly before travelling to a new stroke.")
        distance = math.dist(position, endpoint)
        if down:
            if not pen_down:
                strokes += 1
            drawn_points.extend([position, endpoint])
            drawing_length += distance
        else:
            travel_length += distance
            positioned = True
        pen_down = down
        if distance > 0:
            segments.append(ExecutionSegment(start=position, end=endpoint, pen_down=down))
        position = endpoint
    if not drawn_points or drawing_length <= 0:
        invalid("No nonzero drawing segments were found.")
    if drawing_length + travel_length > MAX_PATH_MM:
        invalid("Total drawing and travel exceeds 250 metres.")
    xs, ys = zip(*drawn_points)
    bounds = DrawingBounds(min_x_mm=min(xs), max_x_mm=max(xs), min_y_mm=min(ys), max_y_mm=max(ys),
                           width_mm=max(xs) - min(xs), height_mm=max(ys) - min(ys))
    return ExecutionPreview(expected_start_mm=expected_start, segments=segments, bounds=bounds,
                            drawing_distance_mm=drawing_length, travel_distance_mm=travel_length,
                            strokes=strokes, pen_lifts=lifts)


def verify_roundtrip(drawing: PolylineDrawing, preview: ExecutionPreview):
    expected = []
    position = tuple(preview.expected_start_mm)
    for stroke in drawing.strokes:
        first = tuple(stroke.points[0])
        if position != first:
            expected.append((position, first, False))
        expected.extend((tuple(a), tuple(b), True) for a, b in zip(stroke.points, stroke.points[1:]) if a != b)
        position = tuple(stroke.points[-1])
    actual = [(tuple(segment.start), tuple(segment.end), segment.pen_down) for segment in preview.segments]
    if expected != actual or len(drawing.strokes) != preview.strokes or preview.pen_lifts != preview.strokes:
        raise DrawingError("EXPORT_MISMATCH", "Exported paths do not match the drawing. No draft was stored.", 500)
