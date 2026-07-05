import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import {
  clearAllLocalCache,
  clearLocalCache,
  createDebouncedSync,
  createIndex,
  createMultiIndex,
  getLocalCache,
  getOrCreateIndex,
  setLocalCache,
  useIndexedLookup,
} from './cache.ts';

/** Number of items in the 3-item test dataset */
const TEST_INDEX_SIZE_THREE: number = 3;
/** Numeric value used as object property in setLocalCache tests */
const TEST_NUMERIC_VALUE: number = 42;
/** Standard short cache TTL (1 minute in ms) */
const CACHE_TTL_ONE_MINUTE_MS: number = 60_000;
/** Short TTL for expiry tests (1 second) */
const CACHE_TTL_SHORT_MS: number = 1000;
/** Time elapsed past short TTL expiry */
const CACHE_TTL_ELAPSED_PAST_MS: number = 2000;
/** Medium cache TTL (5 seconds) */
const CACHE_TTL_MEDIUM_MS: number = 5000;
/** Time elapsed before medium TTL expires */
const CACHE_TTL_BEFORE_MEDIUM_MS: number = 3000;
/** MB multiplier for huge-data test */
const BYTES_PER_KB: number = 1024;
const BYTES_PER_MB: number = BYTES_PER_KB * BYTES_PER_KB;
/** Size of huge data blob (10 MB) */
const HUGE_DATA_SIZE_MB: number = 10;
const HUGE_DATA_SIZE_BYTES: number = HUGE_DATA_SIZE_MB * BYTES_PER_MB;
/** Debounce delay for sync tests (ms) */
const DEBOUNCE_SYNC_DELAY_MS: number = 100;
/** Time elapsed past debounce delay */
const DEBOUNCE_SYNC_ELAPSED_MS: number = 150;
/** Time elapsed to mid-debounce for reset test */
const DEBOUNCE_SYNC_HALF_MS: number = 50;

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('createIndex', () => {
  test('creates a Map index from an array of items', () => {
    const items = [
      { id: '1', name: 'Item 1' },
      { id: '2', name: 'Item 2' },
      { id: '3', name: 'Item 3' },
    ];

    const index = createIndex(items);

    expect(index.size).toBe(TEST_INDEX_SIZE_THREE);
    expect(index.get('1')).toEqual({ id: '1', name: 'Item 1' });
    expect(index.get('2')).toEqual({ id: '2', name: 'Item 2' });
    expect(index.get('3')).toEqual({ id: '3', name: 'Item 3' });
  });

  test('handles empty array', () => {
    const index = createIndex([]);
    expect(index.size).toBe(0);
  });

  test('overwrites duplicate IDs with last occurrence', () => {
    const items = [
      { id: '1', name: 'First' },
      { id: '1', name: 'Second' },
    ];

    const index = createIndex(items);

    expect(index.size).toBe(1);
    expect(index.get('1')).toEqual({ id: '1', name: 'Second' });
  });
});

describe('createMultiIndex', () => {
  test('creates a multi-index Map grouped by key function', () => {
    const items = [
      { id: '1', category: 'A' },
      { id: '2', category: 'B' },
      { id: '3', category: 'A' },
    ];

    const index = createMultiIndex(items, (item) => item.category);

    expect(index.size).toBe(2);
    expect(index.get('A')).toHaveLength(2);
    expect(index.get('B')).toHaveLength(1);
  });

  test('handles empty array', () => {
    const index = createMultiIndex([], (item: { category: string }) => item.category);
    expect(index.size).toBe(0);
  });
});

describe('getOrCreateIndex', () => {
  test('creates and caches index for array', () => {
    const items = [
      { id: '1', name: 'Item 1' },
      { id: '2', name: 'Item 2' },
    ];

    const index1 = getOrCreateIndex(items);
    const index2 = getOrCreateIndex(items);

    expect(index1).toBe(index2);
    expect(index1.get('1')).toEqual({ id: '1', name: 'Item 1' });
  });

  test('creates new index for different array reference', () => {
    const items1 = [{ id: '1', name: 'Item 1' }];
    const items2 = [{ id: '1', name: 'Item 1' }];

    const index1 = getOrCreateIndex(items1);
    const index2 = getOrCreateIndex(items2);

    expect(index1).not.toBe(index2);
  });
});

describe('setLocalCache and getLocalCache', () => {
  test('stores and retrieves data from localStorage', () => {
    const data = { foo: 'bar', count: TEST_NUMERIC_VALUE };
    setLocalCache('test-key', data, CACHE_TTL_ONE_MINUTE_MS);

    const retrieved = getLocalCache<typeof data>('test-key');
    expect(retrieved).toEqual(data);
  });

  test('returns null for non-existent key', () => {
    const result = getLocalCache('non-existent');
    expect(result).toBeNull();
  });

  test('returns null for expired cache', () => {
    const data = { foo: 'bar' };
    setLocalCache('test-key', data, CACHE_TTL_SHORT_MS);

    vi.advanceTimersByTime(CACHE_TTL_ELAPSED_PAST_MS);

    const result = getLocalCache<typeof data>('test-key');
    expect(result).toBeNull();
  });

  test('returns data before TTL expires', () => {
    const data = { foo: 'bar' };
    setLocalCache('test-key', data, CACHE_TTL_MEDIUM_MS);

    vi.advanceTimersByTime(CACHE_TTL_BEFORE_MEDIUM_MS);

    const result = getLocalCache<typeof data>('test-key');
    expect(result).toEqual(data);
  });

  test('handles localStorage quota exceeded gracefully', () => {
    const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => {
      /* suppress test output */
    });

    const hugeData = { data: 'x'.repeat(HUGE_DATA_SIZE_BYTES) };
    setLocalCache('huge-key', hugeData, CACHE_TTL_ONE_MINUTE_MS);

    consoleSpy.mockRestore();

    // The write silently fails on quota error; reading back returns null
    const result = getLocalCache('huge-key');
    expect(result).toBeNull();
  });

  test('handles invalid JSON in localStorage gracefully', () => {
    localStorage.setItem('test-key', 'invalid json');

    const result = getLocalCache('test-key');
    expect(result).toBeNull();
  });
});

describe('clearLocalCache', () => {
  test('removes item from localStorage', () => {
    localStorage.setItem('test-key', 'value');
    clearLocalCache('test-key');
    expect(localStorage.getItem('test-key')).toBeNull();
  });

  test('does not throw on non-existent key', () => {
    expect(() => clearLocalCache('non-existent-key')).not.toThrow();
  });
});

describe('clearAllLocalCache', () => {
  test('clears all storage keys defined in STORAGE_KEYS', () => {
    localStorage.setItem('nohiki:auth:state', 'data1');
    localStorage.setItem('nohiki:profile:selected', 'data2');
    localStorage.setItem('nohiki:theme', 'data3');
    localStorage.setItem('nohiki:sidebar:collapsed', 'data4');
    localStorage.setItem('other-key', 'data5');

    clearAllLocalCache();

    expect(localStorage.getItem('nohiki:auth:state')).toBeNull();
    expect(localStorage.getItem('nohiki:profile:selected')).toBeNull();
    expect(localStorage.getItem('nohiki:theme')).toBeNull();
    expect(localStorage.getItem('nohiki:sidebar:collapsed')).toBeNull();
    expect(localStorage.getItem('other-key')).toBe('data5');
  });
});

describe('createDebouncedSync', () => {
  test('debounces localStorage writes', () => {
    const sync = createDebouncedSync<{ count: number }>(
      'test-key',
      CACHE_TTL_ONE_MINUTE_MS,
      DEBOUNCE_SYNC_DELAY_MS,
    );

    sync({ count: 1 });
    sync({ count: 2 });
    sync({ count: 3 });

    expect(localStorage.getItem('test-key')).toBeNull();

    vi.advanceTimersByTime(DEBOUNCE_SYNC_ELAPSED_MS);

    const cached = getLocalCache<{ count: number }>('test-key');
    expect(cached).toEqual({ count: 3 });
  });

  test('resets timer on subsequent calls', () => {
    const sync = createDebouncedSync<{ count: number }>(
      'test-key',
      CACHE_TTL_ONE_MINUTE_MS,
      DEBOUNCE_SYNC_DELAY_MS,
    );

    sync({ count: 1 });
    vi.advanceTimersByTime(DEBOUNCE_SYNC_HALF_MS);
    sync({ count: 2 });
    vi.advanceTimersByTime(DEBOUNCE_SYNC_HALF_MS);
    sync({ count: 3 });

    expect(localStorage.getItem('test-key')).toBeNull();

    vi.advanceTimersByTime(DEBOUNCE_SYNC_ELAPSED_MS);

    const cached = getLocalCache<{ count: number }>('test-key');
    expect(cached).toEqual({ count: 3 });
  });
});

describe('useIndexedLookup', () => {
  test('returns lookup function for items', () => {
    const items = [
      { id: '1', name: 'Item 1' },
      { id: '2', name: 'Item 2' },
    ];

    const lookup = useIndexedLookup(items);

    expect(lookup('1')).toEqual({ id: '1', name: 'Item 1' });
    expect(lookup('2')).toEqual({ id: '2', name: 'Item 2' });
    expect(lookup('3')).toBeUndefined();
  });

  test('returns undefined for empty array', () => {
    const lookup = useIndexedLookup([]);
    expect(lookup('1')).toBeUndefined();
  });

  test('returns undefined for undefined items', () => {
    const lookup = useIndexedLookup(undefined);
    expect(lookup('1')).toBeUndefined();
  });
});
