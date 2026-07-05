import { afterEach, describe, expect, vi } from 'vitest';
import { useDatasetStore } from './datasetStore.ts';

vi.mock('@/shared/lib/persistence', () => ({
  datasetPersistence: {
    getAll: vi.fn().mockResolvedValue([]),
    set: vi.fn().mockResolvedValue(undefined),
    delete: vi.fn().mockResolvedValue(undefined),
    clear: vi.fn().mockResolvedValue(undefined),
  },
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe('datasetStore - initial state', () => {
  test('starts with empty datasets', () => {
    expect(useDatasetStore.getState().datasets).toEqual([]);
  });

  test('starts with empty datasetsById map', () => {
    expect(useDatasetStore.getState().datasetsById.size).toBe(0);
  });

  test('starts with null activeDatasetId', () => {
    expect(useDatasetStore.getState().activeDatasetId).toBeNull();
  });

  test('starts not loading', () => {
    expect(useDatasetStore.getState().isLoading).toBe(false);
  });

  test('starts not initialized', () => {
    expect(useDatasetStore.getState().isInitialized).toBe(false);
  });

  test('starts with no error', () => {
    expect(useDatasetStore.getState().error).toBeNull();
  });
});

describe('datasetStore - initialize', () => {
  test('sets initialized to true after loading', async () => {
    await useDatasetStore.getState().initialize();
    expect(useDatasetStore.getState().isInitialized).toBe(true);
    expect(useDatasetStore.getState().isLoading).toBe(false);
  });

  test('does not re-initialize if already initialized', async () => {
    await useDatasetStore.getState().initialize();
    await useDatasetStore.getState().initialize();
    expect(useDatasetStore.getState().isInitialized).toBe(true);
  });
});

describe('datasetStore - create', () => {
  test('creates a new dataset', async () => {
    const input = {
      metadata: { name: 'Test Dataset' },
      templateId: 'template-1',
      data: { field: 'value' },
    };
    const result = await useDatasetStore.getState().create(input);
    expect(result.metadata.name).toBe('Test Dataset');
    expect(result.templateId).toBe('template-1');
    expect(result.data).toEqual({ field: 'value' });
    expect(result.id).toBeDefined();
  });

  test('adds dataset to store', async () => {
    const input = { metadata: { name: 'Test Dataset' }, templateId: 'template-1' };
    const result = await useDatasetStore.getState().create(input);
    expect(useDatasetStore.getState().datasets).toContainEqual(result);
    expect(useDatasetStore.getState().datasetsById.get(result.id)).toEqual(result);
  });

  test('creates dataset with empty data if not provided', async () => {
    const input = { metadata: { name: 'Test Dataset' }, templateId: 'template-1' };
    const result = await useDatasetStore.getState().create(input);
    expect(result.data).toEqual({});
  });
});

describe('datasetStore - update', () => {
  test('updates existing dataset', async () => {
    const created = await useDatasetStore.getState().create({
      metadata: { name: 'Original' },
      templateId: 'template-1',
      data: { field: 'original' },
    });
    const updated = await useDatasetStore.getState().update(created.id, {
      metadata: { name: 'Updated' },
      data: { field: 'updated' },
    });
    expect(updated?.metadata.name).toBe('Updated');
    expect(updated?.data).toEqual({ field: 'updated' });
  });

  test('returns null for non-existent dataset', async () => {
    const result = await useDatasetStore.getState().update('non-existent', {
      metadata: { name: 'Test' },
    });
    expect(result).toBeNull();
  });

  test('clears cached HTML when data changes', async () => {
    const created = await useDatasetStore.getState().create({
      metadata: { name: 'Test' },
      templateId: 'template-1',
      data: {},
    });
    await useDatasetStore.getState().setCachedHtml(created.id, '<html>cached</html>');
    const updated = await useDatasetStore.getState().update(created.id, {
      data: { newField: 'value' },
    });
    expect(updated?.cachedHtml).toBeUndefined();
  });
});

describe('datasetStore - delete', () => {
  test('removes dataset from store', async () => {
    const created = await useDatasetStore.getState().create({
      metadata: { name: 'To Delete' },
      templateId: 'template-1',
    });
    await useDatasetStore.getState().delete(created.id);
    expect(useDatasetStore.getState().datasets).not.toContainEqual(created);
    expect(useDatasetStore.getState().datasetsById.has(created.id)).toBe(false);
  });

  test('clears activeDatasetId if deleting active dataset', async () => {
    const created = await useDatasetStore.getState().create({
      metadata: { name: 'Active' },
      templateId: 'template-1',
    });
    useDatasetStore.getState().setActive(created.id);
    await useDatasetStore.getState().delete(created.id);
    expect(useDatasetStore.getState().activeDatasetId).toBeNull();
  });
});

describe('datasetStore - clone', () => {
  test('clones existing dataset with new name', async () => {
    const original = await useDatasetStore.getState().create({
      metadata: { name: 'Original' },
      templateId: 'template-1',
      data: { field: 'value' },
    });
    const cloned = await useDatasetStore.getState().clone(original.id, 'Cloned Dataset');
    expect(cloned?.id).not.toBe(original.id);
    expect(cloned?.metadata.name).toBe('Cloned Dataset');
    expect(cloned?.data).toEqual(original.data);
  });

  test('uses default name if not provided', async () => {
    const original = await useDatasetStore.getState().create({
      metadata: { name: 'Original' },
      templateId: 'template-1',
    });
    const cloned = await useDatasetStore.getState().clone(original.id);
    expect(cloned?.metadata.name).toBe('Original (Copy)');
  });

  test('returns null for non-existent dataset', async () => {
    const result = await useDatasetStore.getState().clone('non-existent');
    expect(result).toBeNull();
  });
});

describe('datasetStore - setActive and getById', () => {
  test('sets active dataset ID', async () => {
    const created = await useDatasetStore.getState().create({
      metadata: { name: 'Test' },
      templateId: 'template-1',
    });
    useDatasetStore.getState().setActive(created.id);
    expect(useDatasetStore.getState().activeDatasetId).toBe(created.id);
  });

  test('can clear active dataset', () => {
    useDatasetStore.getState().setActive('some-id');
    useDatasetStore.getState().setActive(null);
    expect(useDatasetStore.getState().activeDatasetId).toBeNull();
  });

  test('returns dataset by ID', async () => {
    const created = await useDatasetStore.getState().create({
      metadata: { name: 'Test' },
      templateId: 'template-1',
    });
    expect(useDatasetStore.getState().getById(created.id)).toEqual(created);
  });

  test('returns undefined for non-existent ID', () => {
    expect(useDatasetStore.getState().getById('non-existent')).toBeUndefined();
  });
});

describe('datasetStore - getByTemplateId', () => {
  test('returns datasets matching template ID', async () => {
    await useDatasetStore.getState().create({
      metadata: { name: 'Template 1 - Dataset 1' },
      templateId: 'template-1',
    });
    await useDatasetStore.getState().create({
      metadata: { name: 'Template 1 - Dataset 2' },
      templateId: 'template-1',
    });
    await useDatasetStore.getState().create({
      metadata: { name: 'Template 2 - Dataset 1' },
      templateId: 'template-2',
    });
    const results = useDatasetStore.getState().getByTemplateId('template-1');
    expect(results).toHaveLength(2);
    expect(results.every((d) => d.templateId === 'template-1')).toBe(true);
  });
});

describe('datasetStore - caching and import', () => {
  test('sets cached HTML for dataset', async () => {
    const created = await useDatasetStore.getState().create({
      metadata: { name: 'Test' },
      templateId: 'template-1',
    });
    await useDatasetStore.getState().setCachedHtml(created.id, '<html>cached</html>');
    const updated = useDatasetStore.getState().getById(created.id);
    expect(updated?.cachedHtml).toBe('<html>cached</html>');
    expect(updated?.htmlCachedAt).toBeDefined();
  });

  test('does nothing for non-existent dataset', async () => {
    await useDatasetStore.getState().setCachedHtml('non-existent', '<html>test</html>');
    expect(useDatasetStore.getState().getById('non-existent')).toBeUndefined();
  });

  test('clears cached HTML for dataset', async () => {
    const created = await useDatasetStore.getState().create({
      metadata: { name: 'Test' },
      templateId: 'template-1',
    });
    await useDatasetStore.getState().setCachedHtml(created.id, '<html>cached</html>');
    await useDatasetStore.getState().clearCachedHtml(created.id);
    const updated = useDatasetStore.getState().getById(created.id);
    expect(updated?.cachedHtml).toBeUndefined();
    expect(updated?.htmlCachedAt).toBeUndefined();
  });

  test('imports multiple datasets', async () => {
    const inputs = [
      { metadata: { name: 'Dataset 1' }, templateId: 'template-1' },
      { metadata: { name: 'Dataset 2' }, templateId: 'template-1' },
    ];
    const results = await useDatasetStore.getState().importDatasets(inputs);
    expect(results).toHaveLength(2);
    expect(useDatasetStore.getState().datasets).toHaveLength(2);
  });
});

describe('datasetStore - clearAll', () => {
  test('clears all datasets', async () => {
    await useDatasetStore.getState().create({
      metadata: { name: 'Dataset 1' },
      templateId: 'template-1',
    });
    await useDatasetStore.getState().create({
      metadata: { name: 'Dataset 2' },
      templateId: 'template-1',
    });
    await useDatasetStore.getState().clearAll();
    expect(useDatasetStore.getState().datasets).toHaveLength(0);
    expect(useDatasetStore.getState().datasetsById.size).toBe(0);
    expect(useDatasetStore.getState().activeDatasetId).toBeNull();
  });
});
