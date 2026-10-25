"""Loopback studio and bounded offline drawing API. No hardware or file writes."""

import asyncio
from contextlib import asynccontextmanager, suppress
import os
from pathlib import Path
import platform
import threading
from typing import Literal
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import APP_VERSION
from .models import (ApiError, CapabilitiesResponse, Capability, DrawingDraft, GenerateRequest, RevisionRequest,
                     HealthResponse, MachineStatus, ProfilesResponse, StorageStatus, StudioStatus)
from .profiles import load_reference_profiles
from .drawing.errors import DrawingError
from .drawing.service import DraftService


ROOT = Path(__file__).resolve().parents[2]


def capabilities() -> CapabilitiesResponse:
    def planned(phase: int, reason: str) -> Capability:
        return Capability(available=False, phase=phase, reason=reason)
    return CapabilitiesResponse(
        dashboard=Capability(available=True, phase=2, reason="Local studio and service are available."),
        generation=Capability(available=True, phase=3, reason="Deterministic offline drawing commands are available."),
        history=planned(4, "Saved drawings and revisions arrive in Phase 4."),
        gcode_export=Capability(available=True, phase=3, reason="Unverified draft JSON, SVG and restricted G-code downloads are available. Hardware preparation is unavailable."),
        sd_export=planned(4, "Mounted-card selection and verified export arrive in Phase 4."),
        serial_control=planned(6, "USB control needs hardened firmware and the Phase 6 protocol."),
        ai=planned(7, "Optional AI interpretation arrives in Phase 7."),
        voice=planned(8, "Microphone input arrives in Phase 8."),
    )


def create_app(*, frontend_dir: Path | None = None, instance_id: str | None = None) -> FastAPI:
    build_dir = frontend_dir if frontend_dir is not None else ROOT / "frontend" / "dist"
    run_id = instance_id or os.environ.get("PICASSO_INSTANCE_ID") or uuid.uuid4().hex

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Invalid/missing configuration is a startup error, never healthy defaults.
        app.state.profiles = load_reference_profiles(ROOT)
        app.state.drafts = DraftService()
        yield

    app = FastAPI(title="Project Picasso", version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            own_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
            dev_origin = os.environ.get("PICASSO_DEV_ORIGIN")
            if (parsed.scheme not in ("http", "https") or
                    origin not in {own_origin, dev_origin}):
                return JSONResponse(status_code=403, content=ApiError(
                    code="ORIGIN_REJECTED", message="Use the local Picasso application origin.").model_dump())
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=ApiError(
            code="INVALID_REQUEST", message="Check your command and drawing parameters. Commands need 1–2000 characters; dimensions must be positive and finite, and parameters must apply to the chosen shape.").model_dump())

    @app.exception_handler(DrawingError)
    async def drawing_error(request: Request, exc: DrawingError):
        return JSONResponse(status_code=exc.status, content=ApiError(code=exc.code, message=exc.message).model_dump())

    @app.get("/api/health", response_model=HealthResponse)
    def health():
        return HealthResponse(version=APP_VERSION, instance_id=run_id,
                              frontend_ready=(build_dir / "index.html").is_file(),
                              python_version=platform.python_version())

    @app.get("/api/capabilities", response_model=CapabilitiesResponse)
    def get_capabilities():
        return capabilities()

    @app.get("/api/profiles", response_model=ProfilesResponse)
    def get_profiles():
        return ProfilesResponse(profiles=app.state.profiles)

    @app.get("/api/status", response_model=StudioStatus)
    def get_status():
        return StudioStatus(
            machine=MachineStatus(reason="Serial control is not implemented. No ports have been inspected."),
            storage=StorageStatus(reason="No card is configured. Mount discovery arrives in Phase 4."),
        )

    async def run_generation(http_request: Request, operation, *args):
        cancel = threading.Event()
        async def watch_disconnect():
            # The validated body has been read. Wait for the actual ASGI event
            # instead of a nonblocking is_disconnected() cancellation probe.
            while True:
                message = await http_request.receive()
                if message["type"] == "http.disconnect":
                    cancel.set()
                    return
        watcher = asyncio.create_task(watch_disconnect())
        task = asyncio.create_task(asyncio.to_thread(operation, *args, cancel))
        try:
            return await task
        finally:
            cancel.set()
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            # Retrieve a late failure when the HTTP coroutine itself is cancelled.
            if not task.done():
                task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)

    @app.post("/api/drawings/generate", response_model=DrawingDraft)
    async def generate(request: GenerateRequest, http_request: Request):
        return await run_generation(http_request, app.state.drafts.generate, request)

    @app.post("/api/drawings/{revision_id}/revisions", response_model=DrawingDraft)
    async def revise(revision_id: str, request: RevisionRequest, http_request: Request):
        return await run_generation(http_request, app.state.drafts.revise, revision_id, request)

    @app.get("/api/drawings/{revision_id}", response_model=DrawingDraft)
    def get_draft(revision_id: str):
        return app.state.drafts.get(revision_id)

    @app.get("/api/drawings/{revision_id}/export")
    def export_draft(revision_id: str, format: Literal["json", "svg", "gcode"] = "json"):
        import hashlib
        stored = app.state.drafts.export(revision_id)
        content, media, suffix = {
            "json": (stored.json_bytes, "application/json", "json"),
            "svg": (stored.svg_bytes, "image/svg+xml", "svg"),
            "gcode": (stored.gcode_bytes, "text/plain", "nc"),
        }[format]
        return Response(content, media_type=media, headers={
            "Content-Disposition": f'attachment; filename="{stored.filename}.{suffix}"',
            "X-Picasso-Execution-Ready": "false", "X-Picasso-Content-SHA256": hashlib.sha256(content).hexdigest(),
        })

    if (build_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=build_dir / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        if not (build_dir / "index.html").is_file():
            return JSONResponse(status_code=503, content=ApiError(
                code="FRONTEND_NOT_BUILT", message="Run python3 scripts/setup.py to build the studio.").model_dump())
        return FileResponse(build_dir / "index.html", headers={"Cache-Control": "no-store"})

    return app


app = create_app()
