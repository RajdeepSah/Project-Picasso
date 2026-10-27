import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import * as api from '../api/client';
import type { Studio } from '../api/client';

const on = { available: true, phase: 8, reason: 'Offline speech recognition.' };
const off = { available: false, phase: 4, reason: 'Future feature.' };
const studio = (voice = on): Studio => ({
  health: { version: '0.6.0', instance_id: 'test', frontend_ready: true, python_version: '3.14.4' },
  capabilities: { dashboard: on, generation: on, history: off, gcode_export: on, sd_export: off, firmware: off, serial_control: off, ai: off, voice },
  profiles: { profiles: [] },
  status: { machine: { reason: 'No discovery implemented.' }, storage: { reason: 'No card configured.' } },
});

class FakeRecorder {
  static isTypeSupported = () => true;
  state = 'inactive'; mimeType = 'audio/webm;codecs=opus';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start() { this.state = 'recording'; }
  stop() { this.state = 'inactive'; this.ondataavailable?.({ data: new Blob(['opus'], { type: this.mimeType }) }); this.onstop?.(); }
}
const track = { stop: vi.fn() };
const getUserMedia = vi.fn();

async function open(voice = on) {
  vi.spyOn(api, 'loadStudio').mockResolvedValue(studio(voice));
  vi.spyOn(api, 'warmVoice').mockResolvedValue(on);
  const submit = vi.spyOn(api, 'submitCommand');
  render(<App />);
  await screen.findByText('Running locally');
  return { submit, box: screen.getByRole('textbox', { name: 'Drawing command' }) as HTMLTextAreaElement };
}

describe('voice input', () => {
  beforeEach(() => {
    vi.stubGlobal('MediaRecorder', FakeRecorder);
    getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [track] });
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
  });
  afterEach(() => { Reflect.deleteProperty(navigator, 'mediaDevices'); });

  it('records, inserts the recognized command into the composer and never submits it', async () => {
    const transcribe = vi.spyOn(api, 'transcribeAudio').mockResolvedValue({ text: 'Draw a butterfly', duration_s: 2.1, processing_s: 0.8 });
    const { submit, box } = await open();
    fireEvent.click(screen.getByRole('button', { name: 'Start voice input' }));
    const stop = await screen.findByRole('button', { name: 'Stop recording and transcribe' });
    expect(stop).toHaveAttribute('aria-pressed', 'true');
    expect(getUserMedia).toHaveBeenCalledWith({ audio: expect.objectContaining({ channelCount: 1 }) });
    expect(api.warmVoice).toHaveBeenCalled();
    fireEvent.click(stop);
    await waitFor(() => expect(box).toHaveValue('Draw a butterfly'));
    const audio = transcribe.mock.calls[0][0];
    expect(audio).toBeInstanceOf(Blob);
    expect(audio.type).toBe('audio/webm;codecs=opus');
    expect(track.stop).toHaveBeenCalled();
    expect(screen.getByText('Heard “Draw a butterfly”. Review or edit it, then press Enter to draw.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start voice input' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Submit drawing command' })).toBeEnabled();
    expect(submit).not.toHaveBeenCalled();
  });

  it('adds dictation at the cursor and replaces a selection', async () => {
    const transcribe = vi.spyOn(api, 'transcribeAudio').mockResolvedValue({ text: '120 mm wide', duration_s: 1, processing_s: 0.5 });
    const { box } = await open();
    fireEvent.change(box, { target: { value: 'Draw a mandala' } });
    box.setSelectionRange(14, 14);
    fireEvent.click(screen.getByRole('button', { name: 'Start voice input' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop recording and transcribe' }));
    await waitFor(() => expect(box).toHaveValue('Draw a mandala 120 mm wide'));
    transcribe.mockResolvedValue({ text: 'Draw a spiral', duration_s: 1, processing_s: 0.5 });
    box.setSelectionRange(0, box.value.length);
    fireEvent.click(screen.getByRole('button', { name: 'Start voice input' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop recording and transcribe' }));
    await waitFor(() => expect(box).toHaveValue('Draw a spiral'));
  });

  it('Escape cancels a recording without transcribing it', async () => {
    const transcribe = vi.spyOn(api, 'transcribeAudio');
    const { box } = await open();
    fireEvent.click(screen.getByRole('button', { name: 'Start voice input' }));
    await screen.findByRole('button', { name: 'Stop recording and transcribe' });
    fireEvent.keyDown(window, { key: 'Escape' });
    await screen.findByRole('button', { name: 'Start voice input' });
    expect(screen.getByText('Voice input cancelled.')).toBeVisible();
    expect(transcribe).not.toHaveBeenCalled();
    expect(box).toHaveValue('');
  });

  it('explains a blocked microphone and keeps typing available', async () => {
    getUserMedia.mockRejectedValue(new DOMException('denied', 'NotAllowedError'));
    const { box } = await open();
    fireEvent.click(screen.getByRole('button', { name: 'Start voice input' }));
    expect(await screen.findByText(/Microphone access was blocked/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Start voice input' })).toBeEnabled();
    expect(box).toBeEnabled();
  });

  it('shows recognition errors from the local service', async () => {
    vi.spyOn(api, 'transcribeAudio').mockRejectedValue(new Error('No speech was recognized.'));
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Start voice input' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Stop recording and transcribe' }));
    expect(await screen.findByText('No speech was recognized.')).toBeVisible();
  });

  it('reports a browser without recording support', async () => {
    Reflect.deleteProperty(navigator, 'mediaDevices');
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Start voice input' }));
    expect(await screen.findByText(/This browser cannot record audio/)).toBeVisible();
  });

  it('is disabled with the reason when the speech model is not installed', async () => {
    await open({ available: false, phase: 8, reason: 'Voice input needs the offline speech model.' });
    expect(screen.getByRole('button', { name: 'Voice input unavailable: Voice input needs the offline speech model.' })).toBeDisabled();
  });
});
