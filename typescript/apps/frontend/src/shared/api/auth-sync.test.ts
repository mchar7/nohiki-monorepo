import { afterEach, describe, expect, vi } from 'vitest';
import {
  AUTH_TRANSITION_STORAGE_KEY,
  publishAuthTransition,
  subscribeToAuthTransitions,
} from './auth-sync.ts';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('cross-tab auth transitions', () => {
  test('publishes every transition with a distinct value so repeated logouts reach other tabs', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    vi.spyOn(Date, 'now').mockReturnValue(1);
    vi.spyOn(Math, 'random').mockReturnValueOnce(0.1).mockReturnValueOnce(0.2);

    publishAuthTransition(null);
    publishAuthTransition(null);

    const first = setItem.mock.calls[0];
    const second = setItem.mock.calls[1];
    expect(first?.[0]).toBe(AUTH_TRANSITION_STORAGE_KEY);
    expect(second?.[0]).toBe(AUTH_TRANSITION_STORAGE_KEY);
    expect(first?.[1]).not.toBe(second?.[1]);
    expect(JSON.parse(first?.[1] ?? '')).toMatchObject({ userId: null });
  });

  test('does not reject when localStorage cannot be read', () => {
    vi.spyOn(globalThis, 'localStorage', 'get').mockImplementation(() => {
      throw new Error('storage access denied');
    });

    expect(() => publishAuthTransition('user-123')).not.toThrow();
  });

  test('does not reject when localStorage cannot be written', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage write denied');
    });

    expect(() => publishAuthTransition(null)).not.toThrow();
  });

  test('delivers remote logout and account identity changes once without rebroadcasting', () => {
    const handler = vi.fn();
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const unsubscribe = subscribeToAuthTransitions(handler);

    globalThis.dispatchEvent(
      new StorageEvent('storage', {
        key: AUTH_TRANSITION_STORAGE_KEY,
        newValue: JSON.stringify({ userId: null, nonce: 'remote-logout' }),
      }),
    );
    globalThis.dispatchEvent(
      new StorageEvent('storage', {
        key: AUTH_TRANSITION_STORAGE_KEY,
        newValue: JSON.stringify({ userId: 'other-user', nonce: 'remote-login' }),
      }),
    );

    expect(handler.mock.calls).toEqual([[null], ['other-user']]);
    expect(setItem).not.toHaveBeenCalled();

    unsubscribe();
    globalThis.dispatchEvent(
      new StorageEvent('storage', {
        key: AUTH_TRANSITION_STORAGE_KEY,
        newValue: JSON.stringify({ userId: null, nonce: 'after-unsubscribe' }),
      }),
    );
    expect(handler).toHaveBeenCalledTimes(2);
  });

  test('ignores unrelated, removed, and malformed storage values', () => {
    const handler = vi.fn();
    const unsubscribe = subscribeToAuthTransitions(handler);

    globalThis.dispatchEvent(
      new StorageEvent('storage', { key: 'nohiki:theme', newValue: 'dark' }),
    );
    globalThis.dispatchEvent(
      new StorageEvent('storage', { key: AUTH_TRANSITION_STORAGE_KEY, newValue: null }),
    );
    globalThis.dispatchEvent(
      new StorageEvent('storage', { key: AUTH_TRANSITION_STORAGE_KEY, newValue: '{' }),
    );
    globalThis.dispatchEvent(
      new StorageEvent('storage', {
        key: AUTH_TRANSITION_STORAGE_KEY,
        newValue: JSON.stringify({ userId: 42, nonce: 'invalid' }),
      }),
    );

    expect(handler).not.toHaveBeenCalled();
    unsubscribe();
  });
});
