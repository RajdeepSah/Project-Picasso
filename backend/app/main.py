"""Loopback-only dashboard API. No hardware discovery or writes in Phase 2."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
import platform
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import APP_VERSION
from .models import (ApiError, CapabilitiesResponse, Capability, GenerateRequest,
                     HealthResponse, MachineStatus, ProfilesResponse, StorageStatus, StudioStatus)
from .profiles import load_reference_profiles


ROOT = Path(__file__).resolve().parents[2]


def capabilities() -> CapabilitiesResponse:
    def planned(phase: int, reason: str) -> Capability:
        return Capability(available=False, phase=phase, reason=reason)
    return CapabilitiesResponse(
        dashboard=Capability(available=True, phase=2, reason="Local studio and service are available."),
        generation=planned(3, "Offline drawing generation arrives in Phase 3. No drawing has been generated."),
        history=planned(4, "Saved drawings and revisions arrive in Phase 4."),
        gcode_export=planned(3, "The compatible G-code exporter arrives in Phase 3."),
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
            code="INVALID_REQUEST", message="Provide a drawing command between 1 and 2000 characters.").model_dump())

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

    @app.post("/api/drawings/generate", response_model=ApiError, status_code=501)
    def generate(request: GenerateRequest):
        return ApiError(code="GENERATION_UNAVAILABLE", phase=3,
                        message=capabilities().generation.reason)

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
