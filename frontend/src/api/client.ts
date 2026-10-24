import type { ApiError, CapabilitiesResponse, HealthResponse, ProfilesResponse, StudioStatus } from './contracts';

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

export async function submitCommand(prompt: string, signal: AbortSignal): Promise<ApiError> {
  const response = await fetch('/api/drawings/generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
    signal: AbortSignal.any([signal, AbortSignal.timeout(5000)]),
  });
  if (response.status !== 501) throw new Error('The command could not be processed. Please try again.');
  return response.json() as Promise<ApiError>;
}
