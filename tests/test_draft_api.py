import asyncio
import hashlib
import json
import threading
import time
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.drawing.errors import DrawingError
from backend.app.drawing.service import DraftService


def test_revision_export_and_hardware_boundaries(tmp_path):
    with TestClient(create_app(frontend_dir=tmp_path), base_url="http://127.0.0.1") as client:
        client.headers['X-Picasso-Token'] = client.get('/api/session').json()['write_token']
        draft = client.post('/api/drawings/generate', json={'prompt': 'Draw a mandala with 16 petals seed 5'}).json()
        original_id = draft['revision_id']
        assert client.get(f'/api/drawings/{original_id}').json() == draft
        response = client.post(f'/api/drawings/{original_id}/revisions', json={'regenerate': True})
        assert response.status_code == 200
        revised = response.json()
        assert revised['spec']['seed'] == 6
        assert revised['gcode_sha256'] != draft['gcode_sha256']
        assert revised['parent_revision_id'] == original_id
        width, height = (f"{revised['preview']['bounds'][key]:.0f}" for key in ('width_mm', 'height_mm'))
        assert client.get(f'/api/drawings/{original_id}').json() == draft
        for format in ('json', 'svg', 'gcode', 'png', 'txt'):
            response = client.get(f'/api/drawings/{revised["revision_id"]}/export?format={format}')
            assert response.status_code == 200
            extension = 'nc' if format == 'gcode' else format
            assert f'filename="picasso-mandala-{width}x{height}mm-rev2.{extension}"' in response.headers['content-disposition']
            assert response.headers['x-picasso-execution-ready'] == 'false'
            assert hashlib.sha256(response.content).hexdigest() == response.headers['x-picasso-content-sha256']
            if format == 'json':
                assert response.json() == revised
            elif format == 'svg':
                assert ET.fromstring(response.content).tag.endswith('svg')
            elif format == 'png':
                assert response.content.startswith(b'\x89PNG\r\n\x1a\n')
            else:
                assert response.text == revised['gcode']
                assert response.text.endswith('G0 Z5\nG0 X0.000 Y0.000 Z5\n')
        assert client.post('/api/jobs/prepare', json={'revision_id': original_id}).json()['code'] == 'PROFILE_UNVERIFIED'
        assert client.post('/api/machine/start').status_code == 404
        assert client.post('/api/jobs/anything/sd-export').status_code == 422
        assert client.get('/api/drawings/not-present/export').status_code == 404
        assert client.get(f'/api/drawings/{original_id}/export?format=exe').status_code == 422
        assert client.post('/api/drawings/generate', json={'prompt': 'Draw a cat'}).json()['code'] == 'UNSUPPORTED_COMMAND'
        assert client.post(f'/api/drawings/{original_id}/revisions', json={'transform': {'rotation_degrees': 999}}).status_code == 422


def test_disconnect_cancels_worker_without_storing_a_draft(monkeypatch, tmp_path):
    cancelled = threading.Event()
    def slow(self, request, cancel):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if cancel.wait(.01):
                cancelled.set()
                raise DrawingError('GENERATION_CANCELLED', 'Cancelled', 499)
        raise AssertionError('Disconnect did not signal cancellation')
    monkeypatch.setattr(DraftService, 'generate', slow)
    app = create_app(frontend_dir=tmp_path)
    async def request():
        body = json.dumps({'prompt': 'Draw a circle'}).encode()
        messages = asyncio.Queue()
        messages.put_nowait({'type': 'http.request', 'body': body, 'more_body': False})
        async def disconnect():
            await asyncio.sleep(.06)
            await messages.put({'type': 'http.disconnect'})
        async def receive():
            return await messages.get()
        async def send(message):
            pass
        scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'}, 'http_version': '1.1',
                 'method': 'POST', 'scheme': 'http', 'path': '/api/drawings/generate', 'query_string': b'',
                 'headers': [(b'host', b'127.0.0.1'), (b'content-type', b'application/json'), (b'x-picasso-token', app.state.write_token.encode())],
                 'server': ('127.0.0.1', 8000), 'client': ('127.0.0.1', 1234)}
        async with app.router.lifespan_context(app):
            sender = asyncio.create_task(disconnect())
            await asyncio.wait_for(app(scope, receive, send), timeout=3)
            await sender
            assert cancelled.is_set()
            assert not app.state.drafts._items
    asyncio.run(request())
