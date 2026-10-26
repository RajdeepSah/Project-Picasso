#!/usr/bin/env python3
"""Launch the local Picasso studio. Ctrl+C stops every process started here."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import uuid
import webbrowser

from runtime import FRONTEND, PYTHON, ROOT, prerequisites


def check_port(port: int):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if os.name == "posix":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
            listener.listen(1)
        except OSError as exc:
            raise RuntimeError(f"Port {port} is unavailable. Stop its current service or choose --port ANOTHER_PORT.") from exc


def wait_ready(url: str, processes: list[subprocess.Popen], *, instance_id: str | None = None, timeout: float = 20):
    deadline = time.monotonic() + timeout
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("A studio process exited before becoming ready. See its error above; rerun setup if dependencies are missing.")
        try:
            with opener.open(url, timeout=1) as response:
                body = response.read()
                if instance_id:
                    health = json.loads(body)
                    if health.get("application") != "project-picasso" or health.get("instance_id") != instance_id:
                        raise RuntimeError("The selected port belongs to a different service. Choose another port.")
                    if health.get("status") != "ready":
                        raise RuntimeError("The local backend is not ready.")
                return
        except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            time.sleep(.1)
    raise RuntimeError(f"Studio startup timed out waiting for {url}.")


def stop_process(process: subprocess.Popen):
    if os.name == "posix":
        # Every child was started in its own process group, including reload children.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="Run without opening a browser window.")
    parser.add_argument("--dev", action="store_true", help="Run Vite and the backend with live reload.")
    parser.add_argument("--frontend-port", type=int, default=5173, help="Vite port in --dev mode.")
    args = parser.parse_args()
    for port in (args.port, args.frontend_port):
        if not 1 <= port <= 65535:
            parser.error("Ports must be between 1 and 65535.")
    processes: list[subprocess.Popen] = []
    previous_handler = signal.getsignal(signal.SIGTERM)
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        prerequisites(node=args.dev)
        if not PYTHON.is_file():
            raise RuntimeError("Project dependencies are missing. Run python3 scripts/setup.py first.")
        if not args.dev and not (FRONTEND / "dist" / "index.html").is_file():
            raise RuntimeError("The frontend is not built. Run python3 scripts/setup.py first.")
        check_port(args.port)
        if args.dev:
            if args.port == args.frontend_port:
                raise RuntimeError("Backend and frontend ports must be different.")
            check_port(args.frontend_port)
            if not (FRONTEND / "node_modules" / "vite" / "bin" / "vite.js").is_file():
                raise RuntimeError("Frontend dependencies are missing. Run python3 scripts/setup.py first.")
        instance_id = uuid.uuid4().hex
        environment = os.environ.copy()
        environment["PICASSO_INSTANCE_ID"] = instance_id
        environment["PYTHONUNBUFFERED"] = "1"
        if args.dev:
            environment["PICASSO_DEV_ORIGIN"] = f"http://127.0.0.1:{args.frontend_port}"
        else:
            environment.pop("PICASSO_DEV_ORIGIN", None)
        command = [str(PYTHON), "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(args.port), "--no-access-log"]
        if args.dev:
            command += ["--reload", "--reload-dir", str(ROOT / "backend")]
        child_options = {"start_new_session": True} if os.name == "posix" else {}
        processes.append(subprocess.Popen(command, cwd=ROOT, env=environment, **child_options))
        url = f"http://127.0.0.1:{args.port}"
        wait_ready(url + "/api/health", processes, instance_id=instance_id)
        if args.dev:
            environment["PICASSO_API_URL"] = url
            processes.append(subprocess.Popen(["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(args.frontend_port), "--strictPort"], cwd=FRONTEND, env=environment, **child_options))
            url = f"http://127.0.0.1:{args.frontend_port}"
            wait_ready(url, processes)
        print(f"\nProject Picasso is ready: {url}\nPhase 5 · Canonical firmware and commissioning tools. Press Ctrl+C to stop.\n", flush=True)
        if not args.no_browser:
            try:
                if not webbrowser.open(url):
                    print("Open the address above in your browser.", flush=True)
            except webbrowser.Error:
                print("Open the address above in your browser.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(.25)
        raise RuntimeError("A studio process stopped unexpectedly. See the error above.")
    except KeyboardInterrupt:
        print("\nStopping Project Picasso…", flush=True)
        return 0
    except (RuntimeError, OSError) as exc:
        print(f"\nCannot start Picasso: {exc}", file=sys.stderr)
        return 1
    finally:
        for process in reversed(processes):
            stop_process(process)
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
