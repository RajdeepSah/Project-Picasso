"""Voice input returns reviewable text only; it never generates, prepares or moves anything."""
from contextlib import contextmanager
import io
import math
from types import SimpleNamespace
import struct
import threading
import wave

from fastapi.testclient import TestClient
import pytest

from backend.app.drawing.errors import DrawingError
from backend.app.main import create_app
from backend.app.voice import DEFAULT_MODEL_DIR, MAX_SECONDS, VoiceService, normalize


def wav(seconds=1.0, rate=16000, tone=440.0):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes(b''.join(struct.pack('<h', int(8000 * math.sin(2 * math.pi * tone * i / rate))) for i in range(int(seconds * rate))))
    return buffer.getvalue()


class FakeWhisper:
    def __init__(self, *texts):
        self.texts, self.calls = texts, []

    def transcribe(self, samples, **options):
        self.calls.append((samples, options))
        return iter(SimpleNamespace(text=text) for text in self.texts), None


@contextmanager
def client_for(tmp_path, service):
    with TestClient(create_app(frontend_dir=tmp_path, voice_service=service), base_url='http://127.0.0.1') as client:
        client.headers['X-Picasso-Token'] = client.get('/api/session').json()['write_token']
        yield client


@pytest.fixture
def fake(tmp_path):
    model = FakeWhisper(' Draw a rectangle 100 by 60 millimeters.')
    with client_for(tmp_path, VoiceService(tmp_path, loader=lambda: model)) as client:
        yield client, model


def test_without_model_voice_is_reported_unavailable_and_refused(tmp_path):
    with TestClient(create_app(frontend_dir=tmp_path), base_url='http://127.0.0.1') as client:
        voice = client.get('/api/capabilities').json()['voice']
        assert voice['available'] is False and 'setup.py' in voice['reason']
        token = {'X-Picasso-Token': client.get('/api/session').json()['write_token']}
        assert client.post('/api/voice/warm', headers=token).json()['available'] is False
        response = client.post('/api/voice/transcribe', content=wav(), headers={**token, 'Content-Type': 'audio/wav'})
        assert response.status_code == 503 and response.json()['code'] == 'VOICE_UNAVAILABLE'


def test_transcript_is_normalized_text_and_nothing_is_drawn(fake):
    client, model = fake
    assert client.get('/api/capabilities').json()['voice']['available'] is True
    response = client.post('/api/voice/transcribe', content=wav(1.5, rate=48000), headers={'Content-Type': 'audio/wav'})
    assert response.status_code == 200
    body = response.json()
    assert body['text'] == 'Draw a rectangle 100 x 60 mm'
    assert body['duration_s'] == pytest.approx(1.5, abs=0.05)
    samples, options = model.calls[0]
    assert samples.dtype.name == 'float32' and len(samples) == pytest.approx(24000, abs=200)  # resampled to 16 kHz mono
    assert options['language'] == 'en' and options['vad_filter'] is True
    assert client.get('/api/drawings').json()['total'] == 0
    assert client.get('/api/machine').json()['connection'] == 'disconnected'


def test_transcription_requires_the_local_write_token_and_origin(fake):
    client, _ = fake
    assert client.post('/api/voice/transcribe', content=wav(), headers={'X-Picasso-Token': 'wrong'}).status_code == 403
    assert client.post('/api/voice/transcribe', content=wav(), headers={'Origin': 'https://untrusted.example'}).status_code == 403


@pytest.mark.parametrize('audio, code, status', [
    (b'', 'VOICE_AUDIO_INVALID', 422),
    (b'not audio at all' * 10, 'VOICE_AUDIO_INVALID', 422),
    (b'\0' * 4_000_001, 'VOICE_TOO_LONG', 413),
    (wav(MAX_SECONDS + 2, rate=8000), 'VOICE_TOO_LONG', 413),
])
def test_bad_recordings_are_rejected_with_specific_codes(fake, audio, code, status):
    client, model = fake
    response = client.post('/api/voice/transcribe', content=audio, headers={'Content-Type': 'audio/webm'})
    assert (response.status_code, response.json()['code']) == (status, code)
    assert not model.calls


def test_silence_reports_no_speech(tmp_path):
    with client_for(tmp_path, VoiceService(tmp_path, loader=lambda: FakeWhisper())) as client:
        response = client.post('/api/voice/transcribe', content=wav(), headers={'Content-Type': 'audio/wav'})
        assert response.status_code == 422 and response.json()['code'] == 'VOICE_NO_SPEECH'


def test_broken_model_is_reported_not_retried_silently(tmp_path):
    def broken():
        raise RuntimeError('model.bin is truncated')
    service = VoiceService(tmp_path, loader=broken)
    with pytest.raises(DrawingError) as error:
        service.model()
    assert error.value.code == 'VOICE_UNAVAILABLE'
    assert service.capability().available is False and 'truncated' in service.capability().reason


def test_cancelled_request_stops_between_segments(tmp_path):
    service = VoiceService(tmp_path, loader=lambda: FakeWhisper('Draw a', ' circle'))
    cancel = threading.Event(); cancel.set()
    with pytest.raises(DrawingError) as error:
        service.transcribe(wav(), cancel)
    assert error.value.code == 'VOICE_CANCELLED'


@pytest.mark.parametrize('spoken, written', [
    ('Draw a butterfly.', 'Draw a butterfly'),
    ('"Draw an ellipse 120 mm by 80 mm!"', 'Draw an ellipse 120 x 80 mm'),
    ('Create a mandala 1,200 millimetres wide.', 'Create a mandala 1200 mm wide'),
    ('  draw   a  spiral with 5 turns ', 'draw a spiral with 5 turns'),
])
def test_spoken_forms_become_the_command_grammar(spoken, written):
    assert normalize(spoken) == written


@pytest.mark.skipif(not (DEFAULT_MODEL_DIR / 'model.bin').is_file(), reason='offline speech model not installed (python3 scripts/setup.py)')
def test_installed_model_loads_offline_and_ignores_a_pure_tone(monkeypatch):
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    service = VoiceService(DEFAULT_MODEL_DIR)
    assert service.capability().available is True
    with pytest.raises(DrawingError) as error:
        service.transcribe(wav(1.0), threading.Event())
    assert error.value.code == 'VOICE_NO_SPEECH'
