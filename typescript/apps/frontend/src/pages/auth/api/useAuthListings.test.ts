import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { afterAll, afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { useAuthListings } from './useAuthListings.ts';

const {
  mockWorkerUrl,
  mockFetch,
}: {
  mockWorkerUrl: { value: string };
  mockFetch: ReturnType<typeof vi.fn<typeof fetch>>;
} = vi.hoisted(() => ({
  mockWorkerUrl: { value: '' },
  mockFetch: vi.fn<typeof fetch>(),
}));

vi.mock('@/shared/config', () => ({
  config: {
    services: {
      authListings: {
        get workerUrl(): string {
          return mockWorkerUrl.value;
        },
      },
    },
  },
}));

vi.mock('@/shared/api', () => ({
  CACHE_CONFIG: {
    AUTH_LISTINGS: {
      staleTime: 10_800_000,
      gcTime: 86_400_000,
    },
  },
}));

const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = mockFetch;
});

afterAll(() => {
  globalThis.fetch = originalFetch;
});

function createWrapper(): ({ children }: { children: ReactNode }) => JSX.Element {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return QueryClientProvider({ client: queryClient, children }) as JSX.Element;
  };
}

describe('useAuthListings - disabled when workerUrl is empty', () => {
  beforeEach(() => {
    mockWorkerUrl.value = '';
    mockFetch.mockReset();
  });

  test('returns placeholder data immediately when workerUrl is empty', () => {
    const { result } = renderHook(() => useAuthListings(), { wrapper: createWrapper() });

    expect(result.current.data).toEqual({ listings: [], country: '' });
    expect(result.current.isFetching).toBe(false);
  });

  test('does not make any network requests when workerUrl is empty', () => {
    renderHook(() => useAuthListings(), { wrapper: createWrapper() });

    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe('useAuthListings - enabled when workerUrl is set', () => {
  const WORKER_URL = 'https://edge.example.com';

  beforeEach(() => {
    mockWorkerUrl.value = WORKER_URL;
    mockFetch.mockReset();
  });

  afterEach(() => {
    mockFetch.mockReset();
  });

  test('fetches from the worker URL when available', async () => {
    const mockData = { listings: [{ title: 'Engineer' }], country: 'DEU' };
    mockFetch.mockResolvedValue(new Response(JSON.stringify(mockData), { status: 200 }));

    const { result } = renderHook(() => useAuthListings(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isPlaceholderData).toBe(false));

    expect(mockFetch).toHaveBeenCalledWith(`${WORKER_URL}/auth-listings`);
    expect(result.current.data).toEqual(mockData);
  });

  test('returns empty response on non-ok HTTP status', async () => {
    mockFetch.mockResolvedValue(new Response('', { status: 500 }));

    const { result } = renderHook(() => useAuthListings(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual({ listings: [], country: '' });
  });

  test('returns empty response on network error', async () => {
    mockFetch.mockRejectedValue(new TypeError('Network failure'));

    const { result } = renderHook(() => useAuthListings(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual({ listings: [], country: '' });
  });
});

describe('useAuthListings - query configuration', () => {
  beforeEach(() => {
    mockWorkerUrl.value = '';
    mockFetch.mockReset();
  });

  test('provides placeholder data matching empty response shape', () => {
    const { result } = renderHook(() => useAuthListings(), { wrapper: createWrapper() });

    // placeholderData is returned as `data` when the query is disabled
    expect(result.current.data).toEqual({ listings: [], country: '' });
    expect(result.current.data?.listings).toEqual([]);
    expect(result.current.data?.country).toBe('');
  });

  test('does not retry on failure', async () => {
    mockWorkerUrl.value = 'https://edge.example.com';
    mockFetch.mockRejectedValue(new TypeError('fail'));

    const { result } = renderHook(() => useAuthListings(), { wrapper: createWrapper() });

    // The queryFn catches errors and returns EMPTY_RESPONSE, so it always succeeds.
    // retry: false ensures no retries if the query itself were to fail.
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Only called once, with no retries
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
