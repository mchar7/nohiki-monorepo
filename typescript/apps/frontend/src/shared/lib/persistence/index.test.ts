import { beforeEach, describe, expect, vi } from 'vitest';

const fakeIndexedDb = vi.hoisted(() => ({
  legacy: new Map<IDBValidKey, unknown>(),
  stores: new Map<string, Map<IDBValidKey, unknown>>(),
  rejectedClears: new Set<string>(),
}));

function storeId(store: unknown): string {
  if (typeof store !== 'string') {
    throw new TypeError('Expected fake store identifier');
  }
  return store;
}

function getStore(store: unknown): Map<IDBValidKey, unknown> {
  const id = storeId(store);
  let values = fakeIndexedDb.stores.get(id);
  if (!values) {
    values = new Map();
    fakeIndexedDb.stores.set(id, values);
  }
  return values;
}

vi.mock('idb-keyval', () => ({
  createStore: (databaseName: string, storeName: string) => `${databaseName}/${storeName}`,
  clear: (store: unknown) => {
    const id = storeId(store);
    if (fakeIndexedDb.rejectedClears.has(id)) {
      return Promise.reject(new Error(`Failed to clear ${id}`));
    }
    getStore(store).clear();
    return Promise.resolve();
  },
  del: (key: IDBValidKey, store?: unknown) => {
    (store === undefined ? fakeIndexedDb.legacy : getStore(store)).delete(key);
    return Promise.resolve();
  },
  entries: (store: unknown) => Promise.resolve([...getStore(store).entries()]),
  get: (key: IDBValidKey, store: unknown) => Promise.resolve(getStore(store).get(key)),
  keys: (store?: unknown) =>
    Promise.resolve([...(store === undefined ? fakeIndexedDb.legacy : getStore(store)).keys()]),
  set: (key: IDBValidKey, value: unknown, store: unknown) => {
    getStore(store).set(key, value);
    return Promise.resolve();
  },
}));

import {
  clearUserScopedPersistence,
  datasetPersistence,
  schemaPersistence,
  templatePersistence,
} from './index.ts';

const TEMPLATE_STORE = 'nohiki-local-templates-v1/templates';
const SCHEMA_STORE = 'nohiki-local-schemas-v1/schemas';
const DATASET_STORE = 'nohiki-local-datasets-v1/datasets';

beforeEach(() => {
  localStorage.clear();
  fakeIndexedDb.legacy.clear();
  fakeIndexedDb.stores.clear();
  fakeIndexedDb.rejectedClears.clear();
});

describe('clearUserScopedPersistence', () => {
  test('removes user documents and cached preview data from every persistence store', async () => {
    fakeIndexedDb.stores.set(TEMPLATE_STORE, new Map([['template-1', { name: 'Resume' }]]));
    fakeIndexedDb.stores.set(SCHEMA_STORE, new Map([['schema-1', { title: 'Resume fields' }]]));
    fakeIndexedDb.stores.set(
      DATASET_STORE,
      new Map([['dataset-1', { email: 'user@example.com' }]]),
    );
    fakeIndexedDb.legacy.set('template:legacy', { name: 'Legacy template' });
    fakeIndexedDb.legacy.set('dataset:legacy', { email: 'user@example.com' });
    fakeIndexedDb.legacy.set('device-preference', 'compact');
    localStorage.setItem(
      'nohiki-document-builder-store',
      JSON.stringify({ datasets: [{ cachedHtmlData: '<p>private preview</p>' }] }),
    );
    localStorage.setItem('template:fallback', '{"name":"Resume"}');
    localStorage.setItem('dataset:fallback', '{"email":"user@example.com"}');

    await clearUserScopedPersistence();

    expect(fakeIndexedDb.stores.get(TEMPLATE_STORE)).toEqual(new Map());
    expect(fakeIndexedDb.stores.get(SCHEMA_STORE)).toEqual(new Map());
    expect(fakeIndexedDb.stores.get(DATASET_STORE)).toEqual(new Map());
    expect(fakeIndexedDb.legacy).toEqual(new Map([['device-preference', 'compact']]));
    expect(localStorage.getItem('nohiki-document-builder-store')).toBeNull();
    expect(localStorage.getItem('template:fallback')).toBeNull();
    expect(localStorage.getItem('dataset:fallback')).toBeNull();
  });

  test('removes every account-derived key while preserving device preferences', async () => {
    const removed = {
      'attachment-category:resume.pdf': 'resume',
      nohiki_dashboard_last_visit: '2026-07-01T00:00:00.000Z',
      'nohiki:profile:selected': 'profile-private',
      'template:private': '{"name":"Resume"}',
      'dataset:private': '{"email":"user@example.com"}',
    } as const;
    const preserved = {
      'nohiki:theme': 'dark',
      i18nextLng: 'de',
      nohiki_remembered_email: 'user@example.com',
      'nohiki:sidebar:collapsed': 'true',
    } as const;
    for (const [key, value] of Object.entries({ ...removed, ...preserved })) {
      localStorage.setItem(key, value);
    }
    localStorage.setItem(
      'nohiki:auth:state',
      JSON.stringify({
        state: { selectedProfileId: 'profile-private', theme: 'dark' },
        version: 0,
      }),
    );

    await clearUserScopedPersistence();

    for (const key of Object.keys(removed)) expect(localStorage.getItem(key)).toBeNull();
    expect(JSON.parse(localStorage.getItem('nohiki:auth:state') ?? '{}')).toEqual({
      state: { selectedProfileId: null, theme: 'dark' },
      version: 0,
    });
    expect(
      Object.fromEntries(Object.keys(preserved).map((key) => [key, localStorage.getItem(key)])),
    ).toEqual(preserved);
  });

  test('preserves theme, language, remembered email, and device preferences', async () => {
    const preserved = {
      'nohiki:theme': 'dark',
      i18nextLng: 'de',
      nohiki_remembered_email: 'user@example.com',
      'nohiki:sidebar:collapsed': 'true',
    } as const;
    for (const [key, value] of Object.entries(preserved)) {
      localStorage.setItem(key, value);
    }
    localStorage.setItem('dataset:private', '{"email":"user@example.com"}');

    await clearUserScopedPersistence();

    expect(
      Object.fromEntries(Object.keys(preserved).map((key) => [key, localStorage.getItem(key)])),
    ).toEqual(preserved);
    expect(localStorage.getItem('dataset:private')).toBeNull();
  });
  test('quarantines stale records when one store clear fails and recovers on retry', async () => {
    const staleTemplate = { id: 'template-old-user', name: 'Private resume' };
    fakeIndexedDb.stores.set(TEMPLATE_STORE, new Map([[staleTemplate.id, staleTemplate]]));
    fakeIndexedDb.stores.set(SCHEMA_STORE, new Map([['schema-old-user', { private: true }]]));
    fakeIndexedDb.stores.set(DATASET_STORE, new Map([['dataset-old-user', { private: true }]]));
    fakeIndexedDb.rejectedClears.add(TEMPLATE_STORE);

    await expect(clearUserScopedPersistence()).rejects.toThrow(TEMPLATE_STORE);

    // The failed store still physically contains the previous account's data, but quarantine
    // prevents any persistence API from hydrating it for the next account.
    expect(fakeIndexedDb.stores.get(TEMPLATE_STORE)).toEqual(
      new Map([[staleTemplate.id, staleTemplate]]),
    );
    expect(fakeIndexedDb.stores.get(SCHEMA_STORE)).toEqual(new Map());
    expect(fakeIndexedDb.stores.get(DATASET_STORE)).toEqual(new Map());
    await expect(templatePersistence.get(staleTemplate.id)).resolves.toBeUndefined();
    await expect(templatePersistence.getAll()).resolves.toEqual([]);
    await expect(templatePersistence.getAllKeys()).resolves.toEqual([]);
    await expect(schemaPersistence.getAll()).resolves.toEqual([]);
    await expect(datasetPersistence.getAll()).resolves.toEqual([]);

    fakeIndexedDb.rejectedClears.delete(TEMPLATE_STORE);
    await expect(clearUserScopedPersistence()).resolves.toBeUndefined();
    expect(fakeIndexedDb.stores.get(TEMPLATE_STORE)).toEqual(new Map());

    const nextUserTemplate = { id: 'template-new-user', name: 'New resume' };
    await templatePersistence.set(nextUserTemplate as never);
    await expect(templatePersistence.get(nextUserTemplate.id)).resolves.toEqual(nextUserTemplate);
    await expect(templatePersistence.getAllKeys()).resolves.toEqual([nextUserTemplate.id]);
  });
});
