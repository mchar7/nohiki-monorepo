/**
 * Cache utilities for O(1) lookups and localStorage persistence.
 *
 * Design principles:
 * - Use Map for O(1) key lookups instead of Array.find() O(n)
 * - Memoize expensive transformations
 * - Sync with localStorage for offline support
 */

import { STORAGE_KEYS } from '@/shared/api/config.ts';

interface CacheableItem {
  id: string;
}

/**
 * Creates a Map index from an array for O(1) lookups by ID.
 * Time: O(n) to build, O(1) per lookup
 * Space: O(n)
 */
function createIndex<T extends CacheableItem>(items: readonly T[]): Map<string, T> {
  const index = new Map<string, T>();
  for (const item of items) {
    index.set(item.id, item);
  }
  return index;
}

/**
 * Creates a multi-index Map for O(1) lookups by a custom key.
 * Useful for grouping items by a foreign key.
 * Time: O(n) to build, O(1) per lookup
 */
function createMultiIndex<T>(items: readonly T[], keyFn: (item: T) => string): Map<string, T[]> {
  const index = new Map<string, T[]>();
  for (const item of items) {
    const key = keyFn(item);
    const existing = index.get(key);
    if (existing) {
      existing.push(item);
    } else {
      index.set(key, [item]);
    }
  }
  return index;
}

/**
 * Memoizes index creation to avoid rebuilding on every render.
 * Uses a WeakMap to allow garbage collection when source array changes.
 */
const indexCache: WeakMap<readonly CacheableItem[], Map<string, CacheableItem>> = new WeakMap<
  readonly CacheableItem[],
  Map<string, CacheableItem>
>();

function getOrCreateIndex<T extends CacheableItem>(items: readonly T[]): Map<string, T> {
  let index = indexCache.get(items) as Map<string, T> | undefined;
  if (!index) {
    index = createIndex(items);
    indexCache.set(items, index as Map<string, CacheableItem>);
  }
  return index;
}

/**
 * localStorage cache with automatic JSON serialization and TTL support.
 */
interface CacheEntry<T> {
  readonly data: T;
  readonly timestamp: number;
  readonly ttlMs: number;
}

function setLocalCache<T>(key: string, data: T, ttlMs: number): void {
  const entry: CacheEntry<T> = {
    data,
    timestamp: Date.now(),
    ttlMs,
  };
  try {
    localStorage.setItem(key, JSON.stringify(entry));
  } catch {
    // Storage quota exceeded or unavailable - cache write is best-effort
  }
}

function getLocalCache<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) {
      return null;
    }

    const entry = JSON.parse(raw) as CacheEntry<T>;
    const isExpired = Date.now() - entry.timestamp > entry.ttlMs;

    if (isExpired) {
      localStorage.removeItem(key);
      return null;
    }

    return entry.data;
  } catch {
    return null;
  }
}

function clearLocalCache(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Storage unavailable - no cleanup needed
  }
}

function clearAllLocalCache(): void {
  const keysToRemove = Object.values(STORAGE_KEYS);
  for (const key of keysToRemove) {
    clearLocalCache(key);
  }
}

/**
 * Debounced localStorage sync for frequently updated data.
 * Prevents excessive writes while ensuring eventual consistency.
 */
function createDebouncedSync<T>(
  key: string,
  ttlMs: number,
  delayMs: number = 1000,
): (data: T) => void {
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let pendingData: T | null = null;

  return (data: T) => {
    pendingData = data;

    if (timeoutId) {
      clearTimeout(timeoutId);
    }

    timeoutId = setTimeout(() => {
      if (pendingData !== null) {
        setLocalCache(key, pendingData, ttlMs);
        pendingData = null;
      }
      timeoutId = null;
    }, delayMs);
  };
}

/**
 * Hook-compatible cache utilities for use with useMemo.
 */
function useIndexedLookup<T extends CacheableItem>(
  items: readonly T[] | undefined,
): (id: string) => T | undefined {
  if (!items || items.length === 0) {
    return () => undefined;
  }

  const index = getOrCreateIndex(items);
  return (id: string) => index.get(id);
}

export {
  clearAllLocalCache,
  clearLocalCache,
  createDebouncedSync,
  createIndex,
  createMultiIndex,
  getLocalCache,
  getOrCreateIndex,
  setLocalCache,
  useIndexedLookup,
};
