"""Versioned contracts. Geometry schemas establish units, not physical safety."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Finite = Annotated[float, Field(allow_inf_nan=False)]
PositiveMm = Annotated[float, Field(gt=0, le=2000, allow_inf_nan=False)]
Point2 = tuple[Finite, Finite]
GeneratorName = Literal["circle", "rectangle", "spiral", "butterfly", "mandala", "pattern", "imported"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal[1] = 1


class Dimensions(Contract):
    width_mm: PositiveMm
    height_mm: PositiveMm


class GeneratorParameters(Contract):
    radius_mm: PositiveMm | None = None
    petals: Annotated[int, Field(ge=3, le=64)] | None = None
    turns: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)] | None = None
    symmetry: Annotated[int, Field(ge=2, le=64)] | None = None


class DrawingSpec(Contract):
    generator: GeneratorName
    generator_version: Literal["1"] = "1"
    dimensions: Dimensions
    parameters: GeneratorParameters = Field(default_factory=GeneratorParameters)
    seed: int = Field(default=0, ge=0, le=4294967295)
    detail: Literal["sparse", "standard", "dense"] = "standard"

    @model_validator(mode="after")
    def applicable_parameters(self):
        allowed = {"circle": {"radius_mm"}, "rectangle": set(), "spiral": {"turns"},
                   "butterfly": set(), "mandala": {"petals", "symmetry"}, "pattern": {"symmetry"}, "imported": set()}
        present = {key for key, value in self.parameters.model_dump().items()
                   if key != "schema_version" and value is not None}
        if present - allowed[self.generator]:
            raise ValueError("Parameters do not apply to this generator")
        if self.parameters.radius_mm is not None and any(abs(value - 2 * self.parameters.radius_mm) > 1e-9 for value in (self.dimensions.width_mm, self.dimensions.height_mm)):
            raise ValueError("Radius must agree with both circle dimensions")
        if self.parameters.petals is not None and self.parameters.symmetry is not None and self.parameters.petals != self.parameters.symmetry:
            raise ValueError("Mandala petals and symmetry must agree when both are specified")
        return self


class Stroke(Contract):
    points: Annotated[list[Point2], Field(min_length=2, max_length=100000)]
    closed: bool = False


class PolylineDrawing(Contract):
    units: Literal["mm"] = "mm"
    coordinate_system: Literal["centered_cartesian_y_up"] = "centered_cartesian_y_up"
    source: DrawingSpec
    strokes: Annotated[list[Stroke], Field(min_length=1, max_length=10000)]


class MachineProfile(Contract):
    id: str
    revision: str
    label: str
    source_path: str
    verified: Literal[False] = False
    board: None = None
    allowed_region: None = None
    separation_mm: PositiveMm
    anchor_y_mm: Finite
    spool_diameter_mm: PositiveMm
    steps_per_turn: int = Field(gt=0)
    pen_up_degrees: int = Field(ge=0, le=180)
    pen_down_degrees: int = Field(ge=0, le=180)
    dialect: Literal["picasso-legacy-v1"] = "picasso-legacy-v1"
    notes: str


class FirmwareInfo(Contract):
    version: str
    dialect: Literal["picasso-fw-v1"] = "picasso-fw-v1"
    config_ids: dict[str, str] = Field(default_factory=dict)
    reason: str


class ProfilesResponse(Contract):
    profiles: list[MachineProfile]
    measured_profiles: list["CalibrationProfile"] = Field(default_factory=list)
    active_profile_id: str | None = None
    firmware: FirmwareInfo | None = None


class Capability(Contract):
    available: bool
    phase: int
    reason: str


class CapabilitiesResponse(Contract):
    dashboard: Capability
    generation: Capability
    history: Capability
    gcode_export: Capability
    sd_export: Capability
    firmware: Capability
    serial_control: Capability
    ai: Capability
    voice: Capability


class HealthResponse(Contract):
    application: Literal["project-picasso"] = "project-picasso"
    version: str
    phase: Literal[6] = 6
    status: Literal["ready"] = "ready"
    instance_id: str
    frontend_ready: bool
    python_version: str


MachineConnection = Literal["disconnected", "connecting", "connected", "incompatible", "lost"]
RunState = Literal["starting", "streaming", "pausing", "paused", "resuming", "stopping",
                   "completed", "aborted", "failed", "fault", "interrupted"]
HexBoot = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}$")]


class MachineStatus(Contract):
    state: Literal["unavailable"] | MachineConnection = "unavailable"
    reason: str
    discovery_performed: bool = False
    position_known: bool = False


class SerialPortInfo(Contract):
    device: str
    description: str
    hwid: str
    likely_arduino: bool
    simulated: bool = False
    accessible: bool = True


class PortsResponse(Contract):
    ports: list[SerialPortInfo]
    error: str | None = None


class DeviceHello(Contract):
    protocol: int
    firmware_version: str
    dialect: str
    config_id: str
    boot_id: str
    capabilities: list[str]


class DeviceStatus(Contract):
    state: str
    job: str
    boot_id: str
    origin_revision: int
    origin: str
    position_mm: Point2
    position_source: Literal["commanded"] = "commanded"  # step-count estimate, never measured
    pen_down: bool
    received_seq: int
    completed_seq: int
    result: str
    reason: str
    observed_at: str


class UsbRun(Contract):
    id: str
    job_id: str
    title: str
    port: str
    boot_id: str
    origin_revision: int
    token: str
    total_commands: int
    sent_seq: int = 0
    acknowledged_seq: int = 0
    state: RunState
    message: str
    position_mm: Point2 | None = None
    current_line: str | None = None
    started_at: str
    updated_at: str
    measured_feedback: Literal[False] = False


class MachineState(Contract):
    connection: MachineConnection
    port: str | None = None
    simulated: bool = False
    message: str
    hello: DeviceHello | None = None
    status: DeviceStatus | None = None
    status_age_s: Finite | None = None
    run: UsbRun | None = None
    recent_runs: list[UsbRun] = Field(default_factory=list)


class ConnectRequest(Contract):
    port: str = Field(min_length=1, max_length=200)


class UsbStartRequest(Contract):
    expected_boot_id: HexBoot
    expected_origin_revision: int = Field(ge=0, le=65535)
    expected_config_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
    area_clear_confirmed: bool = False


class HomeRequest(Contract):
    expected_boot_id: HexBoot
    expected_origin_revision: int = Field(ge=0, le=65535)
    route_confirmed: bool = False


class StorageStatus(Contract):
    state: Literal["not_configured", "unmounted", "ready", "test_directory"] = "not_configured"
    local_mirror: Literal["SdCard"] = "SdCard"
    discovery_performed: bool = False
    reason: str


class StudioStatus(Contract):
    machine: MachineStatus
    storage: StorageStatus
    credentials_required: Literal[False] = False


class ApiError(Contract):
    code: str
    message: str
    phase: int | None = None


DetailLevel = Literal["low", "medium", "high"]


class GenerateRequest(Contract):
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    # auto: offline shapes first, AI line art only for requests they cannot draw (when configured).
    mode: Literal["auto", "offline", "ai"] = "auto"
    # Default detail; a detail word in the command itself ("intricate") takes precedence offline.
    detail: DetailLevel | None = None
    # AI drawings are traced from pixels and fitted inside this box, like imported images.
    fit_width_mm: PositiveMm | None = None
    fit_height_mm: PositiveMm | None = None


class DrawingTransform(Contract):
    rotation_degrees: Finite = Field(default=0, ge=-360, le=360)
    offset_x_mm: Finite = Field(default=0, ge=-2000, le=2000)
    offset_y_mm: Finite = Field(default=0, ge=-2000, le=2000)
    preserve_aspect: bool = False


class RevisionRequest(Contract):
    spec: DrawingSpec | None = None
    transform: DrawingTransform | None = None
    regenerate: bool = False
    seed_locked: bool = False


class DrawingBounds(Contract):
    min_x_mm: Finite
    min_y_mm: Finite
    max_x_mm: Finite
    max_y_mm: Finite
    width_mm: Finite
    height_mm: Finite


class ExecutionSegment(Contract):
    start: Point2
    end: Point2
    pen_down: bool


class ExecutionPreview(Contract):
    expected_start_mm: Point2 = (0, 0)
    segments: list[ExecutionSegment]
    bounds: DrawingBounds
    drawing_distance_mm: Finite
    travel_distance_mm: Finite
    strokes: int
    pen_lifts: int


class DrawingDraft(Contract):
    drawing_id: str
    revision_id: str
    parent_revision_id: str | None
    revision: int = Field(ge=1)
    title: str
    prompt: str
    spec: DrawingSpec
    transform: DrawingTransform
    geometry: PolylineDrawing
    preview: ExecutionPreview
    gcode: str
    gcode_sha256: str
    exporter_version: Literal["picasso-legacy-v1.0"] = "picasso-legacy-v1.0"
    chord_tolerance_mm: Finite
    rounding_tolerance_mm: Finite = 0.000708
    execution_ready: Literal[False] = False
    simulation_profile: Literal["unverified-preview-v1"] = "unverified-preview-v1"
    warnings: list[str]
    import_source: "ImportedSource | None" = None


class AiProvenance(Contract):
    """Which provider request produced an AI drawing's source image. Never contains credentials."""
    provider: Literal["openai"] = "openai"
    model: str
    quality: DetailLevel
    size: str
    prompt: str
    image_sha256: str
    elapsed_s: Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ImportedSource(Contract):
    filename: str
    content_sha256: str
    dialect: Literal["picasso", "linear-mm", "picasso-json", "image", "ai-image"]
    original_bounds: DrawingBounds
    input_strokes: list[Stroke]
    notes: list[str]
    ai: AiProvenance | None = None


class ImportRequest(Contract):
    filename: str = Field(min_length=1, max_length=120)
    # G-code (or a Picasso JSON draft) as text; an image as base64 of at most 8 MB.
    content: str = Field(min_length=1, max_length=10_700_000)
    kind: Literal["gcode", "image"] = "gcode"
    detail: DetailLevel = "medium"
    center_on_origin: bool = False  # accepted for compatibility; every import is centred on the page
    fit_width_mm: PositiveMm | None = None
    fit_height_mm: PositiveMm | None = None


class HistoryEntry(Contract):
    revision_id: str
    drawing_id: str
    title: str
    revision: int
    prompt: str
    generator: str
    created_at: str
    integrity: Literal["ok", "damaged"]
    integrity_message: str | None = None


class HistoryResponse(Contract):
    items: list[HistoryEntry]
    total: int
    offset: int
    limit: int
    recovery_notices: list[str] = Field(default_factory=list)


class WorkRegion(Contract):
    min_x_mm: Finite = Field(ge=-2000, le=2000)
    max_x_mm: Finite = Field(ge=-2000, le=2000)
    min_y_mm: Finite = Field(ge=-2000, le=2000)
    max_y_mm: Finite = Field(ge=-2000, le=2000)
    margin_mm: Finite = Field(default=5, ge=1, le=100)

    @model_validator(mode="after")
    def nonempty(self):
        if self.min_x_mm + 2 * self.margin_mm >= self.max_x_mm or self.min_y_mm + 2 * self.margin_mm >= self.max_y_mm:
            raise ValueError("Region must contain a nonempty interior after margins")
        return self


class CalibrationInput(Contract):
    label: str = Field(min_length=1, max_length=100)
    base_reference_id: Literal["reference-350", "reference-400"]
    board: str = Field(min_length=1, max_length=120)
    separation_mm: PositiveMm
    anchor_y_mm: Finite = Field(gt=0, le=2000)
    spool_diameter_mm: PositiveMm
    steps_per_turn: int = Field(gt=0, le=100000)
    pen_up_degrees: int = Field(ge=0, le=180)
    pen_down_degrees: int = Field(ge=0, le=180)
    allowed_region: WorkRegion
    rope_min_mm: Finite = Field(gt=0, le=10000)
    rope_max_mm: Finite = Field(gt=0, le=10000)
    measured_by: str = Field(min_length=1, max_length=100)
    measurement_notes: str = Field(min_length=10, max_length=3000)
    origin_procedure: str = Field(min_length=10, max_length=3000)
    firmware_matches_measurements: bool = False
    pen_lift_and_holding_tested: bool = False
    workspace_tested: bool = False
    verified: bool = False
    # Which firmware the machine runs. Canonical firmware is generated from the
    # profile; its configuration ID, read from the machine, proves the match.
    firmware: Literal["legacy-reference", "picasso-canonical"] = "legacy-reference"
    firmware_config_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")] | None = None

    @model_validator(mode="after")
    def measured_region(self):
        if self.rope_min_mm >= self.rope_max_mm:
            raise ValueError("Minimum rope length must be below maximum")
        region = self.allowed_region
        if region.max_y_mm >= self.anchor_y_mm or region.min_x_mm <= -self.separation_mm / 2 or region.max_x_mm >= self.separation_mm / 2:
            raise ValueError("Workspace must lie below and strictly between the motor anchors")
        if self.verified and not (self.firmware_matches_measurements and self.pen_lift_and_holding_tested and self.workspace_tested):
            raise ValueError("Verification requires recorded firmware, pen/holding and workspace checks")
        if self.firmware == "legacy-reference" and self.firmware_config_id:
            raise ValueError("A firmware configuration ID applies only to canonical Picasso firmware")
        if self.verified and self.firmware == "picasso-canonical" and not self.firmware_config_id:
            raise ValueError("Verifying canonical firmware requires the configuration ID shown on the machine's Info screen")
        return self


class CalibrationSaveRequest(Contract):
    calibration: CalibrationInput
    expected_revision: str | None = None
    select_for_preparation: bool = False


class CalibrationProfile(CalibrationInput):
    id: str
    revision: str
    version: int
    recorded_at: str
    verification_method: Literal["operator_recorded"] = "operator_recorded"


class PreparationRequest(Contract):
    revision_id: str
    mode: Literal["physical", "simulation"] = "physical"
    profile_id: str | None = None
    profile_revision: str | None = None


class PreparedJob(Contract):
    id: str
    revision_id: str
    drawing_id: str
    title: str
    mode: Literal["physical", "simulation"]
    profile: CalibrationProfile | None
    gcode: str
    gcode_sha256: str
    gcode_crc32: str | None = None  # shown by canonical firmware after it checks main.nc
    preview: ExecutionPreview
    created_at: str
    expected_start_mm: Point2 = (0, 0)
    manual_origin_required: Literal[True] = True
    hardware_execution_verified: Literal[False] = False
    state: Literal["prepared_locally"] = "prepared_locally"
    warnings: list[str]


class StorageTarget(Contract):
    id: str
    label: str
    path: str
    kind: Literal["physical_card", "test_directory"]
    filesystem: str
    volume_uuid: str
    instance: str
    available: bool
    writable: bool
    reason: str
    current_main_sha256: str | None = None


class TargetsResponse(Contract):
    targets: list[StorageTarget]
    selected_target_id: str | None
    discovery_supported: bool
    discovery_error: str | None = None
    local_mirror_sha256: str | None = None
    auto_sync: "AutoSyncState"


class TargetSelectionRequest(Contract):
    target_id: str


class ProfileSelectionRequest(Contract):
    profile_id: str
    expected_revision: str


class ExportRequest(Contract):
    target_id: str
    expected_job_sha256: str
    expected_existing_sha256: str | None = None
    acknowledge_replace: bool = False
    computer_owns_card: bool = False
    manual_start_understood: bool = False
    stage_local_mirror: bool = False
    expected_local_mirror_sha256: str | None = None


class StageRequest(Contract):
    expected_existing_sha256: str | None = None
    acknowledge_replace: bool = False


class TransferRecord(Contract):
    id: str
    job_id: str
    target_id: str
    target_kind: Literal["physical_card", "test_directory", "local_mirror"]
    status: Literal["copying", "verified", "failed", "interrupted"]
    gcode_sha256: str
    previous_sha256: str | None
    backup: str | None
    bytes_verified: int = 0
    message: str
    created_at: str
    local_mirror_updated: bool = False


class AutoSyncState(Contract):
    enabled: bool = False
    job_id: str | None = None
    target_id: str | None = None
    status: str = "disabled"
    message: str = "Automatic export is disabled."
    last_transfer_id: str | None = None


class AutoSyncRequest(Contract):
    enabled: bool
    job_id: str | None = None
    export: ExportRequest | None = None


class SessionResponse(Contract):
    write_token: str


class VoiceTranscript(Contract):
    """Recognized words for the composer. Text only: it never starts generation or motion."""
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    duration_s: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    processing_s: Annotated[float, Field(ge=0, allow_inf_nan=False)]


ALL_CONTRACTS = (DrawingSpec | PolylineDrawing | ProfilesResponse | CapabilitiesResponse
                 | HealthResponse | StudioStatus | ApiError | GenerateRequest | DrawingDraft | RevisionRequest
                 | ImportRequest | HistoryResponse | CalibrationSaveRequest | CalibrationProfile
                 | PreparationRequest | PreparedJob | TargetsResponse | TargetSelectionRequest
                 | ExportRequest | StageRequest | TransferRecord | AutoSyncRequest | AutoSyncState | SessionResponse | ProfileSelectionRequest
                 | PortsResponse | MachineState | ConnectRequest | UsbStartRequest | HomeRequest | VoiceTranscript)

ProfilesResponse.model_rebuild()
DrawingDraft.model_rebuild()
TargetsResponse.model_rebuild()
