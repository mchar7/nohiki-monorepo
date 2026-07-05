import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { describe, expect, test } from 'vitest';
import { resolveSchemaUrl } from './generate-api.mjs';

// Importing this module must trigger no network or openapi-typescript spawn:
// generation runs only under the CLI guard. A hanging or throwing import fails here.

const DEFAULT_SUFFIX = '/docs/api/nohiki.openapi.json';

describe('resolveSchemaUrl', () => {
  test('defaults to the committed OpenAPI document when OPENAPI_SCHEMA_URL is unset', () => {
    expect(resolveSchemaUrl({}).endsWith(DEFAULT_SUFFIX)).toBe(true);
  });

  test('honors an OPENAPI_SCHEMA_URL override', () => {
    const override = 'https://api.example.test/openapi.json';
    expect(resolveSchemaUrl({ OPENAPI_SCHEMA_URL: override })).toBe(override);
  });

  test('reads process.env by default (no argument)', () => {
    const prev = process.env.OPENAPI_SCHEMA_URL;
    try {
      process.env.OPENAPI_SCHEMA_URL = 'https://env.example.test/openapi.json';
      expect(resolveSchemaUrl()).toBe('https://env.example.test/openapi.json');
      delete process.env.OPENAPI_SCHEMA_URL;
      expect(resolveSchemaUrl().endsWith(DEFAULT_SUFFIX)).toBe(true);
    } finally {
      if (prev === undefined) delete process.env.OPENAPI_SCHEMA_URL;
      else process.env.OPENAPI_SCHEMA_URL = prev;
    }
  });
});

describe('module import side effects', () => {
  // Under `node --eval` / stdin execution, process.argv[1] is undefined.
  // The old CLI guard called pathToFileURL(process.argv[1]) unconditionally,
  // throwing a TypeError just from importing the module. This spawns a real
  // ESM eval process (argv[1] absent) and proves the import neither throws
  // nor runs generation (which would fetch/spawn openapi-typescript and hang).
  test('imports cleanly when process.argv[1] is absent', () => {
    const scriptPath = resolve(dirname(fileURLToPath(import.meta.url)), 'generate-api.mjs');
    const moduleHref = pathToFileURL(scriptPath).href;
    const source = `try { await import(${JSON.stringify(moduleHref)}); console.log('IMPORT_OK'); } catch (error) { console.error(error); process.exitCode = 1; }`;
    const result = spawnSync(process.execPath, ['--input-type=module', '--eval', source], {
      encoding: 'utf8',
      timeout: 15000,
    });

    expect(result.signal).toBeNull();
    expect(result.status).toBe(0);
    expect(result.stdout).toContain('IMPORT_OK');
  });
});
