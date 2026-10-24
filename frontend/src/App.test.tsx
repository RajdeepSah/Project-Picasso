import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, describe, it, expect } from 'vitest';
import App from './App';
import * as api from './api/client';
import type { Studio } from './api/client';

const capability = { available: false, phase: 3, reason: 'Offline drawing generation arrives in Phase 3. No drawing has been generated.' };
const studio: Studio = {
  health: { version: '0.2.0', instance_id: 'test', frontend_ready: true, python_version: '3.14.4' },
  capabilities: { dashboard: { ...capability, available: true }, generation: capability, history: capability,
    gcode_export: capability, sd_export: capability, serial_control: capability, ai: capability, voice: capability },
  profiles: { profiles: [] },
  status: { machine: { reason: 'No discovery implemented.' }, storage: { reason: 'No card configured.' } },
};

describe('local studio', () => {
  it('submits a command without fabricating a drawing, and preserves the input', async () => {
    vi.spyOn(api, 'loadStudio').mockResolvedValue(studio);
    const submit = vi.spyOn(api, 'submitCommand').mockResolvedValue({ code: 'GENERATION_UNAVAILABLE', message: capability.reason, phase: 3 });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('Running locally');
    await user.click(screen.getByRole('button', { name: 'Draw a circle' }));
    const input = screen.getByRole('textbox', { name: 'Drawing command' });
    expect(input).toHaveValue('Draw a circle');
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    await waitFor(() => expect(submit).toHaveBeenCalledWith('Draw a circle', expect.any(AbortSignal)));
    expect(await screen.findByText(capability.reason)).toBeVisible();
    expect(input).toHaveValue('Draw a circle');
    expect(screen.getByText('The page is yours.')).toBeVisible();
    expect(screen.getByRole('button', { name: /Voice input unavailable/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Prepare for drawing/ })).toBeDisabled();
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

  it('does not submit Shift+Enter and has functional preview controls', async () => {
    vi.spyOn(api, 'loadStudio').mockResolvedValue(studio);
    const submit = vi.spyOn(api, 'submitCommand');
    render(<App />);
    await screen.findByText('Running locally');
    const input = screen.getByRole('textbox', { name: 'Drawing command' });
    fireEvent.change(input, { target: { value: 'Draw a circle' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Toggle preview grid' }));
    expect(screen.getByRole('button', { name: 'Toggle preview grid' })).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(screen.getByLabelText('Preview zoom')).toHaveTextContent('125%');
    fireEvent.click(screen.getByRole('button', { name: 'Reset preview zoom' }));
    expect(screen.getByLabelText('Preview zoom')).toHaveTextContent('100%');
  });
});
