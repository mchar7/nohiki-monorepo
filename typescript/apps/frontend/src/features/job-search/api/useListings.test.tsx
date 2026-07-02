import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useListings } from './index.ts';

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

describe('useListings - default filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches listings with default filters', async () => {
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

    const { result } = renderHook(() => useListings(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
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

describe('useListings - custom filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches listings with custom filters', async () => {
    mockGet.mockResolvedValue(
      mockFetchResponse({
        items: [],
        total: 0,
        page: 2,
        page_size: 10,
        total_pages: 0,
        has_next: false,
        has_prev: false,
      }),
    );

    const { result } = renderHook(
      () =>
        useListings({
          page: 2,
          pageSize: 10,
          source: 'linkedin',
          company: 'Acme',
          q: 'python',
          sort: 'match_score',
          dir: 'asc',
          showDismissed: true,
          hasSalary: true,
          workArrangement: 'remote',
          seniority: 'senior',
          dateRange: '7d',
        }),
      { wrapper: createWrapper() },
    );
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(mockGet).toHaveBeenCalledWith(
      '/api/v1/listings',
      expect.objectContaining({
        params: {
          query: {
            page: 2,
            page_size: 10,
            source: 'linkedin',
            company: 'Acme',
            q: 'python',
            sort: 'match_score',
            dir: 'asc',
            show_dismissed: true,
            has_salary: true,
            work_arrangement: 'remote',
            seniority: 'senior',
            date_range: '7d',
          },
        },
      }),
    );
  });
});

describe('useListings - search query', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches listings with search query', async () => {
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

    const { result } = renderHook(() => useListings({ q: 'python developer' }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
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
            q: 'python developer',
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
