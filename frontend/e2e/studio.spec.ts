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

async function revision(page: Page, action: () => Promise<unknown>) {
  const response = page.waitForResponse(response => response.url().endsWith('/revisions') && response.request().method() === 'POST');
  await action();
  const result = await response;
  expect(result.status()).toBe(200);
  const draft = await result.json();
  await expect(page.getByRole('status').filter({ hasText: `revision ${draft.revision}.` })).toBeVisible();
  return draft;
}

test('offline circle to resized mandala, regeneration, exact draft downloads and profile inspection', async ({ page }) => {
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
  await page.getByRole('checkbox', { name: 'Keep seed when regenerating' }).check();
  const retained = await revision(page, () => page.getByRole('button', { name: 'Regenerate drawing' }).click());
  expect(retained.gcode_sha256).toBe(regenerated.gcode_sha256);
  expect(retained.revision_id).not.toBe(regenerated.revision_id);
  await expect(page.getByRole('button', { name: /Voice input unavailable/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: /Prepare for drawing/ })).toBeDisabled();
  const downloadJson = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Draft JSON' }).click();
  const jsonFile = await downloadJson;
  expect(jsonFile.suggestedFilename()).toContain('UNVERIFIED.json');
  const saved = JSON.parse(await readFile((await jsonFile.path())!, 'utf8'));
  expect(saved.execution_ready).toBe(false);
  expect(saved.gcode_sha256).toBe(retained.gcode_sha256);
  await expect(page.getByRole('button', { name: 'G-code', exact: true })).toBeEnabled();
  const downloadCode = page.waitForEvent('download');
  await page.getByRole('button', { name: 'G-code', exact: true }).click();
  const codeFile = await downloadCode;
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
  await page.screenshot({ path: '../docs/screenshots/phase-3-studio.png', fullPage: true });
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
  await page.screenshot({ path: '../docs/screenshots/phase-3-mobile.png', fullPage: true });
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
