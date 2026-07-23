import { readFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { E2E_CONFIG, PRIMARY_USER_STORAGE_STATE_PATH } from './constants.ts';

type StorageState = {
  cookies?: Array<{ name: string; value: string }>;
};

const currentDir: string = path.dirname(fileURLToPath(import.meta.url));
const storageStatePath: string = path.join(currentDir, PRIMARY_USER_STORAGE_STATE_PATH);

const PROFILE_CLEANUP_TIMEOUT_MS = 60_000;
const PROFILE_POLL_INTERVAL_MS = 500;

function delay(milliseconds: number): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, milliseconds);
  return promise;
}

async function deleteProjectedProfiles(cookieHeader: string): Promise<void> {
  const headers = { Cookie: cookieHeader, Origin: E2E_CONFIG.baseUrl };
  const profilesUrl = `${E2E_CONFIG.baseUrl}/api/v1/profiles?page=1&page_size=100`;
  const listResponse = await fetch(profilesUrl, { headers });
  if (!listResponse.ok) {
    throw new Error(`browser profile cleanup failed to list profiles: ${listResponse.status}`);
  }

  const body = (await listResponse.json()) as { items?: Array<{ id?: string }> };
  for (const { id } of body.items ?? []) {
    if (!id) continue;
    const response = await fetch(`${E2E_CONFIG.baseUrl}/api/v1/profiles/${id}`, {
      method: 'DELETE',
      headers,
    });
    if (response.status !== 202 && response.status !== 404) {
      throw new Error(`browser profile cleanup failed with status ${response.status}`);
    }
  }

  const deadline = Date.now() + PROFILE_CLEANUP_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const response = await fetch(profilesUrl, { headers });
    if (!response.ok) {
      throw new Error(`browser profile cleanup poll failed with status ${response.status}`);
    }
    const profiles = (await response.json()) as { items?: unknown[] };
    if ((profiles.items ?? []).length === 0) return;
    await delay(PROFILE_POLL_INTERVAL_MS);
  }
  throw new Error('browser profile cleanup timed out');
}

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

  await deleteProjectedProfiles(cookieHeader);
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
