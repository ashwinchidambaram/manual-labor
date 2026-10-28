// Generates src/types/generated.ts from the combined JSON Schema at schemas/_all.json.
// Usage: npm run gen-types (from frontend/). Output is deterministic: no timestamps.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { compile } from 'json-schema-to-typescript';

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(here, '../../schemas/_all.json');
const outPath = resolve(here, '../src/types/generated.ts');

const schema = JSON.parse(await readFile(schemaPath, 'utf8'));

// Pydantic puts a "title" on every property and on every $defs entry. The compiler names
// any titled subschema as its own exported type, and it names each $ref copy separately
// (BlockStatus, BlockStatus1, ...). So we drop all titles and let the $defs keys name the
// shared types, which the compiler then declares once. Property *names* (a field literally
// called "title") live under `properties` as keys and are kept.
const KEYED_MAPS = new Set(['properties', 'patternProperties', 'definitions', '$defs']);
function stripTitles(node) {
  if (Array.isArray(node)) return node.map(stripTitles);
  if (node === null || typeof node !== 'object') return node;
  const out = {};
  for (const [key, value] of Object.entries(node)) {
    if (key === 'title' && typeof value === 'string') continue;
    if (KEYED_MAPS.has(key) && value && typeof value === 'object' && !Array.isArray(value)) {
      out[key] = Object.fromEntries(
        Object.entries(value).map(([name, sub]) => [name, stripTitles(sub)]),
      );
    } else {
      out[key] = stripTitles(value);
    }
  }
  return out;
}
const prepared = { ...stripTitles({ ...schema, $defs: undefined }), $defs: stripTitles(schema.$defs ?? {}) };

const ts = await compile(prepared, '_all', {
  bannerComment:
    '/* eslint-disable */\n/** AUTO-GENERATED from schemas/_all.json by scripts/gen-types.mjs — do not edit. Regenerate: npm run gen-types */',
  additionalProperties: false,
  strictIndexSignatures: true,
  style: { singleQuote: true, semi: true },
  // _all.json is a container of $defs with no top-level type: export every $defs entry.
  declareExternallyReferenced: true,
  unreachableDefinitions: true,
  cwd: dirname(schemaPath),
});

await mkdir(dirname(outPath), { recursive: true });
await writeFile(outPath, ts, 'utf8');
console.log(`gen-types: wrote ${outPath}`);
