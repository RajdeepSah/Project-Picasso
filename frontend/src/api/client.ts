import type { ApiError, AutoSyncRequest, AutoSyncState, CalibrationProfile, CalibrationSaveRequest, CapabilitiesResponse, Capability,
  DrawingDraft, ExportRequest, HealthResponse, HistoryResponse, HomeRequest, ImportRequest, MachineState, PortsResponse, PreparedJob,
  ProfilesResponse, RevisionRequest, SessionResponse, StageRequest, StorageTarget, StudioStatus, TargetsResponse, TransferRecord,
  UsbRun, UsbStartRequest, VoiceTranscript } from './contracts';

let writeToken = '';
const freshSignal = () => new AbortController().signal;

export type Studio = {
  health: HealthResponse;
  capabilities: CapabilitiesResponse;
  profiles: ProfilesResponse;
  status: StudioStatus;
};

async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal: AbortSignal.any([signal, AbortSignal.timeout(5000)]), cache: 'no-store' });
  if (!response.ok) {
    const error = await response.json().catch(() => null) as ApiError | null;
    throw new Error(error?.message ?? 'The local service could not be reached.');
  }
  return response.json() as Promise<T>;
}

export async function loadStudio(signal: AbortSignal): Promise<Studio> {
  const [health, capabilities, profiles, status, session] = await Promise.all([
    get<HealthResponse>('/api/health', signal),
    get<CapabilitiesResponse>('/api/capabilities', signal),
    get<ProfilesResponse>('/api/profiles', signal),
    get<StudioStatus>('/api/status', signal),
    get<SessionResponse>('/api/session', signal),
  ]);
  writeToken = session.write_token;
  return { health, capabilities, profiles, status };
}

async function send<T>(path: string, body: BodyInit, contentType: string, signal: AbortSignal, method: string, timeout: number, fallback: string, refresh = true): Promise<T> {
  if (!writeToken) writeToken = (await get<SessionResponse>('/api/session', signal)).write_token;
  const response = await fetch(path, {
    method, headers: { 'Content-Type': contentType, 'X-Picasso-Token': writeToken }, body,
    signal: AbortSignal.any([signal, AbortSignal.timeout(timeout)]),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null) as ApiError | null;
    if (refresh && response.status === 403 && error?.code === 'WRITE_TOKEN_REQUIRED') {
      writeToken = '';
      return send<T>(path, body, contentType, signal, method, timeout, fallback, false);
    }
    throw new Error(error?.message ?? fallback);
  }
  return response.json() as Promise<T>;
}

export function mutate<T>(path: string, payload: unknown, signal: AbortSignal, method = 'POST'): Promise<T> {
  return send<T>(path, JSON.stringify(payload), 'application/json', signal, method, 30000, 'The drawing could not be generated. Please try again.');
}

// Voice returns text for the composer only; it never generates or starts a drawing.
export const warmVoice = () => mutate<Capability>('/api/voice/warm', {}, freshSignal());
export const transcribeAudio = (audio: Blob, signal: AbortSignal) =>
  send<VoiceTranscript>('/api/voice/transcribe', audio, audio.type || 'application/octet-stream', signal, 'POST', 60000, 'Speech could not be transcribed. Type the command instead.');

export function submitCommand(prompt: string, signal: AbortSignal): Promise<DrawingDraft> {
  return mutate('/api/drawings/generate', { prompt }, signal);
}

export function reviseDraft(id: string, payload: RevisionRequest, signal: AbortSignal): Promise<DrawingDraft> {
  return mutate(`/api/drawings/${encodeURIComponent(id)}/revisions`, payload, signal);
}

export const fetchDraft = (id: string, signal: AbortSignal) => get<DrawingDraft>(`/api/drawings/${encodeURIComponent(id)}`, signal);
export const fetchHistory = (query: string, offset: number, signal: AbortSignal) => get<HistoryResponse>(`/api/drawings?query=${encodeURIComponent(query)}&offset=${offset}&limit=12`, signal);
export const repairArtifact = (id: string) => mutate(`/api/artifacts/${encodeURIComponent(id)}/repair`, {}, freshSignal());
export const importDrawing = (payload: ImportRequest, signal: AbortSignal) => mutate<DrawingDraft>('/api/drawings/import', payload, signal);
export const saveCalibration = (payload: CalibrationSaveRequest, id?: string) => mutate<CalibrationProfile>(id ? `/api/profiles/${id}` : '/api/profiles', payload, freshSignal(), id ? 'PUT' : 'POST');
export const selectCalibration = (profile: CalibrationProfile) => mutate<ProfilesResponse>('/api/profiles/select', { profile_id: profile.id, expected_revision: profile.revision }, freshSignal());
export const prepareJob = (revision_id: string, mode: 'simulation' | 'physical', profile?: CalibrationProfile) => mutate<PreparedJob>('/api/jobs/prepare', { revision_id, mode, profile_id: mode === 'physical' ? profile?.id : undefined, profile_revision: mode === 'physical' ? profile?.revision : undefined }, freshSignal());
export const fetchJobs = (id: string, signal: AbortSignal) => get<PreparedJob[]>(`/api/jobs?revision_id=${encodeURIComponent(id)}`, signal);
export const fetchJob = (id: string, signal: AbortSignal) => get<PreparedJob>(`/api/jobs/${encodeURIComponent(id)}`, signal);
export const fetchTargets = (signal = freshSignal()) => get<TargetsResponse>('/api/storage/targets', signal);
export const createTestTarget = () => mutate<StorageTarget>('/api/storage/test-target', {}, freshSignal());
export const selectTarget = (target_id: string) => mutate<TargetsResponse>('/api/storage/select', { target_id }, freshSignal());
export const exportJob = (id: string, request: ExportRequest) => mutate<TransferRecord>(`/api/jobs/${id}/sd-export`, request, freshSignal());
export const stageJob = (id: string, request: StageRequest) => mutate<TransferRecord>(`/api/jobs/${id}/stage`, request, freshSignal());
export const armAutoSync = (request: AutoSyncRequest) => mutate<AutoSyncState>('/api/storage/auto-sync', request, freshSignal());
export const fetchTransfers = () => get<TransferRecord[]>('/api/storage/transfers', freshSignal());
export const fetchPorts = () => get<PortsResponse>('/api/machine/ports', freshSignal());
export const fetchMachine = (signal = freshSignal()) => get<MachineState>('/api/machine', signal);
export const connectMachine = (port: string) => mutate<MachineState>('/api/machine/connect', { port }, freshSignal());
export const disconnectMachine = () => mutate<MachineState>('/api/machine/disconnect', {}, freshSignal());
export const homeMachine = (request: HomeRequest) => mutate<MachineState>('/api/machine/home', request, freshSignal());
export const controlMachine = (action: 'pause' | 'resume' | 'stop') => mutate<MachineState>(`/api/machine/${action}`, {}, freshSignal());
export const startUsbRun = (jobId: string, request: UsbStartRequest) => mutate<UsbRun>(`/api/jobs/${encodeURIComponent(jobId)}/usb-start`, request, freshSignal());

export async function downloadDraft(id: string, format: 'json' | 'svg' | 'gcode', signal: AbortSignal) {
  const response = await fetch(`/api/drawings/${encodeURIComponent(id)}/export?format=${format}`, {
    signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]), cache: 'no-store',
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null) as ApiError | null;
    throw new Error(error?.message ?? 'Draft download failed. Please try again.');
  }
  return { blob: await response.blob(), filename: response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] ?? `picasso-UNVERIFIED.${format === 'gcode' ? 'nc' : format}` };
}
