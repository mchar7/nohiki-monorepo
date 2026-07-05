import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { createSecureStorage, SecureStorage } from './secure-storage.ts';

/** TTL used for expiry tests (1 second) */
const TEST_TTL_MS: number = 1000;
/** Elapsed time just past TTL expiry */
const TEST_TTL_EXPIRED_MS: number = 1001;
/** Very long duration used to verify no-expiry behaviour */
const TEST_NO_EXPIRY_ELAPSED_MS: number = 100_000_000;

function createMockStorage(): Storage {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => store.set(key, value),
    removeItem: (key: string) => store.delete(key),
    clear: () => store.clear(),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length(): number {
      return store.size;
    },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('sessionStorage', createMockStorage());
  vi.stubGlobal('localStorage', createMockStorage());
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('SecureStorage - createSecureStorage', () => {
  test('creates a SecureStorage instance', () => {
    const storage = createSecureStorage();
    expect(storage).toBeInstanceOf(SecureStorage);
  });

  test('accepts custom options', () => {
    const storage = createSecureStorage({
      backend: 'local',
      prefix: 'custom',
      defaultTTL: 3_600_000,
    });
    expect(storage).toBeInstanceOf(SecureStorage);
  });
});

describe('SecureStorage - set and get', () => {
  test('stores and retrieves values', () => {
    const storage = createSecureStorage();
    storage.set('key', { data: 'test' });

    const result = storage.get<{ data: string }>('key');

    expect(result).toEqual({ data: 'test' });
  });

  test('uses prefix for keys', () => {
    const storage = createSecureStorage({ prefix: 'myapp' });
    storage.set('key', 'value');

    expect(sessionStorage.getItem('myapp:key')).toBeTruthy();
  });

  test('returns null for non-existent key', () => {
    const storage = createSecureStorage();

    expect(storage.get('nonexistent')).toBeNull();
  });

  test('stores with TTL and expires correctly', () => {
    const storage = createSecureStorage();
    storage.set('key', 'value', { ttl: TEST_TTL_MS });

    expect(storage.get('key')).toBe('value');

    vi.advanceTimersByTime(TEST_TTL_EXPIRED_MS);

    expect(storage.get('key')).toBeNull();
  });

  test('uses default TTL when set', () => {
    const storage = createSecureStorage({ defaultTTL: TEST_TTL_MS });
    storage.set('key', 'value');

    vi.advanceTimersByTime(TEST_TTL_EXPIRED_MS);

    expect(storage.get('key')).toBeNull();
  });

  test('stores without expiration when TTL is 0', () => {
    const storage = createSecureStorage({ defaultTTL: 0 });
    storage.set('key', 'value');

    vi.advanceTimersByTime(TEST_NO_EXPIRY_ELAPSED_MS);

    expect(storage.get('key')).toBe('value');
  });

  test('handles invalid JSON gracefully', () => {
    const storage = createSecureStorage();
    sessionStorage.setItem('nohiki:invalid', 'not-json');

    expect(storage.get('invalid')).toBeNull();
  });
});

describe('SecureStorage - backend options', () => {
  test('uses sessionStorage by default', () => {
    const storage = createSecureStorage();
    storage.set('key', 'value');

    expect(sessionStorage.getItem('nohiki:key')).toBeTruthy();
    expect(localStorage.getItem('nohiki:key')).toBeNull();
  });

  test('uses localStorage when specified', () => {
    const storage = createSecureStorage({ backend: 'local' });
    storage.set('key', 'value');

    expect(localStorage.getItem('nohiki:key')).toBeTruthy();
    expect(sessionStorage.getItem('nohiki:key')).toBeNull();
  });

  test('uses memory storage when specified', () => {
    const storage = createSecureStorage({ backend: 'memory' });
    storage.set('key', 'value');

    expect(storage.get('key')).toBe('value');
    expect(sessionStorage.getItem('nohiki:key')).toBeNull();
    expect(localStorage.getItem('nohiki:key')).toBeNull();
  });

  test('falls back to memory when storage is unavailable', () => {
    vi.stubGlobal('sessionStorage', {
      setItem: () => {
        throw new Error('Storage unavailable');
      },
      getItem: () => null,
      removeItem: () => {
        /* noop stub */
      },
    });

    const storage = createSecureStorage({ backend: 'session' });
    storage.set('key', 'value');

    expect(storage.get('key')).toBe('value');
  });
});

describe('SecureStorage - remove', () => {
  test('removes stored value', () => {
    const storage = createSecureStorage();
    storage.set('key', 'value');

    storage.remove('key');

    expect(storage.get('key')).toBeNull();
  });

  test('handles removing non-existent key', () => {
    const storage = createSecureStorage();

    expect(() => storage.remove('nonexistent')).not.toThrow();
  });
});

describe('SecureStorage - has', () => {
  test('returns true for existing key', () => {
    const storage = createSecureStorage();
    storage.set('key', 'value');

    expect(storage.has('key')).toBe(true);
  });

  test('returns false for non-existent key', () => {
    const storage = createSecureStorage();

    expect(storage.has('nonexistent')).toBe(false);
  });

  test('returns false for expired key', () => {
    const storage = createSecureStorage();
    storage.set('key', 'value', { ttl: TEST_TTL_MS });

    vi.advanceTimersByTime(TEST_TTL_EXPIRED_MS);

    expect(storage.has('key')).toBe(false);
  });
});

describe('SecureStorage - clear', () => {
  test('clears all items with prefix', () => {
    const storage = createSecureStorage({ prefix: 'myapp' });
    storage.set('key1', 'value1');
    storage.set('key2', 'value2');

    storage.clear();

    expect(storage.get('key1')).toBeNull();
    expect(storage.get('key2')).toBeNull();
  });

  test('does not clear items with different prefix', () => {
    const storage1 = createSecureStorage({ prefix: 'app1' });
    const storage2 = createSecureStorage({ prefix: 'app2' });

    storage1.set('key', 'value1');
    storage2.set('key', 'value2');

    storage1.clear();

    expect(storage1.get('key')).toBeNull();
    expect(storage2.get('key')).toBe('value2');
  });
});

describe('SecureStorage - keys', () => {
  test('returns all keys with prefix', () => {
    const storage = createSecureStorage({ prefix: 'myapp' });
    storage.set('key1', 'value1');
    storage.set('key2', 'value2');

    const keys = storage.keys();

    expect(keys).toContain('key1');
    expect(keys).toContain('key2');
    expect(keys).toHaveLength(2);
  });

  test('returns empty array when no keys', () => {
    const storage = createSecureStorage();

    expect(storage.keys()).toEqual([]);
  });

  test('does not include keys from other prefixes', () => {
    const storage1 = createSecureStorage({ prefix: 'app1' });
    const storage2 = createSecureStorage({ prefix: 'app2' });

    storage1.set('key1', 'value1');
    storage2.set('key2', 'value2');

    expect(storage1.keys()).toEqual(['key1']);
    expect(storage2.keys()).toEqual(['key2']);
  });
});

describe('SecureStorage - memory storage', () => {
  test('persists data between calls with same prefix', () => {
    const storage1 = createSecureStorage({ backend: 'memory', prefix: 'shared' });
    storage1.set('key', 'value');

    const storage2 = createSecureStorage({ backend: 'memory', prefix: 'shared' });

    expect(storage2.get('key')).toBe('value');
  });

  test('clears memory storage correctly', () => {
    const storage = createSecureStorage({ backend: 'memory', prefix: 'test' });
    storage.set('key1', 'value1');
    storage.set('key2', 'value2');

    storage.clear();

    expect(storage.keys()).toEqual([]);
  });
});
