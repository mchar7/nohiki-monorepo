import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { SEARCH_MAX_RESULTS_PER_GROUP, SEARCH_MIN_QUERY_LENGTH } from '../lib/constants.ts';
import { useGlobalSearch } from './useGlobalSearch.ts';

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
    $api: createQueryClient(client as unknown as Parameters<typeof createQueryClient>[0]),
    createDevClient: vi.fn(),
  };
});

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

interface MockListing {
  id: string;
  title: string;
  company_name: string;
  listing_url: string;
  source: string;
  required_skills: string[];
  discovered_at: string;
  created_at: string;
}

interface MockListingsResponse {
  items: MockListing[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

interface MockSkillsResponse {
  skills: { id: string; name: string; display_name: string; category: string }[];
  total: number;
  query: string;
}

const MOCK_LISTING: MockListing = {
  id: 'listing-1',
  title: 'Software Engineer',
  company_name: 'Acme Corp',
  listing_url: 'https://example.com',
  source: 'linkedin',
  required_skills: [],
  discovered_at: '2025-01-01',
  created_at: '2025-01-01',
};

const MOCK_LISTINGS: MockListingsResponse = {
  items: [MOCK_LISTING],
  total: 1,
  page: 1,
  page_size: SEARCH_MAX_RESULTS_PER_GROUP,
  total_pages: 1,
  has_next: false,
  has_prev: false,
};

const MOCK_SKILLS: MockSkillsResponse = {
  skills: [{ id: 'skill-1', name: 'typescript', display_name: 'TypeScript', category: 'Language' }],
  total: 1,
  query: 'type',
};

function setupBothEndpoints(): void {
  mockGet
    .mockResolvedValueOnce(mockFetchResponse(MOCK_LISTINGS))
    .mockResolvedValueOnce(mockFetchResponse(MOCK_SKILLS));
}

describe('useGlobalSearch - short queries', () => {
  beforeEach(() => vi.clearAllMocks());

  test('returns empty groups when query is shorter than minimum length', () => {
    const { result } = renderHook(() => useGlobalSearch('a'), { wrapper: createWrapper() });
    expect(nonNull(result.current.groups[0]).results).toHaveLength(0);
    expect(nonNull(result.current.groups[1]).results).toHaveLength(0);
    expect(result.current.isSearching).toBe(false);
    expect(mockGet).not.toHaveBeenCalled();
  });

  test('does not fire queries at minimum minus one', () => {
    const shortQuery = 'a'.repeat(SEARCH_MIN_QUERY_LENGTH - 1);
    const { result } = renderHook(() => useGlobalSearch(shortQuery), {
      wrapper: createWrapper(),
    });
    expect(result.current.hasResults).toBe(false);
    expect(mockGet).not.toHaveBeenCalled();
  });
});

describe('useGlobalSearch - query execution', () => {
  beforeEach(() => vi.clearAllMocks());

  test('fires parallel queries for listings and skills', async () => {
    setupBothEndpoints();
    renderHook(() => useGlobalSearch('test'), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));

    expect(mockGet).toHaveBeenCalledWith(
      '/api/v1/listings',
      expect.objectContaining({
        params: { query: { q: 'test', page_size: SEARCH_MAX_RESULTS_PER_GROUP } },
      }),
    );
    expect(mockGet).toHaveBeenCalledWith(
      '/api/v1/skills/search',
      expect.objectContaining({
        params: { query: { q: 'test', limit: SEARCH_MAX_RESULTS_PER_GROUP } },
      }),
    );
  });

  test('sends page_size to cap results', async () => {
    setupBothEndpoints();
    renderHook(() => useGlobalSearch('test'), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(mockGet).toHaveBeenCalledWith(
      '/api/v1/listings',
      expect.objectContaining({
        params: { query: { q: 'test', page_size: SEARCH_MAX_RESULTS_PER_GROUP } },
      }),
    );
  });
});

describe('useGlobalSearch - result mapping', () => {
  beforeEach(() => vi.clearAllMocks());

  test('maps listing response with correct href', async () => {
    setupBothEndpoints();
    const { result } = renderHook(() => useGlobalSearch('test'), { wrapper: createWrapper() });

    await waitFor(() => expect(nonNull(result.current.groups[0]).results).toHaveLength(1));

    expect(nonNull(result.current.groups[0]).results[0]).toEqual({
      type: 'listing',
      id: 'listing-1',
      title: 'Software Engineer',
      subtitle: 'Acme Corp',
      href: '/jobs/listing-1',
    });
  });

  test('maps skill response correctly', async () => {
    setupBothEndpoints();
    const { result } = renderHook(() => useGlobalSearch('type'), { wrapper: createWrapper() });

    await waitFor(() => expect(nonNull(result.current.groups[1]).results).toHaveLength(1));

    expect(nonNull(result.current.groups[1]).results[0]).toEqual({
      type: 'skill',
      id: 'skill-1',
      title: 'TypeScript',
      subtitle: 'Language',
      href: '',
    });
  });
});

describe('useGlobalSearch - loading and error states', () => {
  beforeEach(() => vi.clearAllMocks());

  test('returns isSearching true while fetching', async () => {
    mockGet.mockReturnValue(
      new Promise(() => {
        /* intentionally pending */
      }),
    );
    const { result } = renderHook(() => useGlobalSearch('test'), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSearching).toBe(true));
    expect(nonNull(result.current.groups[0]).isLoading).toBe(true);
    expect(nonNull(result.current.groups[1]).isLoading).toBe(true);
  });

  test('returns isError true per group on failure', async () => {
    mockGet.mockRejectedValue(new Error('Network error'));
    const { result } = renderHook(() => useGlobalSearch('test'), { wrapper: createWrapper() });

    await waitFor(() => expect(nonNull(result.current.groups[0]).isError).toBe(true));
    expect(nonNull(result.current.groups[1]).isError).toBe(true);
  });
});
