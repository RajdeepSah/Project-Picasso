import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

test('built app connects, submits honest command feedback and inspects both references', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Your imagination, one line at a time.' })).toBeVisible();
  await page.getByRole('button', { name: 'Draw a circle', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Drawing command' })).toHaveValue('Draw a circle');
  await page.getByRole('textbox', { name: 'Drawing command' }).press('Enter');
  await expect(page.getByRole('status').filter({ hasText: 'No drawing has been generated' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Voice input unavailable/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: /Prepare for drawing/ })).toBeDisabled();
  await page.getByRole('button', { name: 'Machine', exact: true }).click();
  await expect(page.getByText('350 mm', { exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Inspect reference profile' }).selectOption('reference-400');
  await expect(page.getByText('400 mm', { exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/profiles')).json()).active_profile_id).toBeNull();
  await page.getByRole('button', { name: 'Drawing', exact: true }).click();
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect(page.getByRole('status', { name: 'Preview zoom', exact: true })).toHaveText('125%');
  await page.getByRole('button', { name: 'Reset preview zoom' }).click();
  await page.getByRole('button', { name: 'Open getting started guide' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.getByRole('button', { name: /New drawing/ }).click();
  await page.evaluate(async () => { await document.fonts.ready; window.scrollTo(0, 0); });
  await mkdir('../docs/screenshots', { recursive: true });
  await page.screenshot({ path: '../docs/screenshots/phase-2-studio.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('mobile layout remains usable without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByText('Running locally')).toBeAttached();
  await page.getByRole('button', { name: 'Create a beautiful mandala' }).click();
  await expect(page.getByRole('textbox', { name: 'Drawing command' })).toHaveValue('Create a beautiful mandala');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('textbox', { name: 'Drawing command' }).press('Enter');
  await expect(page.getByRole('status').filter({ hasText: 'Phase 3' })).toBeVisible();
  await page.evaluate(async () => { await document.fonts.ready; window.scrollTo(0, 0); });
  await page.screenshot({ path: '../docs/screenshots/phase-2-mobile.png', fullPage: true });
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
