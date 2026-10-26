import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, describe, it, expect } from 'vitest';
import App from './App';
import * as api from './api/client';
import type { Studio } from './api/client';
import type { DrawingDraft, MachineState, PortsResponse, PreparedJob } from './api/contracts';
import circle from './testing/circle.json';

const fixture = circle as unknown as DrawingDraft;
const planned = { available: false, phase: 4, reason: 'Future feature.' };
const studio: Studio = {
  health: { version: '0.3.0', instance_id: 'test', frontend_ready: true, python_version: '3.14.4' },
  capabilities: { dashboard: { ...planned, available: true }, generation: { ...planned, available: true }, history: planned,
    gcode_export: { ...planned, available: true }, sd_export: planned, firmware: planned, serial_control: planned, ai: planned, voice: planned },
  profiles: { profiles: [] },
  status: { machine: { reason: 'No discovery implemented.' }, storage: { reason: 'No card configured.' } },
};

async function generateCircle() {
  vi.spyOn(api, 'loadStudio').mockResolvedValue(studio);
  const submit = vi.spyOn(api, 'submitCommand').mockResolvedValue(structuredClone(fixture));
  render(<App />);
  await screen.findByText('Running locally');
  fireEvent.click(screen.getByRole('button', { name: 'Circle' }));
  fireEvent.keyDown(screen.getByRole('textbox', { name: 'Drawing command' }), { key: 'Enter' });
  await screen.findByRole('img', { name: 'Circle drawing path preview, simulation only' });
  return submit;
}

describe('offline drawing studio', () => {
  it('submits a real drawing command and displays exported paths without enabling hardware', async () => {
    const submit = await generateCircle();
    expect(submit).toHaveBeenCalledWith('Draw a circle', expect.any(AbortSignal));
    expect(screen.getByTestId('drawing-path')).toHaveAttribute('d', expect.stringContaining('M'));
    expect(screen.getByTestId('actual-bounds')).toHaveTextContent('120.00 × 120.00 mm');
    expect(screen.getByRole('button', { name: /Voice input unavailable/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Export G-code' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'More export options' }));
    expect(screen.getByRole('button', { name: /Prepare for drawing/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Draft JSON/ })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Toggle travel paths' }));
    expect(screen.queryByTestId('travel-path')).not.toBeInTheDocument();
  });

  it('keeps the prior drawing when a new command is unsupported', async () => {
    const submit = await generateCircle();
    submit.mockRejectedValueOnce(new Error('Choose one supported drawing.'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Drawing command' }), { target: { value: 'Draw a cat' } });
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Drawing command' }), { key: 'Enter' });
    await screen.findByText('Choose one supported drawing.');
    expect(screen.getByRole('img', { name: /Circle drawing path/ })).toHaveAttribute('data-gcode-sha256', fixture.gcode_sha256);
  });

  it('updates dimensions with aspect lock and ignores an obsolete revision response', async () => {
    let complete!: (draft: DrawingDraft) => void;
    const revise = vi.spyOn(api, 'reviseDraft').mockReturnValue(new Promise(resolve => { complete = resolve; }));
    await generateCircle();
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Drawing width in millimetres' }), { target: { value: '140' } });
    expect(screen.getByRole('spinbutton', { name: 'Drawing height in millimetres' })).toHaveValue(140);
    await waitFor(() => expect(revise).toHaveBeenCalled(), { timeout: 2000 });
    expect(revise.mock.calls[0][1].spec?.dimensions).toEqual({ width_mm: 140, height_mm: 140 });
    fireEvent.click(screen.getByRole('button', { name: /drawing options/ }));
    fireEvent.click(screen.getByRole('button', { name: /New drawing/ }));
    await act(async () => complete({ ...fixture, revision_id: 'stale-r2', revision: 2 }));
    expect(screen.queryByRole('img', { name: /drawing path preview/ })).not.toBeInTheDocument();
    expect(screen.getByText('The page is yours.')).toBeVisible();
  });

  it('recovers from backend failure while keeping a drafted command', async () => {
    const load = vi.spyOn(api, 'loadStudio').mockRejectedValueOnce(new Error('Offline')).mockResolvedValue(studio);
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The local service is offline');
    fireEvent.change(screen.getByRole('textbox', { name: 'Drawing command' }), { target: { value: 'A mandala' } });
    expect(screen.getByRole('button', { name: 'Submit drawing command' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }));
    await screen.findByText('Running locally');
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('textbox', { name: 'Drawing command' })).toHaveValue('A mandala');
  });

  it('keeps Shift+Enter for multiline input and provides grid and zoom controls', async () => {
    vi.spyOn(api, 'loadStudio').mockResolvedValue(studio);
    const submit = vi.spyOn(api, 'submitCommand');
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('Running locally');
    await user.type(screen.getByRole('textbox', { name: 'Drawing command' }), 'Draw a circle');
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Drawing command' }), { key: 'Enter', shiftKey: true });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Toggle preview grid' }));
    expect(screen.getByRole('button', { name: 'Toggle preview grid' })).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(screen.getByRole('status', { name: 'Preview zoom' })).toHaveTextContent('125%');
  });

  it('offers Execute beside Simulation only for a settled drawing', async () => {
    vi.spyOn(api, 'reviseDraft').mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, 'loadStudio').mockResolvedValue(studio);
    render(<App />);
    await screen.findByText('Running locally');
    expect(screen.getByRole('button', { name: 'Execute' })).toBeDisabled();
    cleanup();
    await generateCircle();
    expect(screen.getByRole('button', { name: 'Execute' })).toBeEnabled();
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Drawing width in millimetres' }), { target: { value: '140' } });
    expect(screen.getByRole('button', { name: 'Execute' })).toBeDisabled();
  });

  it('opens the USB sheet, explains port permissions and asks for a verified profile first', async () => {
    const ports: PortsResponse = { ports: [{ device: '/dev/ttyUSB0', description: 'USB Serial', hwid: '1A86:7523', likely_arduino: true, accessible: false }] };
    vi.spyOn(api, 'fetchPorts').mockResolvedValue(ports);
    const prepare = vi.spyOn(api, 'prepareJob');
    // jsdom has no modal dialogs; opening is all the sheet needs.
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.setAttribute('open', ''); } });
    await generateCircle();
    fireEvent.click(screen.getByRole('button', { name: 'Execute' }));
    const sheet = await screen.findByRole('dialog', { name: 'Draw it on the machine' });
    expect(await within(sheet).findByText(/sudo usermod -aG dialout/)).toBeVisible();
    expect(within(sheet).getByRole('button', { name: 'Record measurements' })).toBeVisible();
    expect(within(sheet).getByRole('button', { name: 'Start drawing' })).toBeDisabled();
    expect(prepare).not.toHaveBeenCalled();
  });

  it('shows acknowledged progress on the preview with an always-visible Stop', async () => {
    const run = { id: 'run-1', job_id: 'job-1', title: 'Circle', port: '/dev/ttyUSB0', boot_id: '0000002a', origin_revision: 1, token: '0a0b0c0d',
      total_commands: fixture.gcode.split('\n').filter(Boolean).length, acknowledged_seq: 2, state: 'streaming', message: 'Streaming.',
      position_mm: [60, 0], started_at: '', updated_at: '' };
    vi.spyOn(api, 'fetchMachine').mockResolvedValue({ connection: 'connected', message: '', run } as unknown as MachineState);
    vi.spyOn(api, 'fetchJob').mockResolvedValue({ id: 'job-1', revision_id: fixture.revision_id } as unknown as PreparedJob);
    const control = vi.spyOn(api, 'controlMachine').mockResolvedValue({ connection: 'connected', message: '' } as unknown as MachineState);
    await generateCircle();
    expect(await screen.findByRole('button', { name: /Executing · 3%/ })).toBeEnabled();
    expect(await screen.findByTestId('machine-cursor')).toHaveAttribute('cx', '60');
    expect(screen.getByRole('slider', { name: 'Simulation progress' })).toHaveValue('14');
    fireEvent.click(screen.getByRole('button', { name: 'Stop the machine' }));
    expect(control).toHaveBeenCalledWith('stop');
  });
});
