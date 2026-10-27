import { expect, test, type Page } from '@playwright/test';
import { mkdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

async function command(page: Page, text: string) {
  await page.getByRole('textbox', { name: 'Drawing command' }).fill(text);
  const response = page.waitForResponse(response => response.url().endsWith('/api/drawings/generate') && response.request().method() === 'POST');
  await page.getByRole('textbox', { name: 'Drawing command' }).press('Enter');
  const result = await response;
  expect(result.status()).toBe(200);
  const draft = await result.json();
  await expect(page.getByRole('img', { name: /drawing path preview, simulation only/ })).toHaveAttribute('data-gcode-sha256', draft.gcode_sha256);
  return draft;
}

/** A control in the Export menu beside Export G-code, opening the menu when it is closed. */
async function exportOption(page: Page, name: string) {
  const more = page.getByRole('button', { name: 'More export options' });
  if (await more.getAttribute('aria-expanded') !== 'true') await more.click();
  return page.locator('#export-options').getByRole('button', { name });
}

async function importFile(page: Page, kind: 'Image' | 'G-code', path: string, detail?: 'Low' | 'Medium' | 'High') {
  await page.getByRole('button', { name: 'Import drawing', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Import a drawing' });
  await dialog.getByRole('radio', { name: kind }).click();
  await dialog.getByLabel('Drawing file', { exact: true }).setInputFiles(path);
  if (detail) await dialog.getByText(detail, { exact: true }).click();
  const response = page.waitForResponse(response => response.url().endsWith('/api/drawings/import') && response.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Import', exact: true }).click();
  const result = await response;
  expect(result.status()).toBe(200);
  const draft = await result.json();
  await expect(page.getByRole('img', { name: /Imported drawing path/ })).toHaveAttribute('data-gcode-sha256', draft.gcode_sha256);
  return draft;
}

async function revision(page: Page, action: () => Promise<unknown>) {
  const response = page.waitForResponse(response => response.url().endsWith('/revisions') && response.request().method() === 'POST');
  await action();
  const result = await response;
  expect(result.status()).toBe(200);
  const draft = await result.json();
  await expect(page.getByRole('status').filter({ hasText: `revision ${draft.revision}.` })).toBeVisible();
  return draft;
}

test('offline circle to resized mandala, regeneration, named G-code/SVG/PNG downloads and profile inspection', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeVisible();
  await command(page, 'Draw a circle diameter 100');
  await expect(page.getByTestId('actual-bounds')).toHaveText('100.00 × 100.00 mm');
  const resized = await revision(page, () => page.getByRole('spinbutton', { name: 'Drawing width in millimetres' }).fill('140'));
  expect(resized.preview.bounds.width_mm).toBe(140);
  expect(resized.preview.bounds.height_mm).toBe(140);
  await command(page, 'Create a beautiful mandala with 12 petals, seed 7');
  const regenerated = await revision(page, () => page.getByRole('button', { name: 'Regenerate drawing' }).click());
  expect(regenerated.spec.seed).toBe(8);
  await page.getByRole('button', { name: 'Advanced' }).click();
  await page.getByRole('checkbox', { name: 'Keep seed when regenerating' }).check();
  const retained = await revision(page, () => page.getByRole('button', { name: 'Regenerate drawing' }).click());
  expect(retained.gcode_sha256).toBe(regenerated.gcode_sha256);
  expect(retained.revision_id).not.toBe(regenerated.revision_id);
  await expect(page.getByRole('button', { name: /Voice input unavailable/ })).toBeDisabled();
  const name = `picasso-mandala-${retained.preview.bounds.width_mm.toFixed(0)}x${retained.preview.bounds.height_mm.toFixed(0)}mm-rev${retained.revision}`;
  await expect(await exportOption(page, 'SVG')).toBeEnabled();
  await expect(page.locator('#export-options').getByRole('button')).toHaveText(['G-code', 'SVG', 'PNG']);
  const downloadSvg = page.waitForEvent('download');
  await (await exportOption(page, 'SVG')).click();
  const svgFile = await downloadSvg;
  expect(svgFile.suggestedFilename()).toBe(`${name}.svg`);
  expect(await readFile((await svgFile.path())!, 'utf8')).toContain(retained.gcode_sha256);
  const downloadPng = page.waitForEvent('download');
  await (await exportOption(page, 'PNG')).click();
  const pngFile = await downloadPng;
  expect(pngFile.suggestedFilename()).toBe(`${name}.png`);
  expect((await readFile((await pngFile.path())!)).subarray(0, 4).toString('latin1')).toBe('\x89PNG');
  await expect(page.getByRole('button', { name: 'Export G-code', exact: true })).toBeEnabled();
  const downloadCode = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export G-code', exact: true }).click();
  const codeFile = await downloadCode;
  expect(codeFile.suggestedFilename()).toBe(`${name}.gcode`);
  const bytes = await readFile((await codeFile.path())!);
  expect(createHash('sha256').update(bytes).digest('hex')).toBe(retained.gcode_sha256);
  expect(bytes.toString()).toBe(retained.gcode);
  await page.getByRole('button', { name: 'Machine', exact: true }).click();
  await page.getByRole('combobox', { name: 'Inspect reference profile' }).selectOption('reference-400');
  await expect(page.getByText('400 mm', { exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/profiles')).json()).active_profile_id).toBeNull();
  await page.getByRole('button', { name: 'Drawing', exact: true }).click();
  await page.getByRole('button', { name: 'Toggle travel paths' }).click();
  await expect(page.getByTestId('travel-path')).not.toBeAttached();
  await page.getByRole('button', { name: 'Play simulation' }).click();
  await expect(page.getByRole('button', { name: 'Pause simulation' })).toBeEnabled();
  await page.getByRole('button', { name: 'Pause simulation' }).click();
  await page.getByRole('slider', { name: 'Simulation progress' }).fill('100');
  await page.getByRole('combobox', { name: 'Simulation speed' }).selectOption('20');
  await expect(page.getByTitle(/At 20× the preview takes/)).toBeVisible();
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect(page.getByRole('status', { name: 'Preview zoom', exact: true })).toHaveText('125%');
  await page.getByRole('button', { name: 'Reset preview zoom' }).click();
  await page.getByRole('button', { name: 'Open getting started guide' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.getByRole('spinbutton', { name: 'Drawing width in millimetres' }).evaluate(element => element.closest('.inspector-body')?.scrollTo(0, 0));
  await page.evaluate(async () => { await document.fonts.ready; window.scrollTo(0, 0); });
  await mkdir('../docs/screenshots', { recursive: true });
  await page.screenshot({ path: '../docs/screenshots/phase-6-studio.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('unsupported commands retain the previous drawing', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeVisible();
  const draft = await command(page, 'Draw a butterfly');
  await page.getByRole('textbox', { name: 'Drawing command' }).fill('Draw a cat');
  await page.getByRole('textbox', { name: 'Drawing command' }).press('Enter');
  await expect(page.getByRole('status').filter({ hasText: 'Choose one drawing' })).toBeVisible();
  await expect(page.getByRole('img', { name: /Butterfly drawing path/ })).toHaveAttribute('data-gcode-sha256', draft.gcode_sha256);
});

test('mobile drawing and adjustments have no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeAttached();
  await command(page, 'Create a beautiful mandala');
  await revision(page, () => page.getByRole('spinbutton', { name: 'Drawing width in millimetres' }).fill('100'));
  await expect(page.getByTestId('actual-bounds')).toHaveText('100.00 × 100.00 mm');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.evaluate(async () => { await document.fonts.ready; window.scrollTo(0, 0); });
  await page.screenshot({ path: '../docs/screenshots/phase-6-mobile.png', fullPage: true });
});

test('offline API is visible and reconnect preserves the command', async ({ page }) => {
  await page.route('**/api/**', route => route.abort());
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('The local service is offline');
  await page.getByRole('textbox', { name: 'Drawing command' }).fill('Draw a butterfly');
  await expect(page.getByRole('button', { name: 'Submit drawing command' })).toBeDisabled();
  await page.unroute('**/api/**');
  await page.getByRole('button', { name: 'Reconnect' }).click();
  await expect(page.getByText('Running locally')).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Drawing command' })).toHaveValue('Draw a butterfly');
});

test('saved history reopens after reload and supplied mandala G-code imports centred on the page', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeVisible();
  const original = await command(page, 'Draw a circle diameter 83');
  await page.reload();
  await page.getByRole('button', { name: 'Gallery', exact: true }).click();
  await page.getByRole('radio', { name: 'List layout' }).click();
  await page.getByRole('textbox', { name: 'Search drawing history' }).fill('diameter 83');
  await page.getByRole('button', { name: 'Open Circle revision 1', exact: true }).click();
  await expect(page.getByRole('img', { name: /Circle drawing path/ })).toHaveAttribute('data-gcode-sha256', original.gcode_sha256);
  const imported = await importFile(page, 'G-code', '../SdCard/01 Test GCode/mandala_11x14.gcode');
  expect(imported.import_source.dialect).toBe('linear-mm');
  expect(imported.import_source.original_bounds.width_mm).toBe(252);
  expect(imported.transform.offset_x_mm).toBe(0);
  expect(imported.preview.bounds.min_x_mm).toBe(-126);
  expect(imported.gcode.endsWith('G0 Z5\nG0 X0.000 Y0.000 Z5\n')).toBe(true);
  await expect(page.getByTestId('actual-bounds')).toHaveText('252.00 × 252.00 mm');
  await expect(page.getByRole('button', { name: 'Regenerate drawing' })).toBeDisabled();
});

test('a picture imports as traced, centred line art that plays in the simulation', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeVisible();
  const imported = await importFile(page, 'Image', '../SdCard/01 Test GCode/banana/banana.jpg', 'Low');
  expect(imported.import_source.dialect).toBe('image');
  expect(imported.spec.detail).toBe('sparse');
  expect(imported.transform.offset_x_mm).toBe(0);
  // Fitted inside 85% of the default A4 portrait page.
  expect(imported.preview.bounds.width_mm).toBeLessThanOrEqual(178.5 + .001);
  expect(imported.preview.bounds.height_mm).toBeLessThanOrEqual(252.45 + .001);
  await expect(page.getByRole('status').filter({ hasText: 'Imported banana.jpg' })).toBeVisible();
  await page.getByRole('button', { name: 'Play simulation' }).click();
  await expect(page.getByRole('button', { name: 'Pause simulation' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Execute', exact: true })).toBeEnabled();
});

test('recording an unverified measured profile does not unlock physical preparation', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeVisible();
  const draft = await command(page, 'Draw a circle diameter 50');
  await page.getByRole('button', { name: 'Machine', exact: true }).click();
  await page.getByRole('button', { name: 'Record / edit measurements' }).click();
  const dialog = page.getByRole('dialog', { name: 'Record a machine profile' });
  await dialog.getByRole('textbox', { name: 'Profile name' }).fill('Browser fixture — unverified');
  await dialog.getByRole('textbox', { name: 'Actual board model' }).fill('Test fixture, not observed hardware');
  for (const [label, value] of [
    ['Allowed minimum X mm','-150'], ['Allowed maximum X mm','150'], ['Allowed minimum Y mm','-100'], ['Allowed maximum Y mm','100'],
    ['Minimum rope length mm','100'], ['Maximum rope length mm','600'],
  ]) await dialog.getByRole('spinbutton', { name: label, exact: true }).fill(value);
  await dialog.getByLabel('Measured by', { exact: true }).fill('Browser test fixture');
  await dialog.getByLabel('Measurement and workspace-test notes', { exact: true }).fill('Synthetic test values only. No physical calibration evidence.');
  await dialog.getByLabel('Manual origin procedure before every job', { exact: true }).fill('Synthetic fixture only: real origin procedure remains unverified.');
  await dialog.getByRole('button', { name: 'Save & select unverified profile' }).click();
  await expect(dialog).not.toBeVisible();
  const profiles = await (await page.request.get('/api/profiles')).json();
  const profile = profiles.measured_profiles.find((item: { label: string }) => item.label === 'Browser fixture — unverified');
  expect(profile.verified).toBe(false);
  const token = (await (await page.request.get('/api/session')).json()).write_token;
  const physical = await page.request.post('/api/jobs/prepare', { headers: { 'X-Picasso-Token': token },
    data: { revision_id: draft.revision_id, mode: 'physical', profile_id: profile.id, profile_revision: profile.revision } });
  expect((await physical.json()).code).toBe('PROFILE_UNVERIFIED');
});

test('measurements differing from both references verify only through the canonical firmware ID', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeVisible();
  const draft = await command(page, 'Draw a circle diameter 50');
  await page.getByRole('button', { name: 'Machine', exact: true }).click();
  await page.getByRole('button', { name: 'Record / edit measurements' }).click();
  let dialog = page.getByRole('dialog', { name: 'Record a machine profile' });
  await dialog.getByRole('combobox', { name: 'Edit measured profile' }).selectOption('');
  await dialog.getByRole('textbox', { name: 'Profile name' }).fill('Browser fixture — canonical firmware');
  await dialog.getByRole('textbox', { name: 'Actual board model' }).fill('Test fixture, not observed hardware');
  for (const [label, value] of [
    ['Motor spacing mm', '362.5'], ['Anchor Y above origin mm', '243'],
    ['Allowed minimum X mm','-150'], ['Allowed maximum X mm','150'], ['Allowed minimum Y mm','-100'], ['Allowed maximum Y mm','100'],
    ['Minimum rope length mm','100'], ['Maximum rope length mm','600'],
  ]) await dialog.getByRole('spinbutton', { name: label, exact: true }).fill(value);
  await dialog.getByLabel('Measured by', { exact: true }).fill('Browser test fixture');
  await dialog.getByLabel('Measurement and workspace-test notes', { exact: true }).fill('Synthetic values that differ from both bundled sketches.');
  await dialog.getByLabel('Manual origin procedure before every job', { exact: true }).fill('Synthetic fixture only: real origin procedure remains unverified.');
  await dialog.getByRole('combobox', { name: 'Firmware on the machine' }).selectOption('picasso-canonical');
  await expect(dialog.getByText('Save this profile first')).toBeVisible();
  await dialog.getByRole('button', { name: 'Save & select unverified profile' }).click();
  await expect(dialog).not.toBeVisible();

  await page.getByRole('button', { name: 'Record / edit measurements' }).click();
  dialog = page.getByRole('dialog', { name: 'Record a machine profile' });
  const identity = (await dialog.locator('.firmware-id code').textContent())!;
  expect(identity).toMatch(/^[0-9a-f]{16}$/);
  const profiles = await (await page.request.get('/api/profiles')).json();
  const header = await page.request.get(`/api/profiles/${profiles.active_profile_id}/firmware-config`);
  expect(header.headers()['x-picasso-firmware-config-id']).toBe(identity);
  expect(await header.text()).toContain('#define PICASSO_SEPARATION_MM (362.5f)');
  await dialog.getByRole('textbox', { name: 'Configuration ID shown on the machine' }).fill('0123456789abcdef');
  for (const name of ['I confirmed the flashed firmware uses these calibration values.', 'I tested pen clearance/settling and motor holding with this machine.',
    'I tested the recorded work area and rope-length limits.', 'Mark this profile verified by my recorded checks.']) await dialog.getByRole('checkbox', { name }).check();
  await dialog.getByRole('button', { name: 'Save & select verified profile' }).click();
  await expect(dialog.getByRole('alert')).toContainText('configuration ID does not match');
  await dialog.getByRole('textbox', { name: 'Configuration ID shown on the machine' }).fill(identity);
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.screenshot({ path: '../docs/screenshots/phase-6-firmware-profile.png', fullPage: true });
  await dialog.getByRole('button', { name: 'Save & select verified profile' }).click();
  await expect(dialog).not.toBeVisible();

  const verified = (await (await page.request.get('/api/profiles')).json()).measured_profiles.find((profile: { id: string }) => profile.id === profiles.active_profile_id);
  expect(verified.verified).toBe(true);
  const token = (await (await page.request.get('/api/session')).json()).write_token;
  const job = await page.request.post('/api/jobs/prepare', { headers: { 'X-Picasso-Token': token },
    data: { revision_id: draft.revision_id, mode: 'physical', profile_id: verified.id, profile_revision: verified.revision } });
  expect((await job.json()).gcode_crc32).toMatch(/^[0-9a-f]{8}$/);
});

/** Saves and verifies a profile matching the simulator's compiled configuration; returns its configuration ID. */
async function verifiedSimulatorProfile(page: Page) {
  const token = (await (await page.request.get('/api/session')).json()).write_token;
  const headers = { 'X-Picasso-Token': token };
  // Same values as the synthetic configuration compiled into the simulator.
  const calibration = { label: 'Simulated firmware fixture', base_reference_id: 'reference-350', board: 'Host simulator, not hardware',
    separation_mm: 350, anchor_y_mm: 250, spool_diameter_mm: 35, steps_per_turn: 2048, pen_up_degrees: 85, pen_down_degrees: 70,
    allowed_region: { min_x_mm: -150, max_x_mm: 150, min_y_mm: -100, max_y_mm: 150, margin_mm: 5 }, rope_min_mm: 100, rope_max_mm: 600,
    measured_by: 'Browser test', measurement_notes: 'Synthetic simulator values; no physical evidence.', origin_procedure: 'Simulator keypad script confirms the origin.',
    firmware: 'picasso-canonical' };
  const saved = await (await page.request.post('/api/profiles', { data: { calibration, select_for_preparation: true }, headers })).json();
  const identity = (await (await page.request.get('/api/profiles')).json()).firmware.config_ids[saved.id];
  const verified = await page.request.put(`/api/profiles/${saved.id}`, { headers, data: { expected_revision: saved.revision, select_for_preparation: true,
    calibration: { ...calibration, firmware_config_id: identity, verified: true, firmware_matches_measurements: true, pen_lift_and_holding_tested: true, workspace_tested: true } } });
  expect(verified.ok()).toBe(true);
  return identity as string;
}

test('Execute beside Simulation connects, draws over USB, returns to origin and stops from the preview', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeVisible();
  await verifiedSimulatorProfile(page);
  await page.reload();
  await expect(page.getByText('Running locally')).toBeVisible();
  await command(page, 'Draw a circle diameter 40');

  const execute = page.getByRole('button', { name: 'Execute', exact: true });
  await expect(page.getByRole('button', { name: 'Play simulation' })).toBeVisible();
  await execute.click();
  const sheet = page.getByRole('dialog', { name: 'Draw it on the machine' });
  await expect(sheet.getByText(/Prepared job .* fits the recorded workspace/)).toBeVisible();
  await sheet.getByRole('combobox', { name: 'Serial port' }).selectOption('sim://picasso-firmware');
  await sheet.getByRole('button', { name: 'Connect' }).click();
  await expect(sheet.getByText(/Picasso firmware 0\.6\.1 · configuration/)).toBeVisible({ timeout: 30000 });
  await expect(sheet.locator('.usb-checks li.ok')).toHaveCount(4, { timeout: 10000 });
  const start = sheet.getByRole('button', { name: 'Start drawing' });
  await expect(start).toBeDisabled();
  await sheet.getByRole('checkbox', { name: 'The drawing area is clear and I am watching the machine.' }).check();
  await start.click();
  await expect(sheet.getByLabel('USB run')).toBeVisible();
  await sheet.getByRole('button', { name: 'Close execute' }).click();
  const executing = page.getByRole('button', { name: /Executing · \d+%/ });
  await expect(executing).toBeVisible();
  await expect(page.getByTestId('machine-cursor')).toBeVisible({ timeout: 10000 });
  await expect(page.getByText('Machine drawing')).toBeVisible();
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.screenshot({ path: '../docs/screenshots/phase-6-execute.png', fullPage: true });
  await executing.click();  // reopening the sheet shows the same run
  const run = sheet.getByLabel('USB run');
  await expect(run.getByText('COMPLETED', { exact: true })).toBeVisible({ timeout: 60000 });
  await expect(page.getByRole('button', { name: 'Stop the machine' })).not.toBeVisible();

  // The circle returns pen up to the page centre (0,0), so the next run starts without Go to origin.
  await expect(sheet.locator('.usb-checks li.ok')).toHaveCount(4, { timeout: 30000 });
  await sheet.getByRole('checkbox', { name: 'The drawing area is clear and I am watching the machine.' }).check();
  await start.click();
  await expect(page.getByRole('button', { name: /Executing · \d+%/ })).toBeVisible();
  await sheet.getByRole('button', { name: 'Close execute' }).click();
  await page.getByRole('button', { name: 'Stop the machine' }).click();
  await expect(page.getByRole('button', { name: 'Stop the machine' })).not.toBeVisible({ timeout: 15000 });
  await expect(execute).toBeEnabled();
  await expect.poll(async () => (await (await page.request.get('/api/machine')).json()).recent_runs[0].state, { timeout: 15000 }).toBe('aborted');

  // A stopped run leaves the pen away from (0,0): the next run needs an explicit, confirmed Go to origin.
  await execute.click();
  await expect(sheet.getByText(/Prepared job .* fits the recorded workspace/)).toBeVisible();
  await expect(start).toBeDisabled();
  await sheet.getByRole('checkbox', { name: /straight pen-up route .* to \(0,0\) is clear/ }).check();
  await sheet.getByRole('button', { name: 'Go to origin' }).click();
  await expect(sheet.locator('.usb-checks li.ok')).toHaveCount(4, { timeout: 30000 });
  const token = (await (await page.request.get('/api/session')).json()).write_token;
  await page.request.post('/api/machine/disconnect', { headers: { 'X-Picasso-Token': token } });
});
