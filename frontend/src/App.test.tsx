import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, describe, it, expect } from 'vitest';
import App from './App';
import * as api from './api/client';
import type { Studio } from './api/client';
import type { DrawingDraft } from './api/contracts';
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
  fireEvent.click(screen.getByRole('button', { name: 'Draw a circle' }));
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
});
