import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { isSecureFetchError, secureFetch } from './secure-fetch.ts';

/** Non-object primitive used to test type guard rejection */
const TEST_NON_OBJECT_NUMBER: number = 123;

vi.mock('@/shared/config', () => ({
  config: {
    api: {
      baseUrl: 'https://api.test.com',
      timeout: 5000,
    },
  },
}));

let originalFetch: typeof globalThis.fetch;

beforeEach(() => {
  originalFetch = globalThis.fetch;

  vi.stubGlobal('sessionStorage', {
    getItem: vi.fn().mockReturnValue(null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('secure-fetch - isSecureFetchError', () => {
  test('returns true for valid SecureFetchError', () => {
    const error = {
      type: 'network',
      message: 'Connection failed',
      url: 'https://api.test.com/endpoint',
    };

    expect(isSecureFetchError(error)).toBe(true);
  });

  test('returns true for error with all fields', () => {
    const error = {
      type: 'http',
      message: 'Not Found',
      url: 'https://api.test.com/endpoint',
      status: 404,
      statusText: 'Not Found',
    };

    expect(isSecureFetchError(error)).toBe(true);
  });

  test('returns false for null', () => {
    expect(isSecureFetchError(null)).toBe(false);
  });

  test('returns false for undefined', () => {
    expect(isSecureFetchError(undefined)).toBe(false);
  });

  test('returns false for non-object', () => {
    expect(isSecureFetchError('string')).toBe(false);
    expect(isSecureFetchError(TEST_NON_OBJECT_NUMBER)).toBe(false);
  });

  test('returns false for object missing required fields', () => {
    expect(isSecureFetchError({ type: 'network' })).toBe(false);
    expect(isSecureFetchError({ message: 'error' })).toBe(false);
    expect(isSecureFetchError({ type: 'network', message: 'error' })).toBe(false);
  });
});

describe('secureFetch - request construction', () => {
  test('makes request to correct URL with base URL', async () => {
    const mockResponse = { data: 'test' };
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
      headers: new Headers({ 'content-length': '100' }),
    });

    const result = await secureFetch('/endpoint');

    expect(result).toEqual(mockResponse);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'https://api.test.com/endpoint',
      expect.objectContaining({
        method: 'GET',
        credentials: 'include',
      }),
    );
  });

  test('sets default Content-Type header', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
      headers: new Headers({ 'content-length': '2' }),
    });

    await secureFetch('/endpoint');

    const [, callOptions] = nonNull(vi.mocked(globalThis.fetch).mock.calls[0]);
    const headers = callOptions?.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  test('allows base URL override', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
      headers: new Headers({ 'content-length': '2' }),
    });

    await secureFetch('/endpoint', { baseUrl: 'https://other-api.com' });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      'https://other-api.com/endpoint',
      expect.any(Object),
    );
  });
});

describe('secureFetch - CSRF handling', () => {
  test('includes CSRF token for POST requests', async () => {
    vi.mocked(sessionStorage.getItem).mockReturnValue('csrf-token-123');

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
      headers: new Headers({ 'content-length': '2' }),
    });

    await secureFetch('/endpoint', { method: 'POST' });

    const [, callOptions] = nonNull(vi.mocked(globalThis.fetch).mock.calls[0]);
    const headers = callOptions?.headers as Headers;
    expect(headers.get('X-CSRF-Token')).toBe('csrf-token-123');
  });

  test('does not include CSRF token for GET requests', async () => {
    vi.mocked(sessionStorage.getItem).mockReturnValue('csrf-token-123');

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
      headers: new Headers({ 'content-length': '2' }),
    });

    await secureFetch('/endpoint', { method: 'GET' });

    const [, callOptions] = nonNull(vi.mocked(globalThis.fetch).mock.calls[0]);
    const headers = callOptions?.headers as Headers;
    expect(headers.get('X-CSRF-Token')).toBeNull();
  });

  test('allows explicit CSRF override', async () => {
    vi.mocked(sessionStorage.getItem).mockReturnValue('csrf-token-123');

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
      headers: new Headers({ 'content-length': '2' }),
    });

    await secureFetch('/endpoint', { method: 'POST', includeCSRF: false });

    const [, callOptions] = nonNull(vi.mocked(globalThis.fetch).mock.calls[0]);
    const headers = callOptions?.headers as Headers;
    expect(headers.get('X-CSRF-Token')).toBeNull();
  });
});

describe('secureFetch - response handling', () => {
  test('throws http error for non-ok response', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      headers: new Headers(),
    });

    await expect(secureFetch('/endpoint')).rejects.toMatchObject({
      type: 'http',
      status: 404,
      statusText: 'Not Found',
    });
  });

  test('returns undefined for 204 No Content', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers(),
    });

    const result = await secureFetch('/endpoint');

    expect(result).toBeUndefined();
  });

  test('returns undefined for empty response', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-length': '0' }),
    });

    const result = await secureFetch('/endpoint');

    expect(result).toBeUndefined();
  });

  test('throws parse error for invalid JSON', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-length': '100' }),
      json: () => Promise.reject(new Error('Invalid JSON')),
    });

    await expect(secureFetch('/endpoint')).rejects.toMatchObject({
      type: 'parse',
      message: expect.stringContaining('Failed to parse response as JSON'),
    });
  });
});

describe('secureFetch - error handling', () => {
  test('throws timeout error when request times out', async () => {
    globalThis.fetch = vi.fn().mockImplementation(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          options?.signal?.addEventListener('abort', () => {
            const error = new DOMException('Aborted', 'AbortError');
            reject(error);
          });
        }),
    );

    await expect(secureFetch('/endpoint', { timeout: 10 })).rejects.toMatchObject({
      type: 'timeout',
    });
  });

  test('throws network error for fetch failure', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

    await expect(secureFetch('/endpoint')).rejects.toMatchObject({
      type: 'network',
      message: 'Network error',
    });
  });
});
