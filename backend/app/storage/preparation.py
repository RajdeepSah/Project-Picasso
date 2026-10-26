"""Operator-recorded calibration and complete Cartesian/rope path validation."""

from contextlib import contextmanager
import json
import math
import os
import uuid

from .. import firmware
from ..drawing.errors import DrawingError
from ..drawing.gcode import parse, verify_roundtrip
from ..drawing.geometry import segment_distance
from ..models import CalibrationProfile, PreparedJob
from .repository import directory, now, sha


class ProfileManager:
    def __init__(self, repository, references):
        self.repository = repository
        self.references = {profile.id: profile for profile in references}

    def all(self):
        with self.repository.connection() as db:
            return [CalibrationProfile.model_validate_json(row[0]) for row in db.execute("SELECT document FROM profiles ORDER BY rowid DESC")]

    def get(self, identity):
        with self.repository.connection() as db:
            row = db.execute("SELECT document FROM profiles WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise DrawingError("PROFILE_NOT_FOUND", "Measured profile not found. Record measurements first.", 404)
        return CalibrationProfile.model_validate_json(row[0])

    @contextmanager
    def configuration_lock(self):
        directory(self.repository.root)
        descriptor = None
        try:
            if os.name == 'posix':
                import fcntl
                descriptor = os.open(self.repository.root / 'export.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise DrawingError('PROFILE_BUSY', 'A managed export/configuration update is in progress. Retry after it finishes.', 409) from exc
            with self.repository.lock:
                yield
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def select(self, identity, revision):
        with self.configuration_lock():
            profile = self.get(identity)
            if revision != profile.revision:
                raise DrawingError('STALE_PROFILE', 'Profile changed. Reload before selecting.', 409)
            self.repository.set_setting('active_profile', identity)

    def save(self, request, identity=None):
        with self.configuration_lock():
            return self._save(request, identity)

    def _save(self, request, identity=None):
        calibration = request.calibration
        reference = self.references[calibration.base_reference_id]
        if calibration.verified:
            if calibration.firmware == 'legacy-reference':
                for name in ('separation_mm', 'anchor_y_mm', 'spool_diameter_mm', 'steps_per_turn', 'pen_up_degrees', 'pen_down_degrees'):
                    if getattr(calibration, name) != getattr(reference, name):
                        raise DrawingError("FIRMWARE_PROFILE_MISMATCH", "Recorded calibration differs from the selected bundled legacy sketch. Save it unverified, generate canonical Picasso firmware from it, upload that firmware and record the configuration ID the machine shows.")
            validate_point((0, 0), calibration)
        # The ID is read from the machine, so it must describe exactly these values.
        if calibration.firmware_config_id and calibration.firmware_config_id != firmware.config_id(calibration):
            raise DrawingError("FIRMWARE_CONFIG_MISMATCH", "The configuration ID does not match these calibration values. Regenerate machine_config.h from this saved profile, upload it and enter the ID the machine shows, or clear the ID and save unverified.")
        with self.repository.connection() as db:
            previous = db.execute("SELECT document FROM profiles WHERE id=?", (identity,)).fetchone() if identity else None
            if identity and previous is None:
                raise DrawingError("PROFILE_NOT_FOUND", "Measured profile not found.", 404)
            previous = CalibrationProfile.model_validate_json(previous[0]) if previous else None
            if previous and request.expected_revision != previous.revision:
                raise DrawingError("STALE_PROFILE", "Profile changed. Reload before saving.", 409)
            identity = identity or uuid.uuid4().hex
            version = previous.version + 1 if previous else 1
            revision = sha(json.dumps({'calibration': calibration.model_dump(), 'version': version}, sort_keys=True).encode())
            profile = CalibrationProfile(**calibration.model_dump(), id=identity, revision=revision, version=version, recorded_at=now())
            db.execute("INSERT INTO profiles VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document", (identity, revision, profile.model_dump_json()))
            db.execute("INSERT INTO profile_versions VALUES(?,?,?)", (identity, revision, profile.model_dump_json()))
            if request.select_for_preparation:
                db.execute("INSERT INTO settings VALUES('active_profile',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(identity),))
        return profile


def validate_point(point, profile):
    x, y = point
    region = profile.allowed_region
    margin = region.margin_mm
    if not (region.min_x_mm + margin <= x <= region.max_x_mm - margin and region.min_y_mm + margin <= y <= region.max_y_mm - margin):
        raise DrawingError("PATH_OUT_OF_BOUNDS", "A drawing or travel point lies outside the measured region and margins. Include the (0,0) start and resize/reposition the drawing.")
    if y >= profile.anchor_y_mm - margin:
        raise DrawingError("ROPE_BRANCH_INVALID", "The path approaches or crosses the motor anchor line.")


def validate_physical_path(preview, profile):
    if not profile.verified:
        raise DrawingError("PROFILE_UNVERIFIED", "Record and verify the actual machine profile before physical preparation.")
    half_step = profile.spool_diameter_mm * 3.1416 / profile.steps_per_turn / 2
    points = [tuple(preview.expected_start_mm)]
    for segment in preview.segments:
        points.extend([tuple(segment.start), tuple(segment.end)])
    for point in points:
        validate_point(point, profile)
    anchors = [(-profile.separation_mm/2, profile.anchor_y_mm), (profile.separation_mm/2, profile.anchor_y_mm)]
    for segment in preview.segments:
        for anchor in anchors:
            minimum = segment_distance(anchor, segment.start, segment.end)
            maximum = max(math.dist(anchor, segment.start), math.dist(anchor, segment.end))
            if minimum < profile.rope_min_mm + half_step or maximum > profile.rope_max_mm - half_step:
                raise DrawingError("ROPE_LIMIT_EXCEEDED", "A drawing or travel segment violates measured rope limits (including a half-step allowance). Resize/reposition or correct the measured profile.")


class JobManager:
    def __init__(self, repository, drafts, profiles):
        self.repository, self.drafts, self.profiles = repository, drafts, profiles

    def prepare(self, request):
        draft = self.drafts.get(request.revision_id)
        preview = parse(draft.gcode, expected_start=(0, 0))
        verify_roundtrip(draft.geometry, preview)
        profile = None
        crc = firmware.gcode_crc32(draft.gcode)
        warnings = ["Manually establish both physical and firmware (0,0) before every legacy SD drawing. A previous drawing need not finish at origin.",
                    "Copy verification does not start the machine or measure its position. Physical commissioning remains an operator responsibility.",
                    f"Canonical Picasso firmware shows CRC {crc} after checking main.nc; confirm it matches before starting. The legacy sketch cannot."]
        if request.mode == 'physical':
            identity = request.profile_id or self.repository.setting('active_profile')
            if not identity:
                raise DrawingError("PROFILE_UNVERIFIED", "Record actual board, measurements, allowed region and checks in a measured profile first.")
            profile = self.profiles.get(identity)
            if request.profile_revision != profile.revision:
                raise DrawingError("STALE_PROFILE", "Profile revision changed. Reload and prepare again.", 409)
            validate_physical_path(preview, profile)
            warnings.append("Path checks use an operator-recorded profile; the app has not observed a hardware test.")
        else:
            if request.profile_id or request.profile_revision:
                raise DrawingError("INVALID_PREPARATION", "Simulation preparation does not activate a physical profile.")
            warnings.append("Simulation job: export is restricted to the app-owned test directory. It cannot update a physical card or SdCard/main.nc.")
        job = PreparedJob(id=uuid.uuid4().hex, revision_id=draft.revision_id, drawing_id=draft.drawing_id,
                          title=draft.title, mode=request.mode, profile=profile, gcode=draft.gcode,
                          gcode_sha256=draft.gcode_sha256, gcode_crc32=crc, preview=preview, created_at=now(), warnings=warnings)
        self.repository.save(job.id, 'job', {'job.json': job.model_dump_json().encode(), 'drawing.nc': draft.gcode.encode()},
                             {'drawing_id': draft.drawing_id, 'parent_id': draft.revision_id, 'title': draft.title})
        return job

    def get(self, identity):
        files = self.repository.load(identity, 'job')
        job = PreparedJob.model_validate_json(files['job.json'])
        if sha(files['drawing.nc']) != job.gcode_sha256 or files['drawing.nc'] != job.gcode.encode():
            raise DrawingError("ARTIFACT_DAMAGED", "Prepared job checksum mismatch.", 409)
        return job

    def validate_for_export(self, identity):
        job = self.get(identity)
        if job.mode == 'physical':
            profile = self.profiles.get(job.profile.id)
            if self.repository.setting('active_profile') != profile.id:
                raise DrawingError("STALE_PREPARATION", "The selected machine profile changed. Select the intended profile and prepare again.", 409)
            if not profile.verified or profile.revision != job.profile.revision:
                raise DrawingError("STALE_PREPARATION", "The measured profile changed or is unverified. Prepare this drawing again.", 409)
            validate_physical_path(parse(job.gcode), profile)
        return job
