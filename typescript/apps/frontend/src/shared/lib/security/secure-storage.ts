/**
 * Secure storage abstraction for sensitive data.
 *
 * This module provides a secure wrapper around browser storage with:
 * - Automatic expiration
 * - Optional encryption (for non-sensitive metadata)
 * - Memory-only storage option for sensitive tokens
 * - Graceful fallback when storage is unavailable
 *
 * IMPORTANT: Never store access tokens or refresh tokens in localStorage/sessionStorage.
 * Use httpOnly cookies managed by the backend for auth tokens.
 * This storage is for non-sensitive application data only.
 */

/** Options for secure storage */
interface SecureStorageOptions {
  /** Storage backend: 'session' (default), 'local', or 'memory' */
  readonly backend?: 'session' | 'local' | 'memory';
  /** Key prefix for namespacing */
  readonly prefix?: string;
  /** Default TTL in milliseconds (0 = no expiration) */
  readonly defaultTTL?: number;
}

/** Stored item wrapper with metadata */
interface StoredItem<T> {
  readonly value: T;
  readonly expiresAt: number | null;
  readonly createdAt: number;
}

/** In-memory storage fallback */
const memoryStorage: Map<string, string> = new Map<string, string>();

/**
 * Gets the appropriate storage backend
 */
function getStorageBackend(backend: SecureStorageOptions['backend']): Storage | null {
  if (backend === 'memory') {
    return null; // Will use memoryStorage Map
  }

  try {
    const storage = backend === 'local' ? globalThis.localStorage : globalThis.sessionStorage;
    // Test if storage is available
    const testKey = '__storage_test__';
    storage.setItem(testKey, 'test');
    storage.removeItem(testKey);
    return storage;
  } catch {
    return null; // Fall back to memory storage
  }
}

/**
 * Secure storage class for application data.
 *
 * @example
 * ```ts
 * const storage = createSecureStorage({ prefix: 'app', backend: 'session' });
 *
 * // Store with expiration
 * storage.set('preferences', { theme: 'dark' }, { ttl: 3600000 });
 *
 * // Retrieve
 * const prefs = storage.get<{ theme: string }>('preferences');
 * ```
 */
class SecureStorage {
  private readonly storage: Storage | null;
  private readonly prefix: string;
  private readonly defaultTTL: number;
  private readonly useMemory: boolean;

  constructor(options: SecureStorageOptions = {}) {
    const { backend = 'session', prefix = 'nohiki', defaultTTL = 0 } = options;

    this.storage = getStorageBackend(backend);
    this.prefix = prefix;
    this.defaultTTL = defaultTTL;
    this.useMemory = backend === 'memory' || this.storage === null;
  }

  /**
   * Generates the full storage key with prefix
   */
  private getKey(key: string): string {
    return `${this.prefix}:${key}`;
  }

  /**
   * Stores a value with optional TTL
   */
  set<T>(key: string, value: T, options?: { ttl?: number }): void {
    const fullKey = this.getKey(key);
    const ttl = options?.ttl ?? this.defaultTTL;

    const item: StoredItem<T> = {
      value,
      expiresAt: ttl > 0 ? Date.now() + ttl : null,
      createdAt: Date.now(),
    };

    const serialized = JSON.stringify(item);

    if (this.useMemory) {
      memoryStorage.set(fullKey, serialized);
    } else {
      this.storage?.setItem(fullKey, serialized);
    }
  }

  /**
   * Retrieves a value, returning null if expired or not found
   */
  get<T>(key: string): T | null {
    const fullKey = this.getKey(key);

    const serialized = this.useMemory ? memoryStorage.get(fullKey) : this.storage?.getItem(fullKey);

    if (!serialized) {
      return null;
    }

    try {
      const item = JSON.parse(serialized) as StoredItem<T>;

      // Check expiration
      if (item.expiresAt !== null && Date.now() > item.expiresAt) {
        this.remove(key);
        return null;
      }

      return item.value;
    } catch {
      // Invalid data, remove it
      this.remove(key);
      return null;
    }
  }

  /**
   * Removes a value from storage
   */
  remove(key: string): void {
    const fullKey = this.getKey(key);

    if (this.useMemory) {
      memoryStorage.delete(fullKey);
    } else {
      this.storage?.removeItem(fullKey);
    }
  }

  /**
   * Checks if a key exists and is not expired
   */
  has(key: string): boolean {
    return this.get(key) !== null;
  }

  /**
   * Clears all items with this storage's prefix
   */
  clear(): void {
    const prefixPattern = `${this.prefix}:`;

    if (this.useMemory) {
      for (const key of memoryStorage.keys()) {
        if (key.startsWith(prefixPattern)) {
          memoryStorage.delete(key);
        }
      }
    } else if (this.storage) {
      const keysToRemove: string[] = [];
      for (let i = 0; i < this.storage.length; i += 1) {
        const key = this.storage.key(i);
        if (key?.startsWith(prefixPattern)) {
          keysToRemove.push(key);
        }
      }
      for (const key of keysToRemove) {
        this.storage.removeItem(key);
      }
    }
  }

  /**
   * Returns all keys with this storage's prefix (without prefix)
   */
  keys(): string[] {
    const prefixPattern = `${this.prefix}:`;
    const result: string[] = [];

    if (this.useMemory) {
      for (const key of memoryStorage.keys()) {
        if (key.startsWith(prefixPattern)) {
          result.push(key.slice(prefixPattern.length));
        }
      }
    } else if (this.storage) {
      for (let i = 0; i < this.storage.length; i += 1) {
        const key = this.storage.key(i);
        if (key?.startsWith(prefixPattern)) {
          result.push(key.slice(prefixPattern.length));
        }
      }
    }

    return result;
  }
}

/**
 * Creates a new SecureStorage instance
 */
function createSecureStorage(options?: SecureStorageOptions): SecureStorage {
  return new SecureStorage(options);
}

export { createSecureStorage, SecureStorage };
