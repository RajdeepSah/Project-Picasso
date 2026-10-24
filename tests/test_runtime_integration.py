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
        request = Request(url + "/api/drawings/generate", data=json.dumps({"prompt": "Draw a circle"}).encode(),
                          headers={"Content-Type": "application/json", "Origin": url}, method="POST")
        with pytest.raises(HTTPError) as error:
            opener.open(request, timeout=2)
        assert error.value.code == 501
        assert json.load(error.value)["code"] == "GENERATION_UNAVAILABLE"
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
