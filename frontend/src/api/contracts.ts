/* Generated from backend Pydantic models. Run npm run contracts; do not edit. */

export type PicassoContracts =
  | DrawingSpec
  | PolylineDrawing
  | ProfilesResponse
  | CapabilitiesResponse
  | HealthResponse
  | StudioStatus
  | ApiError
  | GenerateRequest
  | DrawingDraft
  | RevisionRequest
  | ImportRequest
  | HistoryResponse
  | CalibrationSaveRequest
  | CalibrationProfile
  | PreparationRequest
  | PreparedJob
  | TargetsResponse
  | TargetSelectionRequest
  | ExportRequest
  | StageRequest
  | TransferRecord
  | AutoSyncRequest
  | AutoSyncState
  | SessionResponse
  | ProfileSelectionRequest
  | PortsResponse
  | MachineState
  | ConnectRequest
  | UsbStartRequest
  | HomeRequest;
export type Detail = "sparse" | "standard" | "dense";
export type HeightMm = number;
export type SchemaVersion = 1;
export type WidthMm = number;
export type Generator = "circle" | "rectangle" | "spiral" | "butterfly" | "mandala" | "pattern" | "imported";
export type GeneratorVersion = "1";
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
export type ActiveProfileId = string | null;
export type Dialect = "picasso-fw-v1";
export type Reason = string;
export type SchemaVersion5 = 1;
export type Version = string;
export type MarginMm = number;
export type MaxXMm = number;
export type MaxYMm = number;
export type MinXMm = number;
export type MinYMm = number;
export type SchemaVersion6 = 1;
export type AnchorYMm = number;
export type BaseReferenceId = "reference-350" | "reference-400";
export type Board = string;
export type Firmware = "legacy-reference" | "picasso-canonical";
export type FirmwareConfigId = string | null;
export type FirmwareMatchesMeasurements = boolean;
export type Id = string;
export type Label = string;
export type MeasuredBy = string;
export type MeasurementNotes = string;
export type OriginProcedure = string;
export type PenDownDegrees = number;
export type PenLiftAndHoldingTested = boolean;
export type PenUpDegrees = number;
export type RecordedAt = string;
export type Revision = string;
export type RopeMaxMm = number;
export type RopeMinMm = number;
export type SchemaVersion7 = 1;
export type SeparationMm = number;
export type SpoolDiameterMm = number;
export type StepsPerTurn = number;
export type VerificationMethod = "operator_recorded";
export type Verified = boolean;
export type Version1 = number;
export type WorkspaceTested = boolean;
export type MeasuredProfiles = CalibrationProfile[];
export type AllowedRegion = null;
export type AnchorYMm1 = number;
export type Board1 = null;
export type Dialect1 = "picasso-legacy-v1";
export type Id1 = string;
export type Label1 = string;
export type Notes = string;
export type PenDownDegrees1 = number;
export type PenUpDegrees1 = number;
export type Revision1 = string;
export type SchemaVersion8 = 1;
export type SeparationMm1 = number;
export type SourcePath = string;
export type SpoolDiameterMm1 = number;
export type StepsPerTurn1 = number;
export type Verified1 = false;
export type Profiles = MachineProfile[];
export type SchemaVersion9 = 1;
export type Available = boolean;
export type Phase = number;
export type Reason1 = string;
export type SchemaVersion10 = 1;
export type SchemaVersion11 = 1;
export type Application = "project-picasso";
export type FrontendReady = boolean;
export type InstanceId = string;
export type Phase1 = 6;
export type PythonVersion = string;
export type SchemaVersion12 = 1;
export type Status = "ready";
export type Version2 = string;
export type CredentialsRequired = false;
export type DiscoveryPerformed = boolean;
export type PositionKnown = boolean;
export type Reason2 = string;
export type SchemaVersion13 = 1;
export type State = "unavailable" | ("disconnected" | "connecting" | "connected" | "incompatible" | "lost");
export type SchemaVersion14 = 1;
export type DiscoveryPerformed1 = boolean;
export type LocalMirror = "SdCard";
export type Reason3 = string;
export type SchemaVersion15 = 1;
export type State1 = "not_configured" | "unmounted" | "ready" | "test_directory";
export type Code = string;
export type Message = string;
export type Phase2 = number | null;
export type SchemaVersion16 = 1;
export type Prompt = string;
export type SchemaVersion17 = 1;
export type ChordToleranceMm = number;
export type DrawingId = string;
export type ExecutionReady = false;
export type ExporterVersion = "picasso-legacy-v1.0";
export type Gcode = string;
export type GcodeSha256 = string;
export type ContentSha256 = string;
export type Dialect2 = "picasso" | "linear-mm" | "picasso-json";
export type Filename = string;
export type InputStrokes = Stroke[];
export type Notes1 = string[];
export type HeightMm1 = number;
export type MaxXMm1 = number;
export type MaxYMm1 = number;
export type MinXMm1 = number;
export type MinYMm1 = number;
export type SchemaVersion18 = 1;
export type WidthMm1 = number;
export type SchemaVersion19 = 1;
export type ParentRevisionId = string | null;
export type DrawingDistanceMm = number;
/**
 * @minItems 2
 * @maxItems 2
 */
export type ExpectedStartMm = [number, number];
export type PenLifts = number;
export type SchemaVersion20 = 1;
/**
 * @minItems 2
 * @maxItems 2
 */
export type End = [number, number];
export type PenDown = boolean;
export type SchemaVersion21 = 1;
/**
 * @minItems 2
 * @maxItems 2
 */
export type Start = [number, number];
export type Segments = ExecutionSegment[];
export type Strokes1 = number;
export type TravelDistanceMm = number;
export type Prompt1 = string;
export type Revision2 = number;
export type RevisionId = string;
export type RoundingToleranceMm = number;
export type SchemaVersion22 = 1;
export type SimulationProfile = "unverified-preview-v1";
export type Title = string;
export type OffsetXMm = number;
export type OffsetYMm = number;
export type PreserveAspect = boolean;
export type RotationDegrees = number;
export type SchemaVersion23 = 1;
export type Warnings = string[];
export type Regenerate = boolean;
export type SchemaVersion24 = 1;
export type SeedLocked = boolean;
export type CenterOnOrigin = boolean;
export type Content = string;
export type Dialect3 = "picasso" | "linear-mm" | "picasso-json";
export type Filename1 = string;
export type FitHeightMm = number | null;
export type FitWidthMm = number | null;
export type SchemaVersion25 = 1;
export type CreatedAt = string;
export type DrawingId1 = string;
export type Generator1 = string;
export type Integrity = "ok" | "damaged";
export type IntegrityMessage = string | null;
export type Prompt2 = string;
export type Revision3 = number;
export type RevisionId1 = string;
export type SchemaVersion26 = 1;
export type Title1 = string;
export type Items = HistoryEntry[];
export type Limit = number;
export type Offset = number;
export type RecoveryNotices = string[];
export type SchemaVersion27 = 1;
export type Total = number;
export type AnchorYMm2 = number;
export type BaseReferenceId1 = "reference-350" | "reference-400";
export type Board2 = string;
export type Firmware1 = "legacy-reference" | "picasso-canonical";
export type FirmwareConfigId1 = string | null;
export type FirmwareMatchesMeasurements1 = boolean;
export type Label2 = string;
export type MeasuredBy1 = string;
export type MeasurementNotes1 = string;
export type OriginProcedure1 = string;
export type PenDownDegrees2 = number;
export type PenLiftAndHoldingTested1 = boolean;
export type PenUpDegrees2 = number;
export type RopeMaxMm1 = number;
export type RopeMinMm1 = number;
export type SchemaVersion28 = 1;
export type SeparationMm2 = number;
export type SpoolDiameterMm2 = number;
export type StepsPerTurn2 = number;
export type Verified2 = boolean;
export type WorkspaceTested1 = boolean;
export type ExpectedRevision = string | null;
export type SchemaVersion29 = 1;
export type SelectForPreparation = boolean;
export type Mode = "physical" | "simulation";
export type ProfileId = string | null;
export type ProfileRevision = string | null;
export type RevisionId2 = string;
export type SchemaVersion30 = 1;
export type CreatedAt1 = string;
export type DrawingId2 = string;
/**
 * @minItems 2
 * @maxItems 2
 */
export type ExpectedStartMm1 = [number, number];
export type Gcode1 = string;
export type GcodeCrc32 = string | null;
export type GcodeSha2561 = string;
export type HardwareExecutionVerified = false;
export type Id2 = string;
export type ManualOriginRequired = true;
export type Mode1 = "physical" | "simulation";
export type RevisionId3 = string;
export type SchemaVersion31 = 1;
export type State2 = "prepared_locally";
export type Title2 = string;
export type Warnings1 = string[];
export type Enabled = boolean;
export type JobId = string | null;
export type LastTransferId = string | null;
export type Message1 = string;
export type SchemaVersion32 = 1;
export type Status1 = string;
export type TargetId = string | null;
export type DiscoveryError = string | null;
export type DiscoverySupported = boolean;
export type LocalMirrorSha256 = string | null;
export type SchemaVersion33 = 1;
export type SelectedTargetId = string | null;
export type Available1 = boolean;
export type CurrentMainSha256 = string | null;
export type Filesystem = string;
export type Id3 = string;
export type Instance = string;
export type Kind = "physical_card" | "test_directory";
export type Label3 = string;
export type Path = string;
export type Reason4 = string;
export type SchemaVersion34 = 1;
export type VolumeUuid = string;
export type Writable = boolean;
export type Targets = StorageTarget[];
export type SchemaVersion35 = 1;
export type TargetId1 = string;
export type AcknowledgeReplace = boolean;
export type ComputerOwnsCard = boolean;
export type ExpectedExistingSha256 = string | null;
export type ExpectedJobSha256 = string;
export type ExpectedLocalMirrorSha256 = string | null;
export type ManualStartUnderstood = boolean;
export type SchemaVersion36 = 1;
export type StageLocalMirror = boolean;
export type TargetId2 = string;
export type AcknowledgeReplace1 = boolean;
export type ExpectedExistingSha2561 = string | null;
export type SchemaVersion37 = 1;
export type Backup = string | null;
export type BytesVerified = number;
export type CreatedAt2 = string;
export type GcodeSha2562 = string;
export type Id4 = string;
export type JobId1 = string;
export type LocalMirrorUpdated = boolean;
export type Message2 = string;
export type PreviousSha256 = string | null;
export type SchemaVersion38 = 1;
export type Status2 = "copying" | "verified" | "failed" | "interrupted";
export type TargetId3 = string;
export type TargetKind = "physical_card" | "test_directory" | "local_mirror";
export type Enabled1 = boolean;
export type JobId2 = string | null;
export type SchemaVersion39 = 1;
export type SchemaVersion40 = 1;
export type WriteToken = string;
export type ExpectedRevision1 = string;
export type ProfileId1 = string;
export type SchemaVersion41 = 1;
export type Error = string | null;
export type Accessible = boolean;
export type Description = string;
export type Device = string;
export type Hwid = string;
export type LikelyArduino = boolean;
export type SchemaVersion42 = 1;
export type Simulated = boolean;
export type Ports = SerialPortInfo[];
export type SchemaVersion43 = 1;
export type Connection = "disconnected" | "connecting" | "connected" | "incompatible" | "lost";
export type BootId = string;
export type Capabilities = string[];
export type ConfigId = string;
export type Dialect4 = string;
export type FirmwareVersion = string;
export type Protocol = number;
export type SchemaVersion44 = 1;
export type Message3 = string;
export type Port = string | null;
export type AcknowledgedSeq = number;
export type BootId1 = string;
export type CurrentLine = string | null;
export type Id5 = string;
export type JobId3 = string;
export type MeasuredFeedback = false;
export type Message4 = string;
export type OriginRevision = number;
export type Port1 = string;
export type PositionMm = [number, number] | null;
export type SchemaVersion45 = 1;
export type SentSeq = number;
export type StartedAt = string;
export type State3 =
  | "starting"
  | "streaming"
  | "pausing"
  | "paused"
  | "resuming"
  | "stopping"
  | "completed"
  | "aborted"
  | "failed"
  | "fault"
  | "interrupted";
export type Title3 = string;
export type Token = string;
export type TotalCommands = number;
export type UpdatedAt = string;
export type RecentRuns = UsbRun[];
export type SchemaVersion46 = 1;
export type Simulated1 = boolean;
export type BootId2 = string;
export type CompletedSeq = number;
export type Job = string;
export type ObservedAt = string;
export type Origin = string;
export type OriginRevision1 = number;
export type PenDown1 = boolean;
/**
 * @minItems 2
 * @maxItems 2
 */
export type PositionMm1 = [number, number];
export type PositionSource = "commanded";
export type Reason5 = string;
export type ReceivedSeq = number;
export type Result = string;
export type SchemaVersion47 = 1;
export type State4 = string;
export type StatusAgeS = number | null;
export type Port2 = string;
export type SchemaVersion48 = 1;
export type AreaClearConfirmed = boolean;
export type ExpectedBootId = string;
export type ExpectedConfigId = string;
export type ExpectedOriginRevision = number;
export type SchemaVersion49 = 1;
export type ExpectedBootId1 = string;
export type ExpectedOriginRevision1 = number;
export type RouteConfirmed = boolean;
export type SchemaVersion50 = 1;

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
  firmware?: FirmwareInfo | null;
  measured_profiles?: MeasuredProfiles;
  profiles: Profiles;
  schema_version?: SchemaVersion9;
}
export interface FirmwareInfo {
  config_ids?: ConfigIds;
  dialect?: Dialect;
  reason: Reason;
  schema_version?: SchemaVersion5;
  version: Version;
}
export interface ConfigIds {
  [k: string]: string;
}
export interface CalibrationProfile {
  allowed_region: WorkRegion;
  anchor_y_mm: AnchorYMm;
  base_reference_id: BaseReferenceId;
  board: Board;
  firmware?: Firmware;
  firmware_config_id?: FirmwareConfigId;
  firmware_matches_measurements?: FirmwareMatchesMeasurements;
  id: Id;
  label: Label;
  measured_by: MeasuredBy;
  measurement_notes: MeasurementNotes;
  origin_procedure: OriginProcedure;
  pen_down_degrees: PenDownDegrees;
  pen_lift_and_holding_tested?: PenLiftAndHoldingTested;
  pen_up_degrees: PenUpDegrees;
  recorded_at: RecordedAt;
  revision: Revision;
  rope_max_mm: RopeMaxMm;
  rope_min_mm: RopeMinMm;
  schema_version?: SchemaVersion7;
  separation_mm: SeparationMm;
  spool_diameter_mm: SpoolDiameterMm;
  steps_per_turn: StepsPerTurn;
  verification_method?: VerificationMethod;
  verified?: Verified;
  version: Version1;
  workspace_tested?: WorkspaceTested;
}
export interface WorkRegion {
  margin_mm?: MarginMm;
  max_x_mm: MaxXMm;
  max_y_mm: MaxYMm;
  min_x_mm: MinXMm;
  min_y_mm: MinYMm;
  schema_version?: SchemaVersion6;
}
export interface MachineProfile {
  allowed_region?: AllowedRegion;
  anchor_y_mm: AnchorYMm1;
  board?: Board1;
  dialect?: Dialect1;
  id: Id1;
  label: Label1;
  notes: Notes;
  pen_down_degrees: PenDownDegrees1;
  pen_up_degrees: PenUpDegrees1;
  revision: Revision1;
  schema_version?: SchemaVersion8;
  separation_mm: SeparationMm1;
  source_path: SourcePath;
  spool_diameter_mm: SpoolDiameterMm1;
  steps_per_turn: StepsPerTurn1;
  verified?: Verified1;
}
export interface CapabilitiesResponse {
  ai: Capability;
  dashboard: Capability;
  firmware: Capability;
  gcode_export: Capability;
  generation: Capability;
  history: Capability;
  schema_version?: SchemaVersion11;
  sd_export: Capability;
  serial_control: Capability;
  voice: Capability;
}
export interface Capability {
  available: Available;
  phase: Phase;
  reason: Reason1;
  schema_version?: SchemaVersion10;
}
export interface HealthResponse {
  application?: Application;
  frontend_ready: FrontendReady;
  instance_id: InstanceId;
  phase?: Phase1;
  python_version: PythonVersion;
  schema_version?: SchemaVersion12;
  status?: Status;
  version: Version2;
}
export interface StudioStatus {
  credentials_required?: CredentialsRequired;
  machine: MachineStatus;
  schema_version?: SchemaVersion14;
  storage: StorageStatus;
}
export interface MachineStatus {
  discovery_performed?: DiscoveryPerformed;
  position_known?: PositionKnown;
  reason: Reason2;
  schema_version?: SchemaVersion13;
  state?: State;
}
export interface StorageStatus {
  discovery_performed?: DiscoveryPerformed1;
  local_mirror?: LocalMirror;
  reason: Reason3;
  schema_version?: SchemaVersion15;
  state?: State1;
}
export interface ApiError {
  code: Code;
  message: Message;
  phase?: Phase2;
  schema_version?: SchemaVersion16;
}
export interface GenerateRequest {
  prompt: Prompt;
  schema_version?: SchemaVersion17;
}
export interface DrawingDraft {
  chord_tolerance_mm: ChordToleranceMm;
  drawing_id: DrawingId;
  execution_ready?: ExecutionReady;
  exporter_version?: ExporterVersion;
  gcode: Gcode;
  gcode_sha256: GcodeSha256;
  geometry: PolylineDrawing;
  import_source?: ImportedSource | null;
  parent_revision_id: ParentRevisionId;
  preview: ExecutionPreview;
  prompt: Prompt1;
  revision: Revision2;
  revision_id: RevisionId;
  rounding_tolerance_mm?: RoundingToleranceMm;
  schema_version?: SchemaVersion22;
  simulation_profile?: SimulationProfile;
  spec: DrawingSpec;
  title: Title;
  transform: DrawingTransform;
  warnings: Warnings;
}
export interface ImportedSource {
  content_sha256: ContentSha256;
  dialect: Dialect2;
  filename: Filename;
  input_strokes: InputStrokes;
  notes: Notes1;
  original_bounds: DrawingBounds;
  schema_version?: SchemaVersion19;
}
export interface DrawingBounds {
  height_mm: HeightMm1;
  max_x_mm: MaxXMm1;
  max_y_mm: MaxYMm1;
  min_x_mm: MinXMm1;
  min_y_mm: MinYMm1;
  schema_version?: SchemaVersion18;
  width_mm: WidthMm1;
}
export interface ExecutionPreview {
  bounds: DrawingBounds;
  drawing_distance_mm: DrawingDistanceMm;
  expected_start_mm?: ExpectedStartMm;
  pen_lifts: PenLifts;
  schema_version?: SchemaVersion20;
  segments: Segments;
  strokes: Strokes1;
  travel_distance_mm: TravelDistanceMm;
}
export interface ExecutionSegment {
  end: End;
  pen_down: PenDown;
  schema_version?: SchemaVersion21;
  start: Start;
}
export interface DrawingTransform {
  offset_x_mm?: OffsetXMm;
  offset_y_mm?: OffsetYMm;
  preserve_aspect?: PreserveAspect;
  rotation_degrees?: RotationDegrees;
  schema_version?: SchemaVersion23;
}
export interface RevisionRequest {
  regenerate?: Regenerate;
  schema_version?: SchemaVersion24;
  seed_locked?: SeedLocked;
  spec?: DrawingSpec | null;
  transform?: DrawingTransform | null;
}
export interface ImportRequest {
  center_on_origin?: CenterOnOrigin;
  content: Content;
  dialect?: Dialect3;
  filename: Filename1;
  fit_height_mm?: FitHeightMm;
  fit_width_mm?: FitWidthMm;
  schema_version?: SchemaVersion25;
}
export interface HistoryResponse {
  items: Items;
  limit: Limit;
  offset: Offset;
  recovery_notices?: RecoveryNotices;
  schema_version?: SchemaVersion27;
  total: Total;
}
export interface HistoryEntry {
  created_at: CreatedAt;
  drawing_id: DrawingId1;
  generator: Generator1;
  integrity: Integrity;
  integrity_message?: IntegrityMessage;
  prompt: Prompt2;
  revision: Revision3;
  revision_id: RevisionId1;
  schema_version?: SchemaVersion26;
  title: Title1;
}
export interface CalibrationSaveRequest {
  calibration: CalibrationInput;
  expected_revision?: ExpectedRevision;
  schema_version?: SchemaVersion29;
  select_for_preparation?: SelectForPreparation;
}
export interface CalibrationInput {
  allowed_region: WorkRegion;
  anchor_y_mm: AnchorYMm2;
  base_reference_id: BaseReferenceId1;
  board: Board2;
  firmware?: Firmware1;
  firmware_config_id?: FirmwareConfigId1;
  firmware_matches_measurements?: FirmwareMatchesMeasurements1;
  label: Label2;
  measured_by: MeasuredBy1;
  measurement_notes: MeasurementNotes1;
  origin_procedure: OriginProcedure1;
  pen_down_degrees: PenDownDegrees2;
  pen_lift_and_holding_tested?: PenLiftAndHoldingTested1;
  pen_up_degrees: PenUpDegrees2;
  rope_max_mm: RopeMaxMm1;
  rope_min_mm: RopeMinMm1;
  schema_version?: SchemaVersion28;
  separation_mm: SeparationMm2;
  spool_diameter_mm: SpoolDiameterMm2;
  steps_per_turn: StepsPerTurn2;
  verified?: Verified2;
  workspace_tested?: WorkspaceTested1;
}
export interface PreparationRequest {
  mode?: Mode;
  profile_id?: ProfileId;
  profile_revision?: ProfileRevision;
  revision_id: RevisionId2;
  schema_version?: SchemaVersion30;
}
export interface PreparedJob {
  created_at: CreatedAt1;
  drawing_id: DrawingId2;
  expected_start_mm?: ExpectedStartMm1;
  gcode: Gcode1;
  gcode_crc32?: GcodeCrc32;
  gcode_sha256: GcodeSha2561;
  hardware_execution_verified?: HardwareExecutionVerified;
  id: Id2;
  manual_origin_required?: ManualOriginRequired;
  mode: Mode1;
  preview: ExecutionPreview;
  profile: CalibrationProfile | null;
  revision_id: RevisionId3;
  schema_version?: SchemaVersion31;
  state?: State2;
  title: Title2;
  warnings: Warnings1;
}
export interface TargetsResponse {
  auto_sync: AutoSyncState;
  discovery_error?: DiscoveryError;
  discovery_supported: DiscoverySupported;
  local_mirror_sha256?: LocalMirrorSha256;
  schema_version?: SchemaVersion33;
  selected_target_id: SelectedTargetId;
  targets: Targets;
}
export interface AutoSyncState {
  enabled?: Enabled;
  job_id?: JobId;
  last_transfer_id?: LastTransferId;
  message?: Message1;
  schema_version?: SchemaVersion32;
  status?: Status1;
  target_id?: TargetId;
}
export interface StorageTarget {
  available: Available1;
  current_main_sha256?: CurrentMainSha256;
  filesystem: Filesystem;
  id: Id3;
  instance: Instance;
  kind: Kind;
  label: Label3;
  path: Path;
  reason: Reason4;
  schema_version?: SchemaVersion34;
  volume_uuid: VolumeUuid;
  writable: Writable;
}
export interface TargetSelectionRequest {
  schema_version?: SchemaVersion35;
  target_id: TargetId1;
}
export interface ExportRequest {
  acknowledge_replace?: AcknowledgeReplace;
  computer_owns_card?: ComputerOwnsCard;
  expected_existing_sha256?: ExpectedExistingSha256;
  expected_job_sha256: ExpectedJobSha256;
  expected_local_mirror_sha256?: ExpectedLocalMirrorSha256;
  manual_start_understood?: ManualStartUnderstood;
  schema_version?: SchemaVersion36;
  stage_local_mirror?: StageLocalMirror;
  target_id: TargetId2;
}
export interface StageRequest {
  acknowledge_replace?: AcknowledgeReplace1;
  expected_existing_sha256?: ExpectedExistingSha2561;
  schema_version?: SchemaVersion37;
}
export interface TransferRecord {
  backup: Backup;
  bytes_verified?: BytesVerified;
  created_at: CreatedAt2;
  gcode_sha256: GcodeSha2562;
  id: Id4;
  job_id: JobId1;
  local_mirror_updated?: LocalMirrorUpdated;
  message: Message2;
  previous_sha256: PreviousSha256;
  schema_version?: SchemaVersion38;
  status: Status2;
  target_id: TargetId3;
  target_kind: TargetKind;
}
export interface AutoSyncRequest {
  enabled: Enabled1;
  export?: ExportRequest | null;
  job_id?: JobId2;
  schema_version?: SchemaVersion39;
}
export interface SessionResponse {
  schema_version?: SchemaVersion40;
  write_token: WriteToken;
}
export interface ProfileSelectionRequest {
  expected_revision: ExpectedRevision1;
  profile_id: ProfileId1;
  schema_version?: SchemaVersion41;
}
export interface PortsResponse {
  error?: Error;
  ports: Ports;
  schema_version?: SchemaVersion43;
}
export interface SerialPortInfo {
  accessible?: Accessible;
  description: Description;
  device: Device;
  hwid: Hwid;
  likely_arduino: LikelyArduino;
  schema_version?: SchemaVersion42;
  simulated?: Simulated;
}
export interface MachineState {
  connection: Connection;
  hello?: DeviceHello | null;
  message: Message3;
  port?: Port;
  recent_runs?: RecentRuns;
  run?: UsbRun | null;
  schema_version?: SchemaVersion46;
  simulated?: Simulated1;
  status?: DeviceStatus | null;
  status_age_s?: StatusAgeS;
}
export interface DeviceHello {
  boot_id: BootId;
  capabilities: Capabilities;
  config_id: ConfigId;
  dialect: Dialect4;
  firmware_version: FirmwareVersion;
  protocol: Protocol;
  schema_version?: SchemaVersion44;
}
export interface UsbRun {
  acknowledged_seq?: AcknowledgedSeq;
  boot_id: BootId1;
  current_line?: CurrentLine;
  id: Id5;
  job_id: JobId3;
  measured_feedback?: MeasuredFeedback;
  message: Message4;
  origin_revision: OriginRevision;
  port: Port1;
  position_mm?: PositionMm;
  schema_version?: SchemaVersion45;
  sent_seq?: SentSeq;
  started_at: StartedAt;
  state: State3;
  title: Title3;
  token: Token;
  total_commands: TotalCommands;
  updated_at: UpdatedAt;
}
export interface DeviceStatus {
  boot_id: BootId2;
  completed_seq: CompletedSeq;
  job: Job;
  observed_at: ObservedAt;
  origin: Origin;
  origin_revision: OriginRevision1;
  pen_down: PenDown1;
  position_mm: PositionMm1;
  position_source?: PositionSource;
  reason: Reason5;
  received_seq: ReceivedSeq;
  result: Result;
  schema_version?: SchemaVersion47;
  state: State4;
}
export interface ConnectRequest {
  port: Port2;
  schema_version?: SchemaVersion48;
}
export interface UsbStartRequest {
  area_clear_confirmed?: AreaClearConfirmed;
  expected_boot_id: ExpectedBootId;
  expected_config_id: ExpectedConfigId;
  expected_origin_revision: ExpectedOriginRevision;
  schema_version?: SchemaVersion49;
}
export interface HomeRequest {
  expected_boot_id: ExpectedBootId1;
  expected_origin_revision: ExpectedOriginRevision1;
  route_confirmed?: RouteConfirmed;
  schema_version?: SchemaVersion50;
}
