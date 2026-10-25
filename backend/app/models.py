"""Versioned contracts. Geometry schemas establish units, not physical safety."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Finite = Annotated[float, Field(allow_inf_nan=False)]
PositiveMm = Annotated[float, Field(gt=0, le=2000, allow_inf_nan=False)]
Point2 = tuple[Finite, Finite]
GeneratorName = Literal["circle", "rectangle", "spiral", "butterfly", "mandala", "pattern"]


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
                   "butterfly": set(), "mandala": {"petals", "symmetry"}, "pattern": {"symmetry"}}
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


class ProfilesResponse(Contract):
    profiles: list[MachineProfile]
    active_profile_id: None = None


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
    serial_control: Capability
    ai: Capability
    voice: Capability


class HealthResponse(Contract):
    application: Literal["project-picasso"] = "project-picasso"
    version: str
    phase: Literal[3] = 3
    status: Literal["ready"] = "ready"
    instance_id: str
    frontend_ready: bool
    python_version: str


class MachineStatus(Contract):
    state: Literal["unavailable"] = "unavailable"
    reason: str
    discovery_performed: Literal[False] = False
    position_known: Literal[False] = False


class StorageStatus(Contract):
    state: Literal["not_configured"] = "not_configured"
    local_mirror: Literal["SdCard"] = "SdCard"
    discovery_performed: Literal[False] = False
    reason: str


class StudioStatus(Contract):
    machine: MachineStatus
    storage: StorageStatus
    credentials_required: Literal[False] = False


class ApiError(Contract):
    code: str
    message: str
    phase: int | None = None


class GenerateRequest(Contract):
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


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


ALL_CONTRACTS = (DrawingSpec | PolylineDrawing | ProfilesResponse | CapabilitiesResponse
                 | HealthResponse | StudioStatus | ApiError | GenerateRequest | DrawingDraft | RevisionRequest)
