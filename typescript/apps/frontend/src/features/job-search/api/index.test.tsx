import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { JobListingResponse } from '@/shared/api';
import { listingsQueryOptions, useListing } from './index.ts';

const {
  mockGet,
}: {
  mockGet: ReturnType<typeof vi.fn>;
} = vi.hoisted(() => ({
  mockGet: vi.fn(),
}));

vi.mock('@/shared/api/client', async () => {
  const { default: createQueryClient } =
    await vi.importActual<typeof import('openapi-react-query')>('openapi-react-query');
  const client = {
    GET: mockGet,
    POST: vi.fn(),
    DELETE: vi.fn(),
    PATCH: vi.fn(),
    PUT: vi.fn(),
  };
  return {
    fetchClient: client,
    $api: createQueryClient(client as never),
    createDevClient: vi.fn(),
  };
});

/** Creates a mock response matching openapi-fetch's return shape (data + error + response). */
function mockFetchResponse(data: unknown): {
  data: unknown;
  error: undefined;
  response: { status: number; headers: Headers };
} {
  return {
    data,
    error: undefined,
    response: { status: 200, headers: new Headers({ 'Content-Length': '1' }) },
  };
}

function createWrapper(): ({ children }: { children: ReactNode }) => JSX.Element {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe('listingsQueryOptions / queryKey', () => {
  test('returns correct queryKey with default filters', () => {
    const opts = listingsQueryOptions();
    expect(opts.queryKey).toEqual([
      'get',
      '/api/v1/listings',
      {
        params: {
          query: {
            page: 1,
            page_size: 20,
            source: null,
            company: null,
            q: null,
            sort: 'posted_at',
            dir: 'desc',
            show_dismissed: false,
            has_salary: false,
            work_arrangement: null,
            seniority: null,
            date_range: null,
          },
        },
      },
    ]);
  });

  test('returns correct queryKey with custom filters', () => {
    const opts = listingsQueryOptions({
      page: 3,
      pageSize: 10,
      source: 'linkedin',
      company: 'Acme',
      q: 'python',
    });
    expect(opts.queryKey).toEqual([
      'get',
      '/api/v1/listings',
      {
        params: {
          query: {
            page: 3,
            page_size: 10,
            source: 'linkedin',
            company: 'Acme',
            q: 'python',
            sort: 'posted_at',
            dir: 'desc',
            show_dismissed: false,
            has_salary: false,
            work_arrangement: null,
            seniority: null,
            date_range: null,
          },
        },
      },
    ]);
  });
});

describe('listingsQueryOptions / queryFn', () => {
  test('normalizes undefined source/company/q to null in queryFn call', async () => {
    mockGet.mockResolvedValue(
      mockFetchResponse({
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        total_pages: 0,
        has_next: false,
        has_prev: false,
      }),
    );
    const opts = listingsQueryOptions();
    const { queryFn, queryKey } = opts;
    if (queryFn === undefined) {
      throw new Error('listingsQueryOptions must define a queryFn');
    }
    // $api.queryOptions produces a QueryFunctionContext-style queryFn
    await queryFn({
      client: new QueryClient(),
      queryKey,
      signal: new AbortController().signal,
      meta: undefined,
    });
    expect(mockGet).toHaveBeenCalledWith(
      '/api/v1/listings',
      expect.objectContaining({
        params: {
          query: {
            page: 1,
            page_size: 20,
            source: null,
            company: null,
            q: null,
            sort: 'posted_at',
            dir: 'desc',
            show_dismissed: false,
            has_salary: false,
            work_arrangement: null,
            seniority: null,
            date_range: null,
          },
        },
      }),
    );
  });
});

describe('useListing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches single listing', async () => {
    const mockListing = { id: 'listing-123', title: 'Software Engineer' } as JobListingResponse;
    mockGet.mockResolvedValue(mockFetchResponse(mockListing));

    const { result } = renderHook(() => useListing('listing-123'), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(mockListing);
  });

  test('does not fetch when listingId is empty', () => {
    renderHook(() => useListing(''), { wrapper: createWrapper() });

    expect(mockGet).not.toHaveBeenCalled();
  });
});
