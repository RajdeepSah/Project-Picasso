"""Declared linear absolute-mm import, followed by canonical regeneration."""

import hashlib
import math
import re

from ..models import DrawingBounds, DrawingDraft, ImportRequest, ImportedSource, Stroke
from .errors import DrawingError
from .gcode import parse, verify_roundtrip
from .geometry import MAX_POINTS, MAX_STROKES, validate_strokes

WORD = re.compile(r"([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")


def strip_comments(line):
    result, depth = [], 0
    for character in line:
        if character == ';' and depth == 0:
            break
        if character == '(':
            depth += 1
            if depth > 8:
                raise DrawingError("INVALID_IMPORT", "Comment nesting exceeds the import limit.")
        elif character == ')':
            depth -= 1
            if depth < 0:
                raise DrawingError("INVALID_IMPORT", "Unbalanced comment.")
        elif depth == 0:
            result.append(character)
    if depth:
        raise DrawingError("INVALID_IMPORT", "Unclosed parenthesis comment.")
    return ''.join(result).strip().upper()


def linear_paths(content: str):
    if not content.isascii() or len(content) > 1_000_000 or len(content.splitlines()) > 20000:
        raise DrawingError("IMPORT_TOO_LARGE", "G-code import requires ASCII, at most 1 MB and 20,000 lines.")
    x = y = None
    down = False
    mode = None
    ended = False
    records_started = False
    strokes, current = [], []
    for number, raw in enumerate(content.splitlines(), 1):
        line = strip_comments(raw)
        if not line or line == '%':
            continue
        if not records_started and line in ('HTTP://WWW.YZHROBOT.COM YOUZHIHUI', 'HTTPS://WWW.YZHROBOT.COM YOUZHIHUI'):
            continue  # Exact known vendor banner only; never arbitrary text.
        records_started = True
        if ended:
            raise DrawingError("UNSUPPORTED_IMPORT", f"Line {number}: commands after program end are unsupported.")
        matches = list(WORD.finditer(line))
        if not matches or WORD.sub('', line).strip():
            raise DrawingError("INVALID_IMPORT", f"Line {number}: malformed or unsupported G-code text.")
        values, codes = {}, []
        for match in matches:
            letter, value_text = match.groups()
            value = float(value_text)
            if not math.isfinite(value):
                raise DrawingError("INVALID_IMPORT", f"Line {number}: a number is nonfinite.")
            if letter in ('G', 'M'):
                if not value.is_integer():
                    raise DrawingError("UNSUPPORTED_IMPORT", f"Line {number}: unsupported fractional command.")
                codes.append((letter, int(value)))
            elif letter in ('X', 'Y', 'Z', 'F') and letter not in values:
                values[letter] = value
            else:
                raise DrawingError("UNSUPPORTED_IMPORT", f"Line {number}: unsupported or duplicate word {letter}.")
        motion = [code for letter, code in codes if letter == 'G' and code in (0, 1)]
        if len(motion) > 1:
            raise DrawingError("INVALID_IMPORT", f"Line {number}: multiple motion modes.")
        for letter, code in codes:
            if (letter == 'G' and code not in (0, 1, 17, 21, 90)) or (letter == 'M' and code not in (2, 30)):
                raise DrawingError("UNSUPPORTED_IMPORT", f"Line {number}: {letter}{code} is unsupported. Only absolute-mm XY linear paths and Z pen states can be normalized.")
        if any(letter == 'M' for letter, _ in codes):
            if values or len(codes) != 1:
                raise DrawingError("INVALID_IMPORT", f"Line {number}: program end must be standalone.")
            ended = True
            continue
        if motion:
            mode = motion[0]
        next_down = values.get('Z', -1 if down else 1) <= 0
        if down and not next_down and current:
            strokes.append(current); current = []
        down = next_down
        if 'F' in values and values['F'] <= 0:
            raise DrawingError("INVALID_IMPORT", f"Line {number}: feed must be positive.")
        if 'X' not in values and 'Y' not in values:
            continue
        if mode is None or (x is None and ('X' not in values or 'Y' not in values)):
            raise DrawingError("INVALID_IMPORT", f"Line {number}: the first XY move must establish both axes and a G0/G1 mode.")
        nx, ny = values.get('X', x), values.get('Y', y)
        if max(abs(nx), abs(ny)) > 5000:
            raise DrawingError("INVALID_IMPORT", f"Line {number}: coordinate exceeds the computational import limit.")
        if down:
            if x is None:
                raise DrawingError("INVALID_IMPORT", "Establish a known pen-up XY position before drawing.")
            if not current:
                current = [(x, y)]
            if (nx, ny) != current[-1]:
                current.append((nx, ny))
        x, y = nx, ny
        if len(strokes) > MAX_STROKES or sum(map(len, strokes)) + len(current) > MAX_POINTS:
            raise DrawingError("IMPORT_TOO_LARGE", "Import exceeds the drawing path budget.")
    if current:
        strokes.append(current)
    strokes = [stroke for stroke in strokes if len(stroke) >= 2]
    validate_strokes(strokes)
    return strokes


def parsed_paths(code):
    parse(code)
    # Zero-distance travel can separate strokes; use the linear reader to
    # preserve explicit lift events, not just nonzero preview segments.
    return linear_paths(code)


def import_source(request: ImportRequest) -> ImportedSource:
    notes = ["Pen state is mapped from Z sign; pen-up travel routes are regenerated between strokes.",
             "Feed rates do not control this machine and are omitted from the regenerated export."]
    if request.dialect == 'picasso-json':
        try:
            draft = DrawingDraft.model_validate_json(request.content)
            if hashlib.sha256(draft.gcode.encode('ascii')).hexdigest() != draft.gcode_sha256:
                raise ValueError('G-code checksum mismatch')
            preview = parse(draft.gcode)
            verify_roundtrip(draft.geometry, preview)
            strokes = parsed_paths(draft.gcode)
        except (ValueError, DrawingError) as exc:
            raise DrawingError("INVALID_IMPORT", "This is not an intact supported Picasso draft. JSON preview/readiness claims are never trusted.") from exc
        notes.append("JSON was revalidated from its G-code and imported as a new unverified drawing.")
    elif request.dialect == 'picasso':
        strokes = parsed_paths(request.content)
        notes.append("Strict canonical dialect validated before normalization.")
    else:
        strokes = linear_paths(request.content)
        notes.append("Comments and the exact recognized Youzhihui branding banner were removed; modal XY and absolute-mm setup were resolved. Other unrecognized text is rejected.")
    validate_strokes(strokes)
    xs, ys = zip(*(point for stroke in strokes for point in stroke))
    bounds = DrawingBounds(min_x_mm=min(xs), max_x_mm=max(xs), min_y_mm=min(ys), max_y_mm=max(ys),
                           width_mm=max(xs)-min(xs), height_mm=max(ys)-min(ys))
    cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    normalized = [Stroke(points=[(x-cx, y-cy) for x,y in stroke], closed=stroke[0] == stroke[-1]) for stroke in strokes]
    filename = request.filename.replace('\\', '/').split('/')[-1]
    return ImportedSource(filename=filename, content_sha256=hashlib.sha256(request.content.encode()).hexdigest(),
                          dialect=request.dialect, original_bounds=bounds, input_strokes=normalized, notes=notes)
