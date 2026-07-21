import 'fake-indexeddb/auto';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { DeveloperInfo } from './DeveloperInfo.tsx';

const originalLocation = globalThis.location;

describe('DeveloperInfo cache clearing', () => {
  beforeEach(() => {
    localStorage.setItem('private', 'value');
    sessionStorage.setItem('private', 'value');
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal('location', originalLocation);
    localStorage.clear();
    sessionStorage.clear();
  });

  test('awaits IndexedDB deletion before reloading', async () => {
    let finishDeletion: (() => void) | undefined;
    const request = indexedDB.deleteDatabase('private-cache');
    vi.spyOn(indexedDB, 'databases').mockResolvedValue([{ name: 'private-cache', version: 1 }]);
    vi.spyOn(indexedDB, 'deleteDatabase').mockImplementation(() => {
      const pending = {} as IDBOpenDBRequest;
      Object.defineProperty(pending, 'onsuccess', {
        set(handler: ((event: Event) => void) | null) {
          finishDeletion = () => handler?.(new Event('success'));
        },
      });
      return pending;
    });
    const reload = vi.fn();
    vi.stubGlobal('location', { ...originalLocation, reload });

    render(<DeveloperInfo />);
    fireEvent.click(screen.getByRole('button', { name: /clear cache/iu }));

    await waitFor(() => expect(indexedDB.deleteDatabase).toHaveBeenCalledWith('private-cache'));
    expect(reload).not.toHaveBeenCalled();
    finishDeletion?.();
    await waitFor(() => expect(reload).toHaveBeenCalledOnce());
    request.onerror = null;
  });

  test('reports IndexedDB deletion rejection and does not reload', async () => {
    vi.spyOn(indexedDB, 'databases').mockResolvedValue([{ name: 'private-cache', version: 1 }]);
    vi.spyOn(indexedDB, 'deleteDatabase').mockImplementation(() => {
      const pending = {} as IDBOpenDBRequest;
      queueMicrotask(() => pending.onblocked?.(new IDBVersionChangeEvent('blocked')));
      return pending;
    });
    const reload = vi.fn();
    vi.stubGlobal('location', { ...originalLocation, reload });

    render(<DeveloperInfo />);
    fireEvent.click(screen.getByRole('button', { name: /clear cache/iu }));

    expect(await screen.findByText('IndexedDB deletion blocked: private-cache')).toBeVisible();
    expect(reload).not.toHaveBeenCalled();
  });
});
