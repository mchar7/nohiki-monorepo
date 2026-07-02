import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type {
  PaginatedResponseProfileResponse,
  ResolvedFeatureImportanceResponse,
} from '@/shared/api';
import { useProfile, useProfiles, useResolvedFeatureImportance } from './index.ts';

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
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe('useProfiles', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches profiles list', async () => {
    const mockProfiles: PaginatedResponseProfileResponse = {
      items: [
        {
          id: '1',
          user_id: 'user-1',
          pref_name: 'Profile 1',
          search_keywords: ['python'],
          disallowed_keywords: [],
          work_arrangements: ['REMOTE'],
          notification_threshold: 0.7,
          auto_tailor_threshold: null,
          open_to_relocation: false,
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
      total_pages: 1,
      has_next: false,
      has_prev: false,
    };
    mockGet.mockResolvedValue(mockFetchResponse(mockProfiles));

    const { result } = renderHook(() => useProfiles(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(mockProfiles);
  });
});

describe('useProfile', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches single profile', async () => {
    const mockProfile = {
      id: 'prof-123',
      user_id: 'user-1',
      pref_name: 'Test Profile',
      search_keywords: ['python', 'fastapi'],
      disallowed_keywords: [],
      work_arrangements: ['REMOTE' as const],
      notification_threshold: 0.7,
      auto_tailor_threshold: null,
      open_to_relocation: false,
    };
    mockGet.mockResolvedValue(mockFetchResponse(mockProfile));

    const { result } = renderHook(() => useProfile('prof-123'), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(mockProfile);
  });

  test('does not fetch when profileId is empty', () => {
    renderHook(() => useProfile(''), { wrapper: createWrapper() });

    expect(mockGet).not.toHaveBeenCalled();
  });
});

describe('useResolvedFeatureImportance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches resolved feature importance', async () => {
    const mockImportance: ResolvedFeatureImportanceResponse = {
      skill_match_importance: 80,
      location_importance: 50,
      work_arrangement_importance: 70,
      experience_importance: 60,
      salary_importance: 90,
      recency_importance: 40,
      source: 'user_default',
    };
    mockGet.mockResolvedValue(mockFetchResponse(mockImportance));

    const { result } = renderHook(() => useResolvedFeatureImportance('prof-123'), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(mockImportance);
  });
});
