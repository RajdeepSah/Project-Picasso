"""Exercise the actual launcher and its development proxy after setup/build."""

import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_saved_bytes_and_write_token_across_process_restart():
    """A fresh process reopens the same database; old browser tokens expire."""
    opener = build_opener(ProxyHandler({}))
    draft = old_token = None
    for launch in range(2):
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        process = subprocess.Popen(
            [sys.executable, str(ROOT / 'scripts/picasso.py'), '--no-browser', '--port', str(port)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None, 'Launcher exited during startup'
                try:
                    with opener.open(url + '/api/session', timeout=.5) as response:
                        token = json.load(response)['write_token']
                    break
                except (URLError, TimeoutError, ConnectionError):
                    assert time.monotonic() < deadline
                    time.sleep(.1)
            if launch == 0:
                old_token = token
                request = Request(url + '/api/drawings/generate',
                                  data=json.dumps({'prompt': 'Draw a butterfly seed 19'}).encode(),
                                  headers={'Content-Type': 'application/json', 'X-Picasso-Token': token})
                with opener.open(request, timeout=5) as response:
                    draft = json.load(response)
            else:
                assert token != old_token
                with opener.open(url + '/api/drawings/' + draft['revision_id'], timeout=5) as response:
                    restored = json.load(response)
                assert restored == draft
                request = Request(url + '/api/drawings/generate', data=b'{"prompt":"Draw a circle"}',
                                  headers={'Content-Type': 'application/json', 'X-Picasso-Token': old_token})
                with pytest.raises(HTTPError) as denied:
                    opener.open(request, timeout=5)
                assert denied.value.code == 403
        finally:
            process.terminate()
            try:
                output, _ = process.communicate(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate(timeout=3)
                pytest.fail('Restart test launcher did not shut down')
        assert process.returncode == 0, output


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.mark.skipif(not (ROOT / "frontend/dist/index.html").is_file(), reason="Run scripts/setup.py to build the application first")
@pytest.mark.parametrize("development", [False, True], ids=["built-app", "development-proxy"])
def test_launcher_real_http_and_clean_shutdown(development):
    backend_port = free_port()
    frontend_port = free_port()
    while backend_port == frontend_port:
        frontend_port = free_port()
    url = f"http://127.0.0.1:{frontend_port if development else backend_port}"
    command = [sys.executable, str(ROOT / "scripts/picasso.py"), "--no-browser", "--port", str(backend_port)]
    if development:
        command += ["--dev", "--frontend-port", str(frontend_port)]
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    opener = build_opener(ProxyHandler({}))
    try:
        deadline = time.monotonic() + 20
        while True:
            assert process.poll() is None, "Launcher exited during startup"
            try:
                with opener.open(url + "/api/health", timeout=.5) as response:
                    health = json.load(response)
                break
            except (URLError, TimeoutError, ConnectionError):
                assert time.monotonic() < deadline, "Application did not become ready"
                time.sleep(.1)
        assert health["application"] == "project-picasso"
        assert health["frontend_ready"] is True
        with opener.open(url, timeout=2) as response:
            html = response.read().decode()
        assert "Project Picasso" in html
        assert ("@vite/client" in html) is development
        with opener.open(url + '/api/session', timeout=2) as response:
            token = json.load(response)['write_token']
        request = Request(url + "/api/drawings/generate", data=json.dumps({"prompt": "Draw a circle"}).encode(),
                          headers={"Content-Type": "application/json", "Origin": url, "X-Picasso-Token": token}, method="POST")
        with opener.open(request, timeout=3) as response:
            draft = json.load(response)
        assert draft["execution_ready"] is False
        assert draft["title"] == "Circle"
        assert draft["preview"]["bounds"]["width_mm"] == 120
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate(timeout=3)
            pytest.fail(f"Launcher did not shut down cleanly: {output}")
    assert process.returncode == 0, output
    for port in [backend_port] + ([frontend_port] if development else []):
        with socket.socket() as probe:
            probe.settimeout(.5)
            assert probe.connect_ex(("127.0.0.1", port)) != 0, f"Process still listening on {port}"
