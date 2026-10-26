import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import * as api from '../api/client';
import type { DrawingDraft } from '../api/contracts';
import circle from '../testing/circle.json';
import { ImportDialog } from './ImportDialog';

const fixture = circle as unknown as DrawingDraft;

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.open = true; };
  URL.createObjectURL ??= () => 'blob:thumbnail';
  URL.revokeObjectURL ??= () => {};
  Blob.prototype.text ??= function (this: Blob) {  // jsdom omits Blob.text
    return new Promise(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(this); });
  };
});

describe('ImportDialog', () => {
  it('traces an image at the chosen detail, fitted inside the selected page', async () => {
    const importDrawing = vi.spyOn(api, 'importDrawing').mockResolvedValue(fixture);
    const imported = vi.fn();
    render(<ImportDialog paper="A4-portrait" close={() => {}} imported={imported} />);
    await userEvent.upload(screen.getByLabelText('Drawing file'), new File([new Uint8Array([137, 80, 78, 71])], 'cat.png', { type: 'image/png' }));
    expect(screen.getByText('cat.png')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'High' }));
    expect(screen.getByText(/Finer edges and patterns/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(imported).toHaveBeenCalledWith(fixture));
    const request = importDrawing.mock.calls[0][0];
    expect(request).toMatchObject({ filename: 'cat.png', kind: 'image', detail: 'high', content: 'iVBORw==' });
    expect(request.fit_width_mm).toBeCloseTo(178.5);
    expect(request.fit_height_mm).toBeCloseTo(252.45);
  });

  it('reads G-code as text, keeps its coordinates and hides image detail', async () => {
    const importDrawing = vi.spyOn(api, 'importDrawing').mockResolvedValue(fixture);
    render(<ImportDialog paper="fit" close={() => {}} imported={() => {}} />);
    await userEvent.click(screen.getByRole('radio', { name: 'G-code' }));
    expect(screen.queryByRole('radio', { name: 'Medium' })).not.toBeInTheDocument();
    await userEvent.upload(screen.getByLabelText('Drawing file'), new File(['G0 X0 Y0 Z5\n'], 'path.nc'));
    await userEvent.click(screen.getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(importDrawing).toHaveBeenCalledWith({ filename: 'path.nc', kind: 'gcode', content: 'G0 X0 Y0 Z5\n' }, expect.any(AbortSignal)));
  });

  it('rejects oversized files before uploading and shows service errors', async () => {
    const importDrawing = vi.spyOn(api, 'importDrawing').mockRejectedValue(new Error('No outlines were found in this image.'));
    render(<ImportDialog paper="fit" close={() => {}} imported={() => {}} />);
    const input = screen.getByLabelText('Drawing file');
    await userEvent.upload(input, new File([new Uint8Array(8_000_001)], 'huge.jpg', { type: 'image/jpeg' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Images must be 8.0 MB or smaller.');
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled();
    await userEvent.upload(input, new File([new Uint8Array(4)], 'blank.png', { type: 'image/png' }));
    await userEvent.click(screen.getByRole('button', { name: 'Import' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No outlines were found');
    expect(importDrawing).toHaveBeenCalledTimes(1);
  });
});
