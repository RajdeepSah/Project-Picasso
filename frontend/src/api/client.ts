import type { ApiError, CapabilitiesResponse, DrawingDraft, HealthResponse, ProfilesResponse, RevisionRequest, StudioStatus } from './contracts';

export type Studio = {
  health: HealthResponse;
  capabilities: CapabilitiesResponse;
  profiles: ProfilesResponse;
  status: StudioStatus;
};

async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal: AbortSignal.any([signal, AbortSignal.timeout(5000)]), cache: 'no-store' });
  if (!response.ok) throw new Error('The local service could not be reached.');
  return response.json() as Promise<T>;
}

export async function loadStudio(signal: AbortSignal): Promise<Studio> {
  const [health, capabilities, profiles, status] = await Promise.all([
    get<HealthResponse>('/api/health', signal),
    get<CapabilitiesResponse>('/api/capabilities', signal),
    get<ProfilesResponse>('/api/profiles', signal),
    get<StudioStatus>('/api/status', signal),
  ]);
  return { health, capabilities, profiles, status };
}

async function drawingRequest<T>(path: string, payload: unknown, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null) as ApiError | null;
    throw new Error(error?.message ?? 'The drawing could not be generated. Please try again.');
  }
  return response.json() as Promise<T>;
}

export function submitCommand(prompt: string, signal: AbortSignal): Promise<DrawingDraft> {
  return drawingRequest('/api/drawings/generate', { prompt }, signal);
}

export function reviseDraft(id: string, payload: RevisionRequest, signal: AbortSignal): Promise<DrawingDraft> {
  return drawingRequest(`/api/drawings/${encodeURIComponent(id)}/revisions`, payload, signal);
}

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
