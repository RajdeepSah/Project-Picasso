from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from picasso import check_port, wait_ready  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_occupied_port_fails_clearly_without_starting_or_stopping_another_service():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(RuntimeError, match=f"Port {port} is unavailable"):
            check_port(port)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/picasso.py"), "--no-browser", "--port", str(port)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 1
        assert f"Port {port} is unavailable" in result.stderr
        assert listener.getsockname()[1] == port


def test_backend_exiting_before_readiness_is_a_startup_failure():
    process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    process.wait(timeout=5)
    with pytest.raises(RuntimeError, match="exited before becoming ready"):
        wait_ready("http://127.0.0.1:1/api/health", [process], timeout=.2)


def test_invalid_port_is_rejected_before_launch():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/picasso.py"), "--no-browser", "--port", "70000"], capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert "Ports must be between" in result.stderr
