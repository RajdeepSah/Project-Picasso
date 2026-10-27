"""Hybrid routing: offline shapes never touch the network; other requests become AI line art
that is traced and validated locally. Every provider response here is mocked."""
import base64
import json
import threading
import time

import cv2
import httpx
import numpy as np
import pytest

from backend.app.ai import DEFAULT_MODEL, ENDPOINT, ImageService
from backend.app.drawing.errors import DrawingError
from backend.app.drawing.gcode import parse
from backend.app.drawing.service import DraftService
from backend.app.main import create_app
from backend.app.models import GenerateRequest
from test_phase4_api import connect

KEY = 'sk-test-SECRET-never-leaks-0123456789'


def line_art():
    canvas = np.full((1024, 1024), 255, np.uint8)
    cv2.circle(canvas, (512, 420), 260, 0, 6, cv2.LINE_AA)
    cv2.ellipse(canvas, (512, 760), (300, 120), 0, 0, 360, 0, 6, cv2.LINE_AA)
    cv2.line(canvas, (300, 300), (720, 560), 0, 6, cv2.LINE_AA)
    ok, data = cv2.imencode('.jpg', canvas)
    return data.tobytes()


class FakeOpenAI:
    """Records requests and answers like the Images API: base64 image data only."""
    def __init__(self, status=200, body=None, raise_error=None, block: threading.Event | None = None):
        self.calls, self.status, self.raise_error, self.block = [], status, raise_error, block
        self.body = body if body is not None else {'created': 1, 'data': [{'b64_json': base64.b64encode(line_art()).decode()}]}

    def __call__(self, request: httpx.Request):
        self.calls.append(request)
        if self.block is not None:
            self.block.wait(5)
        if self.raise_error is not None:
            raise self.raise_error
        return httpx.Response(self.status, json=self.body)


def service(fake, key=KEY, **options):
    return ImageService(key, transport=httpx.MockTransport(fake), **options)


@pytest.fixture
def ai_client(tmp_path):
    fake = FakeOpenAI()
    with connect(create_app(frontend_dir=tmp_path, image_service=service(fake))) as client:
        yield client, fake


def test_without_a_key_everything_offline_still_works_and_nothing_is_sent(tmp_path):
    with connect(create_app(frontend_dir=tmp_path)) as client:
        ai = client.get('/api/capabilities').json()['ai']
        assert ai['available'] is False and 'OPENAI_API_KEY' in ai['reason']
        assert client.post('/api/drawings/generate', json={'prompt': 'Draw a butterfly'}).json()['title'] == 'Butterfly'
        error = client.post('/api/drawings/generate', json={'prompt': 'Draw a cat on a skateboard'}).json()
        assert error['code'] == 'UNSUPPORTED_COMMAND' and 'OPENAI_API_KEY' in error['message']
        response = client.post('/api/drawings/generate', json={'prompt': 'Draw a cat', 'mode': 'ai'})
        assert response.status_code == 503 and response.json()['code'] == 'AI_UNAVAILABLE'


@pytest.mark.parametrize('prompt', ['Draw a butterfly', 'Create a mandala with 12 petals, 120 mm wide', 'Draw a circle diameter 100'])
def test_simple_shapes_stay_local_even_with_a_key(ai_client, prompt):
    client, fake = ai_client
    draft = client.post('/api/drawings/generate', json={'prompt': prompt}).json()
    assert draft['spec']['generator'] != 'imported' and draft['import_source'] is None
    assert fake.calls == []


def test_errors_in_a_known_shape_are_not_sent_to_the_ai(ai_client):
    client, fake = ai_client
    assert client.post('/api/drawings/generate', json={'prompt': 'Draw a circle diameter 100 width 80'}).json()['code'] == 'AMBIGUOUS_COMMAND'
    assert client.post('/api/drawings/generate', json={'prompt': 'Draw a mandala with 2 petals'}).json()['code'] == 'INVALID_PARAMETER'
    assert client.post('/api/drawings/generate', json={'prompt': 'Draw a cat', 'mode': 'offline'}).json()['code'] == 'UNSUPPORTED_COMMAND'
    assert fake.calls == []


def test_complex_request_becomes_traced_validated_line_art_that_never_executes(ai_client):
    client, fake = ai_client
    assert client.get('/api/capabilities').json()['ai']['available'] is True
    draft = client.post('/api/drawings/generate', json={'prompt': 'Draw a cat on a skateboard', 'detail': 'high',
                                                        'fit_width_mm': 150, 'fit_height_mm': 200}).json()
    assert len(fake.calls) == 1
    sent = fake.calls[0]
    assert str(sent.url) == ENDPOINT and sent.headers['authorization'] == f'Bearer {KEY}'
    body = json.loads(sent.content)
    assert body['model'] == DEFAULT_MODEL and body['quality'] == 'high' and body['n'] == 1
    assert 'cat on a skateboard' in body['prompt'] and 'no shading' in body['prompt']
    # Traced locally into the same canonical, firmware-dialect pipeline as an imported image.
    assert draft['title'] == 'Cat on a skateboard' and draft['prompt'] == 'Draw a cat on a skateboard'
    assert draft['spec']['generator'] == 'imported' and draft['spec']['detail'] == 'dense'
    source = draft['import_source']
    assert source['dialect'] == 'ai-image' and source['ai']['model'] == DEFAULT_MODEL and source['ai']['quality'] == 'high'
    assert max(draft['preview']['bounds']['width_mm'], draft['preview']['bounds']['height_mm']) <= 200.002
    assert json.loads(parse(draft['gcode']).model_dump_json())['segments'] == draft['preview']['segments']
    assert draft['execution_ready'] is False
    # It is saved to history like any other drawing, but nothing was prepared or started.
    assert client.get('/api/drawings?query=skateboard').json()['total'] == 1
    assert client.get('/api/jobs').json() == [] and client.get('/api/machine').json()['run'] is None
    # The key never reaches the browser, history or exports.
    for path in ('/api/capabilities', f'/api/drawings/{draft["revision_id"]}', f'/api/drawings/{draft["revision_id"]}/export?format=json', '/api/drawings'):
        assert KEY not in client.get(path).text


def test_ai_drawings_resize_locally_and_regeneration_asks_for_a_new_command(ai_client):
    client, fake = ai_client
    draft = client.post('/api/drawings/generate', json={'prompt': 'A lighthouse on a cliff', 'mode': 'ai'}).json()
    revised = client.post(f'/api/drawings/{draft["revision_id"]}/revisions',
                          json={'spec': {**draft['spec'], 'dimensions': {'width_mm': 80, 'height_mm': 80}}}).json()
    assert revised['revision'] == 2 and revised['title'] == draft['title'] and revised['import_source']['ai'] == draft['import_source']['ai']
    error = client.post(f'/api/drawings/{draft["revision_id"]}/revisions', json={'regenerate': True}).json()
    assert error['code'] == 'UNSUPPORTED_REGENERATION' and 'new AI image' in error['message']
    assert len(fake.calls) == 1  # resizing never calls the provider again


@pytest.mark.parametrize('detail, spec_detail', [('low', 'sparse'), ('medium', 'standard'), ('high', 'dense')])
def test_detail_level_drives_provider_quality_and_tracing(detail, spec_detail):
    fake = FakeOpenAI()
    draft = DraftService(images=service(fake)).generate(GenerateRequest(prompt='A tree', detail=detail), threading.Event())
    assert json.loads(fake.calls[0].content)['quality'] == detail
    assert draft.spec.detail == spec_detail and draft.import_source.ai.quality == detail


def test_detail_default_applies_to_offline_shapes_unless_the_command_names_one():
    drafts = DraftService()
    assert drafts.generate(GenerateRequest(prompt='Draw a mandala', detail='low'), threading.Event()).spec.detail == 'sparse'
    assert drafts.generate(GenerateRequest(prompt='Draw an intricate mandala', detail='low'), threading.Event()).spec.detail == 'dense'


@pytest.mark.parametrize('fake, code', [
    (FakeOpenAI(401, {'error': {'message': f'Incorrect API key provided: {KEY}', 'code': 'invalid_api_key'}}), 'AI_KEY_INVALID'),
    (FakeOpenAI(429, {'error': {'message': 'quota', 'code': 'insufficient_quota'}}), 'AI_QUOTA'),
    (FakeOpenAI(429, {'error': {'message': 'slow down', 'type': 'rate_limit_exceeded'}}), 'AI_RATE_LIMITED'),
    (FakeOpenAI(400, {'error': {'message': 'blocked', 'code': 'moderation_blocked'}}), 'AI_REJECTED'),
    (FakeOpenAI(400, {'error': {'message': f'Bad size; key {KEY}', 'code': 'invalid_value'}}), 'AI_REQUEST_FAILED'),
    (FakeOpenAI(500, {'error': {'message': 'oops'}}), 'AI_PROVIDER_ERROR'),
    (FakeOpenAI(200, {'data': []}), 'AI_RESPONSE_INVALID'),
    (FakeOpenAI(200, {'data': [{'b64_json': '%%% not base64'}]}), 'AI_RESPONSE_INVALID'),
    (FakeOpenAI(200, {'data': [{'b64_json': base64.b64encode(b'not an image').decode()}]}), 'INVALID_IMPORT'),
    (FakeOpenAI(raise_error=httpx.ConnectError('offline')), 'AI_OFFLINE'),
    (FakeOpenAI(raise_error=httpx.ReadTimeout('slow')), 'AI_TIMEOUT'),
])
def test_provider_failures_are_clear_and_never_reveal_the_key(tmp_path, fake, code):
    with connect(create_app(frontend_dir=tmp_path, image_service=service(fake))) as client:
        response = client.post('/api/drawings/generate', json={'prompt': 'Draw a dragon'})
        assert response.json()['code'] == code and KEY not in response.text
        assert client.get('/api/drawings').json()['total'] == 0  # nothing half-saved


def test_cancelling_returns_immediately_without_saving():
    release = threading.Event()
    drafts = DraftService(images=service(FakeOpenAI(block=release)))
    cancel = threading.Event()
    threading.Timer(.2, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(DrawingError) as error:
        drafts.generate(GenerateRequest(prompt='A sailing ship'), cancel)
    release.set()
    assert error.value.code == 'GENERATION_CANCELLED' and time.monotonic() - started < 2


def test_one_ai_request_at_a_time():
    release = threading.Event()
    images = service(FakeOpenAI(block=release))
    first = threading.Thread(target=lambda: images.generate('A ship', 'low', threading.Event()))
    first.start()
    time.sleep(.1)
    with pytest.raises(DrawingError) as error:
        images.generate('A second ship', 'low', threading.Event())
    release.set(); first.join()
    assert error.value.code == 'AI_BUSY'


def test_key_and_switches_come_from_environment_or_dotenv(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text(f'# comment\nexport OPENAI_API_KEY="{KEY}"\nPICASSO_OPENAI_IMAGE_MODEL=gpt-image-2.5-sunburst\n')
    monkeypatch.setenv('PICASSO_ENV_FILE', str(env))
    images = ImageService.from_environment()
    assert images.available() and images.model == 'gpt-image-2.5-sunburst'
    assert KEY not in repr(images) and KEY not in images.capability().reason
    monkeypatch.setenv('PICASSO_AI', 'off')
    assert not ImageService.from_environment().available()
    monkeypatch.delenv('PICASSO_AI')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-from-environment')
    assert ImageService.from_environment()._key == 'sk-from-environment'
