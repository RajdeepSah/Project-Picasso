import base64
import math
from threading import Event

import cv2
import numpy as np
import pytest

from backend.app.drawing.errors import DrawingError
from backend.app.drawing.gcode import parse
from backend.app.drawing.service import DraftService
from backend.app.drawing.vectorize import JOIN_PX, LEVELS, _order, image_strokes
from backend.app.main import create_app
from backend.app.models import ImportRequest
from test_phase4_api import connect


def encoded(image, extension='.png'):
    ok, data = cv2.imencode(extension, image)
    assert ok
    return data.tobytes()


def line_art():
    canvas = np.full((400, 600), 255, np.uint8)
    cv2.circle(canvas, (200, 200), 120, 0, 4, cv2.LINE_AA)
    cv2.line(canvas, (380, 80), (560, 320), 0, 4, cv2.LINE_AA)
    return canvas


def photo():
    rng = np.random.default_rng(7)
    canvas = cv2.GaussianBlur(rng.integers(20, 90, (480, 640), dtype=np.uint8), (0, 0), 3)
    cv2.rectangle(canvas, (120, 100), (360, 300), 230, -1)
    cv2.circle(canvas, (480, 330), 90, 180, -1)
    return canvas


def request(data, **options):
    return ImportRequest(filename='picture.png', content=base64.b64encode(data).decode(), kind='image', **options)


def travel(strokes, start):
    total, cursor = 0.0, start
    for stroke in strokes:
        total += math.dist(cursor, stroke[0]); cursor = stroke[-1]
    return total


def test_thin_ink_lines_trace_as_single_centrelines_fitted_and_centred():
    draft = DraftService().import_drawing(request(encoded(line_art()), fit_width_mm=178, fit_height_mm=252), Event())
    # One loop for the circle and one stroke for the line: never both sides of the ink.
    assert draft.preview.strokes <= 3
    assert draft.spec.generator == 'imported' and draft.import_source.dialect == 'image'
    assert abs(draft.preview.bounds.width_mm - 178) <= .002 and draft.preview.bounds.height_mm <= 252
    assert abs(draft.preview.bounds.min_x_mm + draft.preview.bounds.max_x_mm) <= .002
    assert draft.execution_ready is False
    assert parse(draft.gcode).segments == draft.preview.segments  # canonical, firmware-dialect G-code


def test_detail_levels_trade_lines_for_drawing_time_within_budgets():
    data = encoded(photo(), '.jpg')
    results = {level: image_strokes(data, level, Event()) for level in LEVELS}
    points = {level: sum(map(len, strokes)) for level, strokes in results.items()}
    assert 0 < points['low'] <= points['medium'] <= points['high']
    for level, strokes in results.items():
        assert points[level] <= LEVELS[level].points and len(strokes) <= LEVELS[level].strokes
    service = DraftService()
    details = {level: service.import_drawing(request(data, detail=level), Event()).spec.detail for level in LEVELS}
    assert details == {'low': 'sparse', 'medium': 'standard', 'high': 'dense'}


def test_transparent_png_is_drawn_on_white_paper():
    rgba = np.zeros((300, 300, 4), np.uint8)
    cv2.rectangle(rgba, (60, 60), (240, 240), (0, 0, 0, 255), 3)
    assert image_strokes(encoded(rgba), 'medium', Event())


def test_ordering_shortens_travel_and_joins_touching_strokes():
    rng = np.random.default_rng(3)
    strokes = [np.cumsum(rng.normal(0, 4, (8, 2)), axis=0) + rng.uniform(0, 500, 2) for _ in range(120)]
    start = np.array([250.0, 250.0])
    ordered = _order(strokes, start, Event())
    assert travel(ordered, start) < travel(strokes, start) / 3
    assert sum(map(len, ordered)) <= sum(map(len, strokes))
    touching = [np.array([[0.0, 0], [10, 0]]), np.array([[10.0 + JOIN_PX / 2, 0], [20, 0]])]
    assert len(_order(touching, np.zeros(2), Event())) == 1


@pytest.mark.parametrize('content, code', [
    (base64.b64encode(b'not an image').decode(), 'INVALID_IMPORT'),
    ('%%% not base64 %%%', 'INVALID_IMPORT'),
    (base64.b64encode(encoded(np.full((200, 200), 255, np.uint8))).decode(), 'DEGENERATE_PATH'),
])
def test_unreadable_or_empty_images_are_rejected_clearly(content, code):
    with pytest.raises(DrawingError) as error:
        DraftService().import_drawing(ImportRequest(filename='x.png', content=content, kind='image'), Event())
    assert error.value.code == code


def test_cancelled_trace_stops():
    cancel = Event(); cancel.set()
    with pytest.raises(DrawingError) as error:
        image_strokes(encoded(line_art()), 'high', cancel)
    assert error.value.code == 'GENERATION_CANCELLED'


def test_image_import_api_saves_a_resizable_drawing(tmp_path):
    with connect(create_app(frontend_dir=tmp_path)) as client:
        payload = request(encoded(line_art()), detail='low').model_dump()
        draft = client.post('/api/drawings/import', json=payload).json()
        assert draft['import_source']['dialect'] == 'image' and draft['prompt'] == 'Imported picture.png'
        revised = client.post(f'/api/drawings/{draft["revision_id"]}/revisions', json={'spec': {**draft['spec'], 'dimensions': {'width_mm': 90, 'height_mm': 60}}}).json()
        assert revised['revision'] == 2 and abs(revised['preview']['bounds']['width_mm'] - 90) <= .002
        assert client.post('/api/drawings/import', json={**payload, 'kind': 'gcode'}).json()['code'] == 'INVALID_IMPORT'
