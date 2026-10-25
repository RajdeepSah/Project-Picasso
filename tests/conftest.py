"""Every API/launcher test gets isolated application data and SD mirror paths."""
import pytest


@pytest.fixture(autouse=True)
def isolated_app_storage(tmp_path, monkeypatch):
    monkeypatch.setenv('PICASSO_DATA_DIR', str(tmp_path / 'app-data'))
    mirror = tmp_path / 'sd-mirror'
    mirror.mkdir()
    (mirror / 'main.nc').write_bytes(b'original test mirror\n')
    monkeypatch.setenv('PICASSO_MIRROR_DIR', str(mirror))
