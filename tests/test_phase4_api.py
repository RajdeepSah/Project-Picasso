from contextlib import contextmanager
import json
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient
import pytest

from backend.app.main import create_app
from backend.app.models import ImportRequest, RevisionRequest
from backend.app.drawing.errors import DrawingError
from backend.app.drawing.service import DraftService
from backend.app.storage.repository import sha
from test_phase4_storage import calibration

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def connect(app):
    with TestClient(app, base_url='http://127.0.0.1') as client:
        client.headers['X-Picasso-Token'] = client.get('/api/session').json()['write_token']
        yield client


def test_api_restart_history_pagination_thumbnail_and_repair(tmp_path):
    app = create_app(frontend_dir=tmp_path)
    with connect(app) as client:
        first = client.post('/api/drawings/generate', json={'prompt': 'Draw a circle diameter 83'}).json()
        second = client.post(f'/api/drawings/{first["revision_id"]}/revisions', json={'regenerate': True}).json()
        page = client.get('/api/drawings?limit=1&offset=0&query=83').json()
        assert page['total'] == 2 and len(page['items']) == 1
        assert page['items'][0]['revision_id'] == second['revision_id']
        assert client.get(f'/api/drawings/{first["revision_id"]}/thumbnail').headers['content-type'].startswith('image/svg+xml')
    with connect(create_app(frontend_dir=tmp_path)) as client:
        assert client.get('/api/drawings?query=83').json()['total'] == 2
        assert client.get(f'/api/drawings/{first["revision_id"]}').json() == first
        file = client.app.state.repository.artifact_path(first['revision_id'])/'drawing.nc'
        file.write_bytes(b'corrupt')
        assert client.get(f'/api/drawings/{first["revision_id"]}').json()['code'] == 'ARTIFACT_DAMAGED'
        assert any(item['integrity'] == 'damaged' for item in client.get('/api/drawings').json()['items'])
        assert client.post(f'/api/artifacts/{first["revision_id"]}/repair').status_code == 200
        assert file.read_bytes() == first['gcode'].encode()


def test_api_write_session_and_isolated_test_copy(tmp_path):
    with TestClient(create_app(frontend_dir=tmp_path), base_url='http://127.0.0.1') as client:
        assert client.post('/api/drawings/generate', json={'prompt': 'Draw a circle'}).json()['code'] == 'WRITE_TOKEN_REQUIRED'
        client.headers['X-Picasso-Token'] = client.get('/api/session').json()['write_token']
        assert client.post('/api/drawings/generate', headers={'Origin':'https://outside.example'}, json={'prompt':'Draw a circle'}).status_code == 403
        draft = client.post('/api/drawings/generate', json={'prompt':'Draw a circle'}).json()
        assert client.post('/api/jobs/prepare', json={'revision_id':draft['revision_id']}).json()['code'] == 'PROFILE_UNVERIFIED'
        job = client.post('/api/jobs/prepare', json={'revision_id':draft['revision_id'], 'mode':'simulation'}).json()
        target = client.post('/api/storage/test-target').json()
        result = client.post(f'/api/jobs/{job["id"]}/sd-export', json={'target_id':target['id'], 'expected_job_sha256':job['gcode_sha256'], 'acknowledge_replace':True})
        assert result.status_code == 200
        assert result.json()['status'] == 'verified' and result.json()['target_kind'] == 'test_directory'
        assert (Path(target['path'])/'main.nc').read_bytes() == draft['gcode'].encode()
        assert client.get('/api/storage/transfers').json()[0]['status'] == 'verified'
        assert client.post(f'/api/jobs/{job["id"]}/stage', json={'acknowledge_replace':True}).json()['code'] == 'SIMULATION_ONLY'
        assert client.post('/api/machine/start').status_code == 404


def test_api_measured_profiles_edit_conflict_and_job_restore(tmp_path):
    with connect(create_app(frontend_dir=tmp_path)) as client:
        profile = client.post('/api/profiles', json={'calibration':calibration().model_dump(), 'select_for_preparation':True}).json()
        assert profile['verified'] is True and profile['verification_method'] == 'operator_recorded'
        draft = client.post('/api/drawings/generate', json={'prompt':'Draw a circle diameter 40'}).json()
        response = client.post('/api/jobs/prepare', json={'revision_id':draft['revision_id'], 'profile_id':profile['id'], 'profile_revision':profile['revision']})
        assert response.status_code == 200
        job = response.json()
        assert client.get(f'/api/jobs/{job["id"]}').json() == job
        assert client.get(f'/api/jobs?revision_id={draft["revision_id"]}').json()[0] == job
        changed = calibration(measurement_notes='Changed synthetic measurements with no actual hardware claim.').model_dump()
        assert client.put(f'/api/profiles/{profile["id"]}', json={'calibration':changed, 'expected_revision':'wrong'}).json()['code'] == 'STALE_PROFILE'
        updated = client.put(f'/api/profiles/{profile["id"]}', json={'calibration':changed, 'expected_revision':profile['revision']}).json()
        assert updated['revision'] != profile['revision']
        response = client.post(f'/api/jobs/{job["id"]}/stage', json={'acknowledge_replace':True})
        assert response.json()['code'] == 'STALE_PREPARATION'


def test_import_modal_axes_coordinate_comments_and_explicit_origin():
    service = DraftService()
    content = '; X999 Y999 Z0 are comment text\nG21\nG90\nG0 X10 Y20 Z3\nG1 Z0\nG1 X30\nY40\nX10\nY20\nG0 Z3\nM2\n'
    original = service.import_drawing(ImportRequest(filename='modal.nc',content=content), Event())
    assert original.preview.bounds.min_x_mm == 10 and original.preview.bounds.max_y_mm == 40
    assert original.transform.offset_x_mm == 20 and original.transform.offset_y_mm == 30
    centered = service.import_drawing(ImportRequest(filename='modal.nc',content=content,center_on_origin=True,fit_width_mm=100), Event())
    assert centered.preview.bounds.width_mm == centered.preview.bounds.height_mm == 100
    assert centered.preview.bounds.min_x_mm == centered.preview.bounds.min_y_mm == -50
    assert centered.import_source.original_bounds.min_x_mm == 10
    assert '999' not in centered.gcode
    revised = service.revise(centered.revision_id, RevisionRequest(transform={'rotation_degrees':90,'offset_x_mm':5}),Event())
    assert revised.preview.bounds.min_x_mm == -45
    with pytest.raises(DrawingError): service.revise(centered.revision_id, RevisionRequest(regenerate=True), Event())


def test_import_accepts_up_to_2_mb_of_gcode():
    body = 'G0 X0 Y0 Z1\nG1 X10 Y10 Z0\nG0 Z1\n'
    padding = '; padding comment that keeps the line count low\n'
    fits = padding * ((2_000_000 - len(body)) // len(padding)) + body
    assert len(fits) <= 2_000_000
    DraftService().import_drawing(ImportRequest(filename='large.nc', content=fits), Event())
    with pytest.raises(DrawingError, match='2 MB'):
        DraftService().import_drawing(ImportRequest(filename='large.nc', content=padding * 2 + fits), Event())

@pytest.mark.parametrize('command', ['G2 X1 Y1 I0 J1', 'G91', 'G20', 'G92 X0 Y0', 'M3', 'G4 P100', 'G1 X1 X2 Y1', 'M01'])
def test_import_rejects_unknown_semantics_instead_of_dropping_them(command):
    with pytest.raises(DrawingError):
        DraftService().import_drawing(ImportRequest(filename='bad.nc',content='G0 X0 Y0 Z1\n'+command+'\nG1 X1 Y1 Z0\n'),Event())


def test_supplied_mandala_and_vendor_samples_normalize():
    folder = ROOT/'SdCard/01 Test GCode'
    paths = sorted(folder.rglob('*.nc')) + sorted(folder.rglob('*.gcode')) + [folder/'Washburn logo/Washburn logo.txt']
    for path in paths:
        result = DraftService().import_drawing(ImportRequest(filename=path.name,content=path.read_text(),center_on_origin=True,fit_width_mm=120),Event())
        assert abs(result.preview.bounds.width_mm-120) <= .002
        assert result.execution_ready is False
        assert result.gcode.startswith('G0 Z5\n') and ';' not in result.gcode
        if path.suffix == '.gcode':
            assert result.import_source.original_bounds.width_mm == 252
            assert result.transform.offset_x_mm == result.transform.offset_y_mm == 0


def test_json_draft_reimport_is_new_verified_geometry_but_never_execution_ready():
    service = DraftService()
    from backend.app.models import GenerateRequest
    draft = service.generate(GenerateRequest(prompt='Draw a butterfly'), Event())
    imported = service.import_drawing(ImportRequest(filename='draft.json',content=draft.model_dump_json()),Event())
    assert imported.revision_id != draft.revision_id and imported.spec.generator == 'imported'
    assert imported.gcode_sha256 == draft.gcode_sha256
    assert imported.execution_ready is False
    corrupted = json.loads(draft.model_dump_json()); corrupted['gcode'] += 'G1 X999 Y999\n'
    with pytest.raises(DrawingError): service.import_drawing(ImportRequest(filename='bad.json',content=json.dumps(corrupted)),Event())
