"""Versioned contracts. Geometry schemas establish units, not physical safety."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    generator_version: str = Field(default="1", min_length=1, max_length=40)
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
    phase: Literal[2] = 2
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
    prompt: str = Field(min_length=1, max_length=2000)


ALL_CONTRACTS = (DrawingSpec | PolylineDrawing | ProfilesResponse | CapabilitiesResponse
                 | HealthResponse | StudioStatus | ApiError | GenerateRequest)
