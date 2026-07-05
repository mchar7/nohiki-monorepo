// Regenerates src/api/schema.d.ts from the committed OpenAPI document.
// OPENAPI_SCHEMA_URL may point to a live BFF instead.
import { writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const DEFAULT_SCHEMA_URL = new URL('../../../../docs/api/nohiki.openapi.json', import.meta.url)
  .href;

/**
 * Resolve the OpenAPI schema URL from the environment, defaulting to the
 * committed repository document. Pure: no I/O, safe to import in tests.
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {string}
 */
export function resolveSchemaUrl(env = process.env) {
  const value = env.OPENAPI_SCHEMA_URL?.trim();
  return value ? value : DEFAULT_SCHEMA_URL;
}

const OUTPUT_PATH = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  'src',
  'api',
  'schema.d.ts',
);

async function generate() {
  const { default: openapiTS, astToString, COMMENT_HEADER } = await import('openapi-typescript');
  const url = resolveSchemaUrl();
  console.log(`Generating ${OUTPUT_PATH} from ${url}`);
  const ast = await openapiTS(new URL(url));
  await writeFile(OUTPUT_PATH, `${COMMENT_HEADER}${astToString(ast)}`);
  console.log('Done.');
}

// CLI guard: only generate when this file is executed directly, so importing
// resolveSchemaUrl triggers no network calls or file writes.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  generate().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
