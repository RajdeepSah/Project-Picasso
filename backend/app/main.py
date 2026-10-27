"""Local studio with durable artifacts and explicitly managed filesystem exports."""

import asyncio
from contextlib import asynccontextmanager, suppress
import os
from pathlib import Path
import platform
import secrets
import sqlite3
import threading
from typing import Literal
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import APP_VERSION, firmware
from .models import (ApiError, AutoSyncRequest, AutoSyncState, CalibrationProfile, CalibrationSaveRequest,
                     CapabilitiesResponse, Capability, DrawingDraft, ExportRequest, FirmwareInfo, GenerateRequest, HistoryResponse,
                     ImportRequest, PreparationRequest, PreparedJob, ProfileSelectionRequest, RevisionRequest,
                     HealthResponse, MachineStatus, ProfilesResponse, SessionResponse, StageRequest, StudioStatus,
                     StorageTarget, TargetSelectionRequest, TargetsResponse, TransferRecord, ConnectRequest, HomeRequest,
                     MachineState, PortsResponse, SerialPortInfo, UsbRun, UsbStartRequest, VoiceTranscript)
from .machine import transport as serial_transport
from .machine.controller import MachineController
from .profiles import load_reference_profiles
from .drawing.errors import DrawingError
from .drawing.service import DraftService
from .storage.repository import Repository
from .storage.preparation import JobManager, ProfileManager
from .storage.exporter import ExportManager
from .voice import DEFAULT_MODEL_DIR, VoiceService
from .ai import ImageService


ROOT = Path(__file__).resolve().parents[2]


def capabilities(voice: Capability, ai: Capability) -> CapabilitiesResponse:
    return CapabilitiesResponse(
        dashboard=Capability(available=True, phase=2, reason="Local studio and service are available."),
        generation=Capability(available=True, phase=3, reason="Deterministic offline drawing commands are available without a network or API key."),
        history=Capability(available=True, phase=4, reason="Drawings and revisions are saved to local SQLite and checksummed artifacts."),
        gcode_export=Capability(available=True, phase=3, reason="Draft downloads and immutable profile-based preparation are available."),
        sd_export=Capability(available=True, phase=4, reason="Verified managed filesystem export is available. Physical cards require operator-recorded calibration and explicit volume selection; test exports use an isolated directory."),
        firmware=Capability(available=True, phase=5, reason="Canonical firmware source and profile-generated configuration are available. Building, uploading and commissioning are explicit operator steps; no board is contacted."),
        serial_control=Capability(available=True, phase=6, reason="Explicit USB connection to Picasso firmware 0.6+ with acknowledged one-command streaming, pause and stop. Hardware execution remains unverified until commissioning."),
        ai=ai,
        voice=voice,
    )


def create_app(*, frontend_dir: Path | None = None, instance_id: str | None = None, data_dir: Path | None = None, mirror_dir: Path | None = None, target_provider=None, machine_transport=None, simulated_device: bool | None = None, voice_service: VoiceService | None = None, image_service: ImageService | None = None) -> FastAPI:
    build_dir = frontend_dir if frontend_dir is not None else ROOT / "frontend" / "dist"
    run_id = instance_id or os.environ.get("PICASSO_INSTANCE_ID") or uuid.uuid4().hex
    storage_root = data_dir or Path(os.environ.get('PICASSO_DATA_DIR', ROOT / 'data'))
    mirror_root = mirror_dir or Path(os.environ.get('PICASSO_MIRROR_DIR', ROOT / 'SdCard'))
    write_token = secrets.token_urlsafe(32)
    simulated = os.environ.get('PICASSO_SIMULATED_DEVICE') == '1' if simulated_device is None else simulated_device
    voice = voice_service or VoiceService(Path(os.environ.get('PICASSO_VOICE_MODEL_DIR', DEFAULT_MODEL_DIR)))
    images = image_service or ImageService.from_environment()  # the key stays in this process

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Invalid/missing configuration is a startup error, never healthy defaults.
        app.state.profiles = load_reference_profiles(ROOT)
        app.state.repository = Repository(storage_root)
        app.state.drafts = DraftService(repository=app.state.repository, images=images)
        app.state.profile_manager = ProfileManager(app.state.repository, app.state.profiles)
        app.state.jobs = JobManager(app.state.repository, app.state.drafts, app.state.profile_manager)
        app.state.storage = ExportManager(app.state.repository, app.state.jobs, mirror_root, target_provider)
        def open_port(port):
            if machine_transport is not None:
                return machine_transport(port)
            if port == serial_transport.SIMULATED_PORT:
                from .machine.simulated import simulated_transport
                return simulated_transport(storage_root / 'simulator')
            return serial_transport.SerialTransport(port)
        app.state.machine = MachineController(app.state.repository, app.state.jobs, app.state.profile_manager, open_port, simulated)
        async def watch_cards():
            while True:
                await asyncio.sleep(2)
                await asyncio.to_thread(app.state.storage.poll_auto_sync)
        watcher = asyncio.create_task(watch_cards())
        try:
            yield
        finally:
            await asyncio.to_thread(app.state.machine.shutdown)  # best-effort STOP of an active run
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher

    app = FastAPI(title="Project Picasso", version=APP_VERSION, lifespan=lifespan)
    app.state.write_token = write_token
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
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if not secrets.compare_digest(request.headers.get('X-Picasso-Token', ''), write_token):
                return JSONResponse(status_code=403, content=ApiError(code='WRITE_TOKEN_REQUIRED', message='Reconnect to obtain the current local write session.').model_dump())
            try:
                length = int(request.headers.get('content-length', '0') or '0')
            except ValueError:
                length = -1
            if length < 0 or length > 12_000_000:
                return JSONResponse(status_code=413, content=ApiError(code='IMPORT_TOO_LARGE', message='Request exceeds the 12 MB limit.').model_dump())
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        if request.url.path.startswith('/api/profiles'):
            message = 'Check the measured profile, bounds, rope limits and required verification checks. '
            message += exc.errors()[0]['msg'].removeprefix('Value error, ')
        elif request.url.path == '/api/drawings/import':
            message = 'Choose a G-code file or an image of at most 8 MB.'
        else:
            message = 'Check your command and drawing parameters. Commands need 1–2000 characters; dimensions must be positive and finite, and parameters must apply to the chosen shape.'
        return JSONResponse(status_code=422, content=ApiError(
            code="INVALID_REQUEST", message=message).model_dump())

    @app.exception_handler(DrawingError)
    async def drawing_error(request: Request, exc: DrawingError):
        return JSONResponse(status_code=exc.status, content=ApiError(code=exc.code, message=exc.message).model_dump())

    @app.exception_handler(OSError)
    @app.exception_handler(sqlite3.Error)
    async def storage_failure(request: Request, exc: Exception):
        return JSONResponse(status_code=507, content=ApiError(code='LOCAL_STORAGE_ERROR', message='Local storage could not complete this operation. Check free space, permissions and recovery status; no success is claimed.').model_dump())

    @app.get('/api/session', response_model=SessionResponse)
    def session():
        return SessionResponse(write_token=write_token)

    @app.get("/api/health", response_model=HealthResponse)
    def health():
        return HealthResponse(version=APP_VERSION, instance_id=run_id,
                              frontend_ready=(build_dir / "index.html").is_file(),
                              python_version=platform.python_version())

    @app.get("/api/capabilities", response_model=CapabilitiesResponse)
    def get_capabilities():
        return capabilities(voice.capability(), images.capability())

    @app.get("/api/profiles", response_model=ProfilesResponse)
    def get_profiles():
        measured = app.state.profile_manager.all()
        info = FirmwareInfo(version=firmware.FIRMWARE_VERSION, config_ids={profile.id: firmware.config_id(profile) for profile in [*app.state.profiles, *measured]},
                            reason="Configuration IDs fingerprint the values compiled into canonical firmware. The machine shows its ID on the Info screen.")
        return ProfilesResponse(profiles=app.state.profiles, measured_profiles=measured, active_profile_id=app.state.repository.setting('active_profile'), firmware=info)

    @app.get('/api/profiles/{profile_id}/firmware-config')
    def firmware_config(profile_id: str):
        references = {profile.id: profile for profile in app.state.profiles}
        if profile_id in references:
            profile, kind = references[profile_id], 'source reference (no workspace)'
        else:
            profile = app.state.profile_manager.get(profile_id)
            kind = 'verified measured' if profile.verified else 'unverified measured'
        return Response(firmware.render(profile, kind=kind), media_type='text/x-c', headers={
            'Content-Disposition': f'attachment; filename="{firmware.CONFIG_FILENAME}"',
            'X-Picasso-Firmware-Config-Id': firmware.config_id(profile), 'X-Picasso-Hardware-Verified': 'false'})

    @app.post('/api/profiles', response_model=CalibrationProfile)
    def create_profile(request: CalibrationSaveRequest):
        return app.state.profile_manager.save(request)

    @app.put('/api/profiles/{profile_id}', response_model=CalibrationProfile)
    def update_profile(profile_id: str, request: CalibrationSaveRequest):
        return app.state.profile_manager.save(request, profile_id)

    @app.post('/api/profiles/select', response_model=ProfilesResponse)
    def select_profile(request: ProfileSelectionRequest):
        app.state.profile_manager.select(request.profile_id, request.expected_revision)
        return get_profiles()

    @app.get("/api/status", response_model=StudioStatus)
    def get_status():
        machine = app.state.machine.state()
        return StudioStatus(
            machine=MachineStatus(state=machine.connection, reason=machine.message, discovery_performed=False,
                                  position_known=bool(machine.status and machine.status.origin != 'UNSET')),
            storage=app.state.storage.status(),
        )

    def listed_ports():
        return serial_transport.list_ports(simulated)

    @app.get('/api/machine/ports', response_model=PortsResponse)
    def machine_ports():
        try:
            ports = listed_ports()
        except Exception as exc:  # enumeration only; nothing is opened
            return PortsResponse(ports=[], error=f'Port enumeration failed: {exc}')
        return PortsResponse(ports=[SerialPortInfo(**vars(port)) for port in ports])

    @app.get('/api/machine', response_model=MachineState)
    def machine_state():
        return app.state.machine.state()

    @app.post('/api/machine/connect', response_model=MachineState)
    async def machine_connect(request: ConnectRequest):
        # Only a currently listed port can be opened; arbitrary paths are refused.
        if machine_transport is None and request.port not in {port.device for port in listed_ports()}:
            raise DrawingError('PORT_NOT_LISTED', 'Select a port from the current list, then connect.', 404)
        return await asyncio.to_thread(app.state.machine.connect, request.port)

    @app.post('/api/machine/disconnect', response_model=MachineState)
    async def machine_disconnect():
        return await asyncio.to_thread(app.state.machine.disconnect)

    @app.post('/api/machine/home', response_model=MachineState)
    async def machine_home(request: HomeRequest):
        return await asyncio.to_thread(app.state.machine.home, request)

    @app.post('/api/machine/pause', response_model=MachineState)
    async def machine_pause():
        return await asyncio.to_thread(app.state.machine.pause)

    @app.post('/api/machine/resume', response_model=MachineState)
    async def machine_resume():
        return await asyncio.to_thread(app.state.machine.resume)

    @app.post('/api/machine/stop', response_model=MachineState)
    async def machine_stop():
        return await asyncio.to_thread(app.state.machine.stop)

    @app.post('/api/jobs/{job_id}/usb-start', response_model=UsbRun)
    async def usb_start(job_id: str, request: UsbStartRequest):
        return await asyncio.to_thread(app.state.machine.start, job_id, request)

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

    @app.post('/api/drawings/import', response_model=DrawingDraft)
    async def import_drawing(request: ImportRequest, http_request: Request):
        return await run_generation(http_request, app.state.drafts.import_drawing, request)

    @app.post('/api/voice/warm', response_model=Capability)
    def voice_warm():
        return voice.warm()

    @app.post('/api/voice/transcribe', response_model=VoiceTranscript)
    async def voice_transcribe(http_request: Request):
        # Raw recorded audio (webm/ogg/mp4/wav). The result is text for review; nothing is generated or drawn.
        audio = await http_request.body()
        return await run_generation(http_request, voice.transcribe, audio)

    @app.get('/api/drawings', response_model=HistoryResponse)
    def history(query: str = Query(default='', max_length=200), offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=50), drawing_id: str | None = None):
        return app.state.repository.history(query, offset, limit, drawing_id)

    @app.post("/api/drawings/{revision_id}/revisions", response_model=DrawingDraft)
    async def revise(revision_id: str, request: RevisionRequest, http_request: Request):
        return await run_generation(http_request, app.state.drafts.revise, revision_id, request)

    @app.get("/api/drawings/{revision_id}", response_model=DrawingDraft)
    def get_draft(revision_id: str):
        return app.state.drafts.get(revision_id)

    @app.post('/api/artifacts/{artifact_id}/repair')
    def repair_artifact(artifact_id: str):
        app.state.repository.repair(artifact_id)
        return {'status': 'repaired', 'artifact_id': artifact_id}

    @app.get('/api/drawings/{revision_id}/thumbnail')
    def thumbnail(revision_id: str):
        files = app.state.repository.load(revision_id, 'revision')
        return Response(files['preview.svg'], media_type='image/svg+xml', headers={'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'"})

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

    @app.post('/api/jobs/prepare', response_model=PreparedJob)
    def prepare_job(request: PreparationRequest):
        return app.state.jobs.prepare(request)

    @app.get('/api/jobs', response_model=list[PreparedJob])
    def jobs(revision_id: str | None = None):
        with app.state.repository.connection() as db:
            rows = db.execute("SELECT id FROM artifacts WHERE kind='job' AND (? IS NULL OR parent_id=?) ORDER BY created_at DESC LIMIT 30", (revision_id, revision_id)).fetchall()
        return [app.state.jobs.get(row[0]) for row in rows]

    @app.get('/api/jobs/{job_id}', response_model=PreparedJob)
    def job(job_id: str):
        return app.state.jobs.get(job_id)

    @app.get('/api/storage/targets', response_model=TargetsResponse)
    def targets():
        return app.state.storage.targets()

    @app.post('/api/storage/select', response_model=TargetsResponse)
    def select_target(request: TargetSelectionRequest):
        app.state.storage.select(request.target_id)
        return app.state.storage.targets()

    @app.post('/api/storage/test-target', response_model=StorageTarget)
    def create_test_target():
        return app.state.storage.create_test()

    @app.post('/api/jobs/{job_id}/stage', response_model=TransferRecord)
    def stage_job(job_id: str, request: StageRequest):
        return app.state.storage.stage(job_id, request)

    @app.post('/api/jobs/{job_id}/sd-export', response_model=TransferRecord)
    def export_job(job_id: str, request: ExportRequest):
        return app.state.storage.export(job_id, request)

    @app.post('/api/storage/auto-sync', response_model=AutoSyncState)
    def auto_sync(request: AutoSyncRequest):
        return app.state.storage.arm(request)

    @app.get('/api/storage/transfers', response_model=list[TransferRecord])
    def transfers():
        return app.state.repository.transfers()

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
