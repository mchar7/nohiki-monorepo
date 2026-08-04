/**
 * IndexedDB persistence layer using idb-keyval.
 * Provides type-safe storage for local-first entities.
 */

import { clear, createStore, del, entries, get, keys, set, type UseStore } from 'idb-keyval';
import type { LocalDataset } from '@/shared/model/dataset.types.ts';
import type { LocalSchema } from '@/shared/model/schema.types.ts';
import type { LocalTemplate } from '@/shared/model/template.types.ts';

const STORE_NAME = 'nohiki-local';
const DB_VERSION = 1;

// Create separate stores for each entity type
const templateStore: UseStore = createStore(`${STORE_NAME}-templates-v${DB_VERSION}`, 'templates');
const schemaStore: UseStore = createStore(`${STORE_NAME}-schemas-v${DB_VERSION}`, 'schemas');
const datasetStore: UseStore = createStore(`${STORE_NAME}-datasets-v${DB_VERSION}`, 'datasets');
const USER_PERSISTENCE_QUARANTINE_KEY = 'nohiki:user-persistence-quarantined';
let persistenceQuarantined = false;

function isPersistenceQuarantined(): boolean {
  if (persistenceQuarantined) return true;
  try {
    return globalThis.localStorage.getItem(USER_PERSISTENCE_QUARANTINE_KEY) === '1';
  } catch {
    return false;
  }
}

function assertPersistenceAvailable(): void {
  if (isPersistenceQuarantined()) {
    throw new Error('User persistence is quarantined until cleanup succeeds');
  }
}

// Template persistence
export const templatePersistence = {
  async get(id: string): Promise<LocalTemplate | undefined> {
    if (isPersistenceQuarantined()) return undefined;
    return get<LocalTemplate>(id, templateStore);
  },

  async set(template: LocalTemplate): Promise<void> {
    assertPersistenceAvailable();
    await set(template.id, template, templateStore);
  },

  async delete(id: string): Promise<void> {
    await del(id, templateStore);
  },

  async getAll(): Promise<LocalTemplate[]> {
    if (isPersistenceQuarantined()) return [];
    const allEntries = await entries<string, LocalTemplate>(templateStore);
    return allEntries.map(([, value]) => value);
  },

  async getAllKeys(): Promise<string[]> {
    if (isPersistenceQuarantined()) return [];
    return keys<string>(templateStore);
  },

  async clear(): Promise<void> {
    await clear(templateStore);
  },

  async bulkSet(templates: LocalTemplate[]): Promise<void> {
    assertPersistenceAvailable();
    await Promise.all(templates.map((template) => set(template.id, template, templateStore)));
  },
};

// Schema persistence
export const schemaPersistence = {
  async get(id: string): Promise<LocalSchema | undefined> {
    if (isPersistenceQuarantined()) return undefined;
    return get<LocalSchema>(id, schemaStore);
  },

  async set(schema: LocalSchema): Promise<void> {
    assertPersistenceAvailable();
    await set(schema.id, schema, schemaStore);
  },

  async delete(id: string): Promise<void> {
    await del(id, schemaStore);
  },

  async getAll(): Promise<LocalSchema[]> {
    if (isPersistenceQuarantined()) return [];
    const allEntries = await entries<string, LocalSchema>(schemaStore);
    return allEntries.map(([, value]) => value);
  },

  async getAllKeys(): Promise<string[]> {
    if (isPersistenceQuarantined()) return [];
    return keys<string>(schemaStore);
  },

  async clear(): Promise<void> {
    await clear(schemaStore);
  },

  async bulkSet(schemas: LocalSchema[]): Promise<void> {
    assertPersistenceAvailable();
    await Promise.all(schemas.map((schema) => set(schema.id, schema, schemaStore)));
  },
};

// Dataset persistence
export const datasetPersistence = {
  async get(id: string): Promise<LocalDataset | undefined> {
    if (isPersistenceQuarantined()) return undefined;
    return get<LocalDataset>(id, datasetStore);
  },

  async set(dataset: LocalDataset): Promise<void> {
    assertPersistenceAvailable();
    await set(dataset.id, dataset, datasetStore);
  },

  async delete(id: string): Promise<void> {
    await del(id, datasetStore);
  },

  async getAll(): Promise<LocalDataset[]> {
    if (isPersistenceQuarantined()) return [];
    const allEntries = await entries<string, LocalDataset>(datasetStore);
    return allEntries.map(([, value]) => value);
  },

  async getAllKeys(): Promise<string[]> {
    if (isPersistenceQuarantined()) return [];
    return keys<string>(datasetStore);
  },

  async clear(): Promise<void> {
    await clear(datasetStore);
  },

  async bulkSet(datasets: LocalDataset[]): Promise<void> {
    assertPersistenceAvailable();
    await Promise.all(datasets.map((dataset) => set(dataset.id, dataset, datasetStore)));
  },
};

const USER_SCOPED_LOCAL_STORAGE_KEYS: Record<string, true> = {
  'nohiki-document-builder-store': true,
  nohiki_dashboard_last_visit: true,
  'nohiki:profile:selected': true,
};
const USER_SCOPED_STORAGE_PREFIXES: readonly string[] = [
  'template:',
  'dataset:',
  'attachment-category:',
];

function clearSelectedProfileFromAuthState(): void {
  const key = 'nohiki:auth:state';
  const serialized = globalThis.localStorage.getItem(key);
  if (serialized === null) return;

  const persisted = JSON.parse(serialized) as { state?: Record<string, unknown> };
  if (persisted.state === undefined) return;
  persisted.state.selectedProfileId = null;
  globalThis.localStorage.setItem(key, JSON.stringify(persisted));
}

/** Clears persisted document/template data while preserving theme, language, and device preferences. */
export async function clearUserScopedPersistence(): Promise<void> {
  persistenceQuarantined = true;
  try {
    globalThis.localStorage.setItem(USER_PERSISTENCE_QUARANTINE_KEY, '1');
  } catch {
    // The in-memory quarantine still prevents hydration during this page lifetime.
  }

  const cleanupResults = await Promise.allSettled([
    templatePersistence.clear(),
    schemaPersistence.clear(),
    datasetPersistence.clear(),
  ]);
  const failures: unknown[] = cleanupResults.flatMap((result) =>
    result.status === 'rejected' ? [result.reason] : [],
  );

  try {
    for (const key of Object.keys(USER_SCOPED_LOCAL_STORAGE_KEYS)) {
      globalThis.localStorage.removeItem(key);
    }
    for (const key of Object.keys(globalThis.localStorage)) {
      if (USER_SCOPED_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))) {
        globalThis.localStorage.removeItem(key);
      }
    }
    clearSelectedProfileFromAuthState();
  } catch (error) {
    failures.push(error);
  }

  if (failures.length > 0) {
    const details = failures
      .map((failure) => (failure instanceof Error ? failure.message : String(failure)))
      .join('; ');
    throw new AggregateError(
      failures,
      `Failed to clear user-scoped persistence; data remains quarantined: ${details}`,
    );
  }

  try {
    globalThis.localStorage.removeItem(USER_PERSISTENCE_QUARANTINE_KEY);
  } catch {
    // The marker is conservative: leaving it behind fails closed until a later retry.
    throw new Error('User persistence was cleared but its quarantine marker could not be removed');
  }
  persistenceQuarantined = false;
}
