import { readFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { E2E_CONFIG, PRIMARY_USER_STORAGE_STATE_PATH } from './constants.ts';

type StorageState = {
  cookies?: Array<{ name: string; value: string }>;
};

const currentDir: string = path.dirname(fileURLToPath(import.meta.url));
const storageStatePath: string = path.join(currentDir, PRIMARY_USER_STORAGE_STATE_PATH);

export default async function globalTeardown(): Promise<void> {
  let state: StorageState;
  try {
    state = JSON.parse(await readFile(storageStatePath, 'utf8')) as StorageState;
  } catch (error) {
    throw new Error('browser identity cleanup requires authenticated storage state', {
      cause: error,
    });
  }

  const cookieHeader = (state.cookies ?? [])
    .map(({ name, value }) => `${name}=${value}`)
    .join('; ');
  if (!cookieHeader) {
    throw new Error('browser identity cleanup found no authenticated cookies');
  }

  try {
    const response = await fetch(`${E2E_CONFIG.baseUrl}/api/v1/account`, {
      method: 'DELETE',
      headers: { Cookie: cookieHeader, Origin: E2E_CONFIG.baseUrl },
    });
    if (response.status !== 204 && response.status !== 404) {
      throw new Error(`browser identity cleanup failed with status ${response.status}`);
    }
  } finally {
    await rm(storageStatePath, { force: true });
  }
}
