import { afterEach, describe, expect, vi } from 'vitest';
import { useTemplateStore } from './templateStore.ts';

vi.mock('@/shared/lib/persistence', () => ({
  templatePersistence: {
    getAll: vi.fn().mockResolvedValue([]),
    set: vi.fn().mockResolvedValue(undefined),
    delete: vi.fn().mockResolvedValue(undefined),
    clear: vi.fn().mockResolvedValue(undefined),
  },
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe('templateStore - initial state', () => {
  test('starts with empty templates', () => {
    expect(useTemplateStore.getState().templates).toEqual([]);
  });

  test('starts with empty templateIndex', () => {
    expect(useTemplateStore.getState().templateIndex.size).toBe(0);
  });

  test('starts with null selectedTemplateId', () => {
    expect(useTemplateStore.getState().selectedTemplateId).toBeNull();
  });

  test('starts not initialized', () => {
    expect(useTemplateStore.getState().isInitialized).toBe(false);
  });
});

describe('templateStore - initialize', () => {
  test('sets initialized to true after loading', async () => {
    await useTemplateStore.getState().initialize();
    expect(useTemplateStore.getState().isInitialized).toBe(true);
    expect(useTemplateStore.getState().isLoading).toBe(false);
  });

  test('does not re-initialize if already initialized', async () => {
    await useTemplateStore.getState().initialize();
    await useTemplateStore.getState().initialize();
    expect(useTemplateStore.getState().isInitialized).toBe(true);
  });
});

describe('templateStore - create', () => {
  test('creates a new template', async () => {
    const input = { metadata: { name: 'Test Template' }, content: '<html>Test</html>' };
    const result = await useTemplateStore.getState().create(input);
    expect(result.metadata.name).toBe('Test Template');
    expect(result.content).toBe('<html>Test</html>');
    expect(result.id).toBeDefined();
    expect(result.version).toBe(1);
  });

  test('adds template to store and index', async () => {
    const input = { metadata: { name: 'Test Template' }, content: '<html>Test</html>' };
    const result = await useTemplateStore.getState().create(input);
    expect(useTemplateStore.getState().templates).toContainEqual(result);
    expect(useTemplateStore.getState().templateIndex.get(result.id)).toEqual(result);
  });

  test('sets default pageSize', async () => {
    const input = { metadata: { name: 'Test' }, content: '' };
    const result = await useTemplateStore.getState().create(input);
    expect(result.metadata.pageSize).toBeDefined();
  });
});

describe('templateStore - update', () => {
  test('updates existing template', async () => {
    const created = await useTemplateStore.getState().create({
      metadata: { name: 'Original' },
      content: '<html>Original</html>',
    });
    const updated = await useTemplateStore.getState().update(created.id, {
      metadata: { name: 'Updated' },
      content: '<html>Updated</html>',
    });
    expect(updated?.metadata.name).toBe('Updated');
    expect(updated?.content).toBe('<html>Updated</html>');
    expect(updated?.version).toBe(2);
  });

  test('returns null for non-existent template', async () => {
    const result = await useTemplateStore.getState().update('non-existent', {
      metadata: { name: 'Test' },
    });
    expect(result).toBeNull();
  });

  test('can update schemaId to null', async () => {
    const created = await useTemplateStore.getState().create({
      metadata: { name: 'Test' },
      content: '',
      schemaId: 'schema-1',
    });
    const updated = await useTemplateStore.getState().update(created.id, {
      schemaId: null,
    });
    expect(updated?.schemaId).toBeNull();
  });
});

describe('templateStore - delete', () => {
  test('removes template from store', async () => {
    const created = await useTemplateStore.getState().create({
      metadata: { name: 'To Delete' },
      content: '',
    });
    await useTemplateStore.getState().delete(created.id);
    expect(useTemplateStore.getState().templates).not.toContainEqual(created);
    expect(useTemplateStore.getState().templateIndex.has(created.id)).toBe(false);
  });

  test('clears selectedTemplateId if deleting selected', async () => {
    const created = await useTemplateStore.getState().create({
      metadata: { name: 'Selected' },
      content: '',
    });
    useTemplateStore.getState().select(created.id);
    await useTemplateStore.getState().delete(created.id);
    expect(useTemplateStore.getState().selectedTemplateId).toBeNull();
  });
});

describe('templateStore - clone', () => {
  test('clones existing template with new name', async () => {
    const original = await useTemplateStore.getState().create({
      metadata: { name: 'Original' },
      content: '<html>Content</html>',
    });
    const cloned = await useTemplateStore.getState().clone(original.id, 'Cloned Template');
    expect(cloned?.id).not.toBe(original.id);
    expect(cloned?.metadata.name).toBe('Cloned Template');
    expect(cloned?.content).toBe(original.content);
  });

  test('uses default name if not provided', async () => {
    const original = await useTemplateStore.getState().create({
      metadata: { name: 'Original' },
      content: '',
    });
    const cloned = await useTemplateStore.getState().clone(original.id);
    expect(cloned?.metadata.name).toBe('Original (Copy)');
  });

  test('returns null for non-existent template', async () => {
    const result = await useTemplateStore.getState().clone('non-existent');
    expect(result).toBeNull();
  });
});

describe('templateStore - select and getById', () => {
  test('sets selected template ID', async () => {
    const created = await useTemplateStore.getState().create({
      metadata: { name: 'Test' },
      content: '',
    });
    useTemplateStore.getState().select(created.id);
    expect(useTemplateStore.getState().selectedTemplateId).toBe(created.id);
  });

  test('can clear selection', () => {
    useTemplateStore.getState().select('some-id');
    useTemplateStore.getState().select(null);
    expect(useTemplateStore.getState().selectedTemplateId).toBeNull();
  });

  test('returns template by ID', async () => {
    const created = await useTemplateStore.getState().create({
      metadata: { name: 'Test' },
      content: '',
    });
    expect(useTemplateStore.getState().getById(created.id)).toEqual(created);
  });

  test('returns undefined for non-existent ID', () => {
    expect(useTemplateStore.getState().getById('non-existent')).toBeUndefined();
  });
});

describe('templateStore - import and clearAll', () => {
  test('imports multiple templates', async () => {
    const inputs = [
      { metadata: { name: 'Template 1' }, content: '' },
      { metadata: { name: 'Template 2' }, content: '' },
    ];
    const results = await useTemplateStore.getState().importTemplates(inputs);
    expect(results).toHaveLength(2);
    expect(useTemplateStore.getState().templates).toHaveLength(2);
  });

  test('clears all templates', async () => {
    await useTemplateStore.getState().create({
      metadata: { name: 'Template 1' },
      content: '',
    });
    await useTemplateStore.getState().create({
      metadata: { name: 'Template 2' },
      content: '',
    });
    await useTemplateStore.getState().clearAll();
    expect(useTemplateStore.getState().templates).toHaveLength(0);
    expect(useTemplateStore.getState().templateIndex.size).toBe(0);
    expect(useTemplateStore.getState().selectedTemplateId).toBeNull();
  });
});
