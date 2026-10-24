import { spawnSync } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { compile } from 'json-schema-to-typescript';

const root = fileURLToPath(new URL('../../', import.meta.url));
const python = resolve(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const check = process.argv.includes('--check');
const result = spawnSync(python, ['-m', 'backend.app.export_contracts', ...(check ? ['--check'] : [])], {cwd: root, stdio: 'inherit'});
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);
// Pydantic uses draft 2020-12 tuples; the compiler consumes draft-7 tuple items.
// Preserve each element's numeric type rather than generating [unknown, unknown].
function draft7(value) {
  if (Array.isArray(value)) return value.map(draft7);
  if (value === null || typeof value !== 'object') return value;
  const result = Object.fromEntries(Object.entries(value).map(([key, child]) => [key, draft7(child)]));
  if ('prefixItems' in result) {
    result.items = result.prefixItems;
    result.additionalItems = false;
    delete result.prefixItems;
  }
  return result;
}
const schema = JSON.parse(await readFile(resolve(root, 'frontend/schema/contracts.json'), 'utf8'));
const output = await compile(draft7(schema), 'PicassoContracts', {
  bannerComment: '/* Generated from backend Pydantic models. Run npm run contracts; do not edit. */',
  additionalProperties: false,
});
const target = resolve(root, 'frontend/src/api/contracts.ts');
if (check) {
  if (await readFile(target, 'utf8').catch(() => '') !== output) {
    throw new Error('TypeScript contracts are stale. Run npm run contracts.');
  }
  console.log('TypeScript contracts are current.');
} else {
  await writeFile(target, output);
  console.log('Generated TypeScript contracts.');
}
