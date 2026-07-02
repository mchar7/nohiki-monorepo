import { clear, del, get, keys, set } from 'idb-keyval';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import {
  clearAllStorage,
  datasetStorage,
  getStorageQuota,
  migrateStorage,
  templateStorage,
} from './storage.ts';

vi.mock('idb-keyval', () => ({
  get: vi.fn(),
  set: vi.fn(),
  del: vi.fn(),
  keys: vi.fn(),
  clear: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

afterEach(() => {
  vi.resetAllMocks();
});

describe('templateStorage - save', () => {
  test('saves item to IndexedDB', async () => {
    vi.mocked(get).mockResolvedValueOnce(null);
    vi.mocked(set).mockResolvedValueOnce(undefined);

    await templateStorage.save('test-id', { name: 'Test Template' });

    expect(set).toHaveBeenCalledWith(
      'template:test-id',
      expect.objectContaining({
        id: 'test-id',
        data: { name: 'Test Template' },
      }),
    );
  });

  test('preserves createdAt when updating', async () => {
    const existingItem = {
      id: 'test-id',
      data: { name: 'Old Name' },
      createdAt: '2025-01-01T00:00:00Z',
      updatedAt: '2025-01-01T00:00:00Z',
    };
    vi.mocked(get).mockResolvedValueOnce(existingItem);
    vi.mocked(set).mockResolvedValueOnce(undefined);

    await templateStorage.save('test-id', { name: 'New Name' });

    expect(set).toHaveBeenCalledWith(
      'template:test-id',
      expect.objectContaining({
        createdAt: '2025-01-01T00:00:00Z',
      }),
    );
  });

  test('falls back to localStorage on quota error', async () => {
    const quotaError = new Error('QuotaExceededError');
    quotaError.name = 'QuotaExceededError';
    vi.mocked(get).mockResolvedValueOnce(null);
    vi.mocked(set).mockRejectedValueOnce(quotaError);

    await templateStorage.save('test-id', { name: 'Test' });

    expect(localStorage.getItem('template:test-id')).toBeTruthy();
  });
});

describe('templateStorage - load', () => {
  test('loads item from IndexedDB', async () => {
    const mockItem = {
      id: 'test-id',
      data: { name: 'Test' },
      createdAt: '2025-01-01T00:00:00Z',
      updatedAt: '2025-01-01T00:00:00Z',
    };
    vi.mocked(get).mockResolvedValueOnce(mockItem);

    const result = await templateStorage.load('test-id');

    expect(result).toEqual(mockItem);
  });

  test('returns null for non-existent item', async () => {
    vi.mocked(get).mockResolvedValueOnce(undefined);

    const result = await templateStorage.load('nonexistent');

    expect(result).toBeNull();
  });

  test('falls back to localStorage on IndexedDB error', async () => {
    const mockItem = {
      id: 'test-id',
      data: { name: 'Test' },
      createdAt: '2025-01-01T00:00:00Z',
      updatedAt: '2025-01-01T00:00:00Z',
    };
    localStorage.setItem('template:test-id', JSON.stringify(mockItem));
    vi.mocked(get).mockRejectedValueOnce(new Error('IDB Error'));

    const result = await templateStorage.load('test-id');

    expect(result).toEqual(mockItem);
  });
});

describe('templateStorage - delete', () => {
  test('deletes item from IndexedDB', async () => {
    vi.mocked(del).mockResolvedValueOnce(undefined);

    await templateStorage.delete('test-id');

    expect(del).toHaveBeenCalledWith('template:test-id');
  });

  test('falls back to localStorage on IndexedDB error', async () => {
    localStorage.setItem('template:test-id', 'value');
    vi.mocked(del).mockRejectedValueOnce(new Error('IDB Error'));

    await templateStorage.delete('test-id');

    expect(localStorage.getItem('template:test-id')).toBeNull();
  });
});

describe('templateStorage - list', () => {
  test('lists all items with prefix', async () => {
    const mockItems = [
      { id: '1', data: { name: 'A' }, createdAt: '', updatedAt: '' },
      { id: '2', data: { name: 'B' }, createdAt: '', updatedAt: '' },
    ];
    vi.mocked(keys).mockResolvedValueOnce(['template:1', 'template:2', 'other:3']);
    vi.mocked(get).mockResolvedValueOnce(mockItems[0]).mockResolvedValueOnce(mockItems[1]);

    const result = await templateStorage.list();

    expect(result).toHaveLength(2);
  });

  test('filters out null items', async () => {
    vi.mocked(keys).mockResolvedValueOnce(['template:1', 'template:2']);
    vi.mocked(get)
      .mockResolvedValueOnce({ id: '1', data: {}, createdAt: '', updatedAt: '' })
      .mockResolvedValueOnce(null);

    const result = await templateStorage.list();

    expect(result).toHaveLength(1);
  });

  test('falls back to localStorage on IndexedDB error', async () => {
    const mockItem = { id: '1', data: {}, createdAt: '', updatedAt: '' };
    localStorage.setItem('template:1', JSON.stringify(mockItem));
    vi.mocked(keys).mockRejectedValueOnce(new Error('IDB Error'));

    const result = await templateStorage.list();

    expect(result).toHaveLength(1);
  });
});

describe('templateStorage - clear', () => {
  test('clears all items with prefix', async () => {
    vi.mocked(keys).mockResolvedValueOnce(['template:1', 'template:2', 'other:3']);
    vi.mocked(del).mockResolvedValue(undefined);

    await templateStorage.clear();

    expect(del).toHaveBeenCalledTimes(2);
  });

  test('falls back to localStorage on IndexedDB error', async () => {
    localStorage.setItem('template:1', 'value');
    localStorage.setItem('template:2', 'value');
    localStorage.setItem('other:3', 'value');
    vi.mocked(keys).mockRejectedValueOnce(new Error('IDB Error'));

    await templateStorage.clear();

    expect(localStorage.getItem('template:1')).toBeNull();
    expect(localStorage.getItem('template:2')).toBeNull();
    expect(localStorage.getItem('other:3')).toBe('value');
  });
});

describe('datasetStorage', () => {
  test('uses correct prefix', async () => {
    vi.mocked(get).mockResolvedValueOnce(null);
    vi.mocked(set).mockResolvedValueOnce(undefined);

    await datasetStorage.save('test-id', { title: 'Dataset' });

    expect(set).toHaveBeenCalledWith('dataset:test-id', expect.any(Object));
  });
});

describe('getStorageQuota', () => {
  test('returns storage estimate when available', async () => {
    const mockEstimate = { quota: 1_000_000, usage: 50_000 };
    Object.defineProperty(navigator, 'storage', {
      value: { estimate: vi.fn().mockResolvedValueOnce(mockEstimate) },
      configurable: true,
    });

    const result = await getStorageQuota();

    expect(result).toEqual({
      quota: 1_000_000,
      usage: 50_000,
      available: 950_000,
    });
  });

  test('returns zeros when storage API unavailable', async () => {
    const originalStorage = navigator.storage;
    Object.defineProperty(navigator, 'storage', {
      value: undefined,
      configurable: true,
    });

    const result = await getStorageQuota();

    expect(result).toEqual({ quota: 0, usage: 0, available: 0 });

    Object.defineProperty(navigator, 'storage', {
      value: originalStorage,
      configurable: true,
    });
  });
});

describe('clearAllStorage', () => {
  test('clears both template and dataset storage', async () => {
    vi.mocked(keys).mockResolvedValue([]);

    await clearAllStorage();

    expect(keys).toHaveBeenCalledTimes(2);
  });
});

describe('migrateStorage', () => {
  test('performs migration when not already done', async () => {
    vi.mocked(clear).mockResolvedValueOnce(undefined);

    await migrateStorage('v1.0.0');

    expect(clear).toHaveBeenCalled();
    expect(localStorage.getItem('migration:v1.0.0')).toBe('true');
  });

  test('skips migration when already done', async () => {
    localStorage.setItem('migration:v1.0.0', 'true');

    await migrateStorage('v1.0.0');

    expect(clear).not.toHaveBeenCalled();
  });
});
