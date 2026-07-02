import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { JobCorrelationResponse } from '@/shared/api';
import {
  correlationDetailQueryOptions,
  correlationsQueryOptions,
  useCorrelation,
  useMyCorrelations,
} from './index.ts';

const {
  mockGet,
}: {
  mockGet: ReturnType<typeof vi.fn>;
} = vi.hoisted(() => ({
  mockGet: vi.fn(),
}));

vi.mock('@/shared/api/client', async () => {
  const { default: createQueryClient } = await import('openapi-react-query');
  const fakeFetchClient = {
    GET: mockGet,
    POST: vi.fn(),
    DELETE: vi.fn(),
    PATCH: vi.fn(),
    PUT: vi.fn(),
  };
  return {
    fetchClient: fakeFetchClient,
    $api: createQueryClient(fakeFetchClient as never),
    createDevClient: vi.fn(),
  };
});

/** Minimal Response stub satisfying openapi-react-query's queryFn (checks response.status / headers). */
const okResponse: { status: number; headers: Headers } = {
  status: 200,
  headers: new Headers({ 'Content-Length': '1' }),
};

function createWrapper(): ({ children }: { children: ReactNode }) => JSX.Element {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe('correlationsQueryOptions', () => {
  test('returns queryKey starting with get and the API path', () => {
    const opts = correlationsQueryOptions();
    expect(opts.queryKey[0]).toBe('get');
    expect(opts.queryKey[1]).toBe('/api/v1/listings/correlations/mine');
  });
});

describe('correlationDetailQueryOptions', () => {
  test('returns queryKey with correlation path', () => {
    const opts = correlationDetailQueryOptions('corr-123');
    expect(opts.queryKey[0]).toBe('get');
    expect(opts.queryKey[1]).toBe('/api/v1/listings/correlations/{correlation_id}');
  });

  test('is disabled when correlationId is empty', () => {
    const opts = correlationDetailQueryOptions('');
    expect(opts.enabled).toBe(false);
  });
});

describe('useMyCorrelations - default filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches correlations with default filters', async () => {
    mockGet.mockResolvedValue({
      data: {
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        total_pages: 0,
        has_next: false,
        has_prev: false,
      },
      error: undefined,
      response: okResponse,
    });

    const { result } = renderHook(() => useMyCorrelations(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(mockGet).toHaveBeenCalledWith(
      '/api/v1/listings/correlations/mine',
      expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({ page: 1, page_size: 20 }),
        }),
      }),
    );
  });
});

describe('useMyCorrelations - custom filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('forwards the URL percentage on the API integer scale', async () => {
    mockGet.mockResolvedValue({
      data: {
        items: [],
        total: 0,
        page: 2,
        page_size: 10,
        total_pages: 0,
        has_next: false,
        has_prev: false,
      },
      error: undefined,
      response: okResponse,
    });

    const { result } = renderHook(
      () => useMyCorrelations({ page: 2, pageSize: 10, prefId: 'pref-123', minScore: 50 }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(mockGet).toHaveBeenCalledWith(
      '/api/v1/listings/correlations/mine',
      expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({
            page: 2,
            page_size: 10,
            pref_id: 'pref-123',
            min_score: 50,
          }),
        }),
      }),
    );
  });
});

describe('useCorrelation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches single correlation', async () => {
    const mockCorrelation: JobCorrelationResponse = {
      id: 'corr-123',
      pref_id: 'pref-123',
      listing_id: 'listing-123',
      fit_score: 85,
      status: 'EVALUATED',
      score_breakdown: {},
      listing_title: 'Senior Engineer',
      listing_company: 'Example Co',
      listing_url: 'https://example.com/jobs/123',
      listing_location: 'Remote',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    };
    mockGet.mockResolvedValue({ data: mockCorrelation, error: undefined, response: okResponse });

    const { result } = renderHook(() => useCorrelation('corr-123'), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(mockCorrelation);
  });

  test('does not fetch when correlationId is empty', () => {
    renderHook(() => useCorrelation(''), { wrapper: createWrapper() });

    expect(mockGet).not.toHaveBeenCalled();
  });
});
