import { afterEach, describe, expect, vi } from 'vitest';
import { DEFAULT_SCHEMA, useSchemaStore } from './schemaStore.ts';

vi.mock('@/shared/lib/persistence', () => ({
  schemaPersistence: {
    getAll: vi.fn().mockResolvedValue([]),
    set: vi.fn().mockResolvedValue(undefined),
    delete: vi.fn().mockResolvedValue(undefined),
    clear: vi.fn().mockResolvedValue(undefined),
  },
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe('schemaStore - DEFAULT_SCHEMA', () => {
  test('has correct structure', () => {
    expect(DEFAULT_SCHEMA.$schema).toBe('http://json-schema.org/draft-07/schema#');
    expect(DEFAULT_SCHEMA.type).toBe('object');
    expect(DEFAULT_SCHEMA.properties).toEqual({});
    expect(DEFAULT_SCHEMA.required).toEqual([]);
  });
});

describe('schemaStore - initial state', () => {
  test('starts with empty schemas', () => {
    expect(useSchemaStore.getState().schemas).toEqual([]);
  });

  test('starts with empty schemaIndex', () => {
    expect(useSchemaStore.getState().schemaIndex.size).toBe(0);
  });

  test('starts with null selectedSchemaId', () => {
    expect(useSchemaStore.getState().selectedSchemaId).toBeNull();
  });

  test('starts not initialized', () => {
    expect(useSchemaStore.getState().isInitialized).toBe(false);
  });
});

describe('schemaStore - initialize', () => {
  test('sets initialized to true after loading', async () => {
    await useSchemaStore.getState().initialize();
    expect(useSchemaStore.getState().isInitialized).toBe(true);
    expect(useSchemaStore.getState().isLoading).toBe(false);
  });

  test('does not re-initialize if already initialized', async () => {
    await useSchemaStore.getState().initialize();
    await useSchemaStore.getState().initialize();
    expect(useSchemaStore.getState().isInitialized).toBe(true);
  });
});

describe('schemaStore - create', () => {
  test('creates a new schema', async () => {
    const input = { metadata: { name: 'Test Schema' }, jsonSchema: DEFAULT_SCHEMA };
    const result = await useSchemaStore.getState().create(input);
    expect(result.metadata.name).toBe('Test Schema');
    expect(result.jsonSchema).toEqual(DEFAULT_SCHEMA);
    expect(result.id).toBeDefined();
    expect(result.version).toBe(1);
  });

  test('adds schema to store and index', async () => {
    const input = { metadata: { name: 'Test Schema' }, jsonSchema: DEFAULT_SCHEMA };
    const result = await useSchemaStore.getState().create(input);
    expect(useSchemaStore.getState().schemas).toContainEqual(result);
    expect(useSchemaStore.getState().schemaIndex.get(result.id)).toEqual(result);
  });
});

describe('schemaStore - update', () => {
  test('updates existing schema', async () => {
    const created = await useSchemaStore.getState().create({
      metadata: { name: 'Original' },
      jsonSchema: DEFAULT_SCHEMA,
    });
    const updated = await useSchemaStore.getState().update(created.id, {
      metadata: { name: 'Updated' },
    });
    expect(updated?.metadata.name).toBe('Updated');
    expect(updated?.version).toBe(2);
  });

  test('returns null for non-existent schema', async () => {
    const result = await useSchemaStore.getState().update('non-existent', {
      metadata: { name: 'Test' },
    });
    expect(result).toBeNull();
  });
});

describe('schemaStore - delete', () => {
  test('removes schema from store', async () => {
    const created = await useSchemaStore.getState().create({
      metadata: { name: 'To Delete' },
      jsonSchema: DEFAULT_SCHEMA,
    });
    await useSchemaStore.getState().delete(created.id);
    expect(useSchemaStore.getState().schemas).not.toContainEqual(created);
    expect(useSchemaStore.getState().schemaIndex.has(created.id)).toBe(false);
  });

  test('clears selectedSchemaId if deleting selected', async () => {
    const created = await useSchemaStore.getState().create({
      metadata: { name: 'Selected' },
      jsonSchema: DEFAULT_SCHEMA,
    });
    useSchemaStore.getState().select(created.id);
    await useSchemaStore.getState().delete(created.id);
    expect(useSchemaStore.getState().selectedSchemaId).toBeNull();
  });
});

describe('schemaStore - clone', () => {
  test('clones existing schema with new name', async () => {
    const original = await useSchemaStore.getState().create({
      metadata: { name: 'Original' },
      jsonSchema: { ...DEFAULT_SCHEMA, title: 'Test' },
    });
    const cloned = await useSchemaStore.getState().clone(original.id, 'Cloned Schema');
    expect(cloned?.id).not.toBe(original.id);
    expect(cloned?.metadata.name).toBe('Cloned Schema');
    expect(cloned?.jsonSchema).toEqual(original.jsonSchema);
  });

  test('uses default name if not provided', async () => {
    const original = await useSchemaStore.getState().create({
      metadata: { name: 'Original' },
      jsonSchema: DEFAULT_SCHEMA,
    });
    const cloned = await useSchemaStore.getState().clone(original.id);
    expect(cloned?.metadata.name).toBe('Original (Copy)');
  });

  test('returns null for non-existent schema', async () => {
    const result = await useSchemaStore.getState().clone('non-existent');
    expect(result).toBeNull();
  });
});

describe('schemaStore - select and getById', () => {
  test('sets selected schema ID', async () => {
    const created = await useSchemaStore.getState().create({
      metadata: { name: 'Test' },
      jsonSchema: DEFAULT_SCHEMA,
    });
    useSchemaStore.getState().select(created.id);
    expect(useSchemaStore.getState().selectedSchemaId).toBe(created.id);
  });

  test('can clear selection', () => {
    useSchemaStore.getState().select('some-id');
    useSchemaStore.getState().select(null);
    expect(useSchemaStore.getState().selectedSchemaId).toBeNull();
  });

  test('returns schema by ID', async () => {
    const created = await useSchemaStore.getState().create({
      metadata: { name: 'Test' },
      jsonSchema: DEFAULT_SCHEMA,
    });
    expect(useSchemaStore.getState().getById(created.id)).toEqual(created);
  });

  test('returns undefined for non-existent ID', () => {
    expect(useSchemaStore.getState().getById('non-existent')).toBeUndefined();
  });
});

describe('schemaStore - import and clearAll', () => {
  test('imports multiple schemas', async () => {
    const inputs = [
      { metadata: { name: 'Schema 1' }, jsonSchema: DEFAULT_SCHEMA },
      { metadata: { name: 'Schema 2' }, jsonSchema: DEFAULT_SCHEMA },
    ];
    const results = await useSchemaStore.getState().importSchemas(inputs);
    expect(results).toHaveLength(2);
    expect(useSchemaStore.getState().schemas).toHaveLength(2);
  });

  test('clears all schemas', async () => {
    await useSchemaStore.getState().create({
      metadata: { name: 'Schema 1' },
      jsonSchema: DEFAULT_SCHEMA,
    });
    await useSchemaStore.getState().create({
      metadata: { name: 'Schema 2' },
      jsonSchema: DEFAULT_SCHEMA,
    });
    await useSchemaStore.getState().clearAll();
    expect(useSchemaStore.getState().schemas).toHaveLength(0);
    expect(useSchemaStore.getState().schemaIndex.size).toBe(0);
    expect(useSchemaStore.getState().selectedSchemaId).toBeNull();
  });
});
