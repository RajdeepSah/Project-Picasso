/* Generated from backend Pydantic models. Run npm run contracts; do not edit. */

export type PicassoContracts =
  | DrawingSpec
  | PolylineDrawing
  | ProfilesResponse
  | CapabilitiesResponse
  | HealthResponse
  | StudioStatus
  | ApiError
  | GenerateRequest;
export type Detail = "sparse" | "standard" | "dense";
export type HeightMm = number;
export type SchemaVersion = 1;
export type WidthMm = number;
export type Generator = "circle" | "rectangle" | "spiral" | "butterfly" | "mandala" | "pattern";
export type GeneratorVersion = string;
export type Petals = number | null;
export type RadiusMm = number | null;
export type SchemaVersion1 = 1;
export type Symmetry = number | null;
export type Turns = number | null;
export type SchemaVersion2 = 1;
export type Seed = number;
export type CoordinateSystem = "centered_cartesian_y_up";
export type SchemaVersion3 = 1;
/**
 * @minItems 1
 * @maxItems 10000
 */
export type Strokes = [Stroke, ...Stroke[]];
export type Closed = boolean;
/**
 * @minItems 2
 * @maxItems 100000
 */
export type Points = [[number, number], [number, number], ...[number, number][]];
export type SchemaVersion4 = 1;
export type Units = "mm";
export type ActiveProfileId = null;
export type AllowedRegion = null;
export type AnchorYMm = number;
export type Board = null;
export type Dialect = "picasso-legacy-v1";
export type Id = string;
export type Label = string;
export type Notes = string;
export type PenDownDegrees = number;
export type PenUpDegrees = number;
export type Revision = string;
export type SchemaVersion5 = 1;
export type SeparationMm = number;
export type SourcePath = string;
export type SpoolDiameterMm = number;
export type StepsPerTurn = number;
export type Verified = false;
export type Profiles = MachineProfile[];
export type SchemaVersion6 = 1;
export type Available = boolean;
export type Phase = number;
export type Reason = string;
export type SchemaVersion7 = 1;
export type SchemaVersion8 = 1;
export type Application = "project-picasso";
export type FrontendReady = boolean;
export type InstanceId = string;
export type Phase1 = 2;
export type PythonVersion = string;
export type SchemaVersion9 = 1;
export type Status = "ready";
export type Version = string;
export type CredentialsRequired = false;
export type DiscoveryPerformed = false;
export type PositionKnown = false;
export type Reason1 = string;
export type SchemaVersion10 = 1;
export type State = "unavailable";
export type SchemaVersion11 = 1;
export type DiscoveryPerformed1 = false;
export type LocalMirror = "SdCard";
export type Reason2 = string;
export type SchemaVersion12 = 1;
export type State1 = "not_configured";
export type Code = string;
export type Message = string;
export type Phase2 = number | null;
export type SchemaVersion13 = 1;
export type Prompt = string;
export type SchemaVersion14 = 1;

export interface DrawingSpec {
  detail?: Detail;
  dimensions: Dimensions;
  generator: Generator;
  generator_version?: GeneratorVersion;
  parameters?: GeneratorParameters;
  schema_version?: SchemaVersion2;
  seed?: Seed;
}
export interface Dimensions {
  height_mm: HeightMm;
  schema_version?: SchemaVersion;
  width_mm: WidthMm;
}
export interface GeneratorParameters {
  petals?: Petals;
  radius_mm?: RadiusMm;
  schema_version?: SchemaVersion1;
  symmetry?: Symmetry;
  turns?: Turns;
}
export interface PolylineDrawing {
  coordinate_system?: CoordinateSystem;
  schema_version?: SchemaVersion3;
  source: DrawingSpec;
  strokes: Strokes;
  units?: Units;
}
export interface Stroke {
  closed?: Closed;
  points: Points;
  schema_version?: SchemaVersion4;
}
export interface ProfilesResponse {
  active_profile_id?: ActiveProfileId;
  profiles: Profiles;
  schema_version?: SchemaVersion6;
}
export interface MachineProfile {
  allowed_region?: AllowedRegion;
  anchor_y_mm: AnchorYMm;
  board?: Board;
  dialect?: Dialect;
  id: Id;
  label: Label;
  notes: Notes;
  pen_down_degrees: PenDownDegrees;
  pen_up_degrees: PenUpDegrees;
  revision: Revision;
  schema_version?: SchemaVersion5;
  separation_mm: SeparationMm;
  source_path: SourcePath;
  spool_diameter_mm: SpoolDiameterMm;
  steps_per_turn: StepsPerTurn;
  verified?: Verified;
}
export interface CapabilitiesResponse {
  ai: Capability;
  dashboard: Capability;
  gcode_export: Capability;
  generation: Capability;
  history: Capability;
  schema_version?: SchemaVersion8;
  sd_export: Capability;
  serial_control: Capability;
  voice: Capability;
}
export interface Capability {
  available: Available;
  phase: Phase;
  reason: Reason;
  schema_version?: SchemaVersion7;
}
export interface HealthResponse {
  application?: Application;
  frontend_ready: FrontendReady;
  instance_id: InstanceId;
  phase?: Phase1;
  python_version: PythonVersion;
  schema_version?: SchemaVersion9;
  status?: Status;
  version: Version;
}
export interface StudioStatus {
  credentials_required?: CredentialsRequired;
  machine: MachineStatus;
  schema_version?: SchemaVersion11;
  storage: StorageStatus;
}
export interface MachineStatus {
  discovery_performed?: DiscoveryPerformed;
  position_known?: PositionKnown;
  reason: Reason1;
  schema_version?: SchemaVersion10;
  state?: State;
}
export interface StorageStatus {
  discovery_performed?: DiscoveryPerformed1;
  local_mirror?: LocalMirror;
  reason: Reason2;
  schema_version?: SchemaVersion12;
  state?: State1;
}
export interface ApiError {
  code: Code;
  message: Message;
  phase?: Phase2;
  schema_version?: SchemaVersion13;
}
export interface GenerateRequest {
  prompt: Prompt;
  schema_version?: SchemaVersion14;
}
