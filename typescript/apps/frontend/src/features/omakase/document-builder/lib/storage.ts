import { clear, del, get, keys, set } from 'idb-keyval';

interface StorageItem<T = unknown> {
  id: string;
  data: T;
  createdAt: string;
  updatedAt: string;
}

interface StorageQuota {
  quota: number;
  usage: number;
  available: number;
}

class Storage<T = unknown> {
  private readonly prefix: string;

  constructor(prefix: string) {
    this.prefix = prefix;
  }

  private getKey(id: string): string {
    return `${this.prefix}:${id}`;
  }

  async save(id: string, data: T): Promise<void> {
    const now = new Date().toISOString();
    const item: StorageItem<T> = {
      id,
      data,
      createdAt: now,
      updatedAt: now,
    };

    try {
      const existing = await this.load(id);
      if (existing) {
        item.createdAt = existing.createdAt;
      }
      await set(this.getKey(id), item);
    } catch (error) {
      if (this.isQuotaError(error)) {
        this.fallbackToLocalStorage(id, item);
      } else {
        throw error;
      }
    }
  }

  async load(id: string): Promise<StorageItem<T> | null> {
    try {
      const item = await get<StorageItem<T>>(this.getKey(id));
      return item || null;
    } catch {
      return this.loadFromLocalStorage(id);
    }
  }

  async delete(id: string): Promise<void> {
    try {
      await del(this.getKey(id));
    } catch {
      localStorage.removeItem(this.getKey(id));
    }
  }

  async list(): Promise<StorageItem<T>[]> {
    try {
      const allKeys = await keys();
      const storageKeys = allKeys.filter((key: IDBValidKey) => {
        const keyStr: string = typeof key === 'string' ? key : '';
        return keyStr.startsWith(`${this.prefix}:`);
      });

      const items = await Promise.all(
        storageKeys.map(async (key: IDBValidKey) => {
          try {
            return await get<StorageItem<T>>(key);
          } catch {
            return null;
          }
        }),
      );

      return items.filter(
        (item: StorageItem<T> | null | undefined): item is StorageItem<T> => item !== null,
      );
    } catch {
      return this.listFromLocalStorage();
    }
  }

  async clear(): Promise<void> {
    try {
      const allKeys = await keys();
      const storageKeys = allKeys.filter((key: IDBValidKey) => {
        const keyStr: string = typeof key === 'string' ? key : '';
        return keyStr.startsWith(`${this.prefix}:`);
      });

      await Promise.all(storageKeys.map((key: IDBValidKey) => del(key)));
    } catch {
      const localKeys = Object.keys(localStorage).filter((key) =>
        key.startsWith(`${this.prefix}:`),
      );
      for (const key of localKeys) {
        localStorage.removeItem(key);
      }
    }
  }

  private isQuotaError(error: unknown): boolean {
    return (
      error instanceof Error &&
      (error.name === 'QuotaExceededError' ||
        error.message.includes('quota') ||
        error.message.includes('storage'))
    );
  }

  private fallbackToLocalStorage(id: string, item: StorageItem<T>): void {
    try {
      localStorage.setItem(this.getKey(id), JSON.stringify(item));
    } catch (error) {
      throw new Error('Storage quota exceeded', { cause: error });
    }
  }

  private loadFromLocalStorage(id: string): StorageItem<T> | null {
    try {
      const item = localStorage.getItem(this.getKey(id));
      if (item) {
        return JSON.parse(item);
      }
      return null;
    } catch {
      return null;
    }
  }

  private listFromLocalStorage(): StorageItem<T>[] {
    const items: StorageItem<T>[] = [];
    const prefix = `${this.prefix}:`;

    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key?.startsWith(prefix)) {
        try {
          const item = localStorage.getItem(key);
          if (item) {
            items.push(JSON.parse(item));
          }
        } catch {
          // Ignore individual parse errors in localStorage fallback
        }
      }
    }

    return items;
  }
}

const templateStorage: Storage<unknown> = new Storage('template');
const datasetStorage: Storage<unknown> = new Storage('dataset');

async function getStorageQuota(): Promise<StorageQuota> {
  if ('storage' in navigator && navigator.storage && 'estimate' in navigator.storage) {
    try {
      const estimate = await navigator.storage.estimate();
      return {
        quota: estimate.quota || 0,
        usage: estimate.usage || 0,
        available: (estimate.quota || 0) - (estimate.usage || 0),
      };
    } catch {
      return { quota: 0, usage: 0, available: 0 };
    }
  }
  return { quota: 0, usage: 0, available: 0 };
}

async function clearAllStorage(): Promise<void> {
  await Promise.all([templateStorage.clear(), datasetStorage.clear()]);
}

async function migrateStorage(version: string): Promise<void> {
  const migrationKey = `migration:${version}`;
  const migrated = localStorage.getItem(migrationKey);

  if (!migrated) {
    try {
      await clear();
      localStorage.setItem(migrationKey, 'true');
    } catch {
      // Migration failure is non-critical - storage will be cleared on next migration attempt
    }
  }
}

export { clearAllStorage, datasetStorage, getStorageQuota, migrateStorage, templateStorage };
