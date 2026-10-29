// Generates src/api/types.ts from src/api/openapi.json (exported by
// `uv run python -m manuallabor.api.export_openapi`). Deterministic: no timestamps.
// Usage: npm run gen-api (from frontend/).
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';

const here = dirname(fileURLToPath(import.meta.url));
const specPath = resolve(here, '../src/api/openapi.json');
const outPath = resolve(here, '../src/api/types.ts');

const spec = JSON.parse(await readFile(specPath, 'utf8'));
const ast = await openapiTS(spec);
const banner =
  '/* eslint-disable */\n/** AUTO-GENERATED from src/api/openapi.json by scripts/gen-api.mjs - do not edit. Regenerate: npm run gen-api */\n\n';
await writeFile(outPath, banner + astToString(ast), 'utf8');
console.log(`gen-api: wrote ${outPath}`);
