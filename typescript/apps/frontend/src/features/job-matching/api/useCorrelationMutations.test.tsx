import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { JobCorrelationResponse } from '@/shared/api';
import {
  correlationDetailQueryOptions,
  correlationsQueryOptions,
  useAdjustScore,
  useRecordFeedback,
  useScoreFeedback,
} from './index.ts';

const { mockPost }: { mockPost: ReturnType<typeof vi.fn> } = vi.hoisted(() => ({
  mockPost: vi.fn(),
}));

vi.mock('@/shared/api/client', async () => {
  const { default: createQueryClient } = await import('openapi-react-query');
  const fakeFetchClient = {
    GET: vi.fn(),
    POST: mockPost,
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

function createHarness(): {
  queryClient: QueryClient;
  wrapper: ({ children }: { children: ReactNode }) => JSX.Element;
} {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    queryClient,
    wrapper: ({ children }: { children: ReactNode }): JSX.Element => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  };
}

const correlation: JobCorrelationResponse = {
  id: 'corr-123',
  listing_id: 'listing-1',
  pref_id: 'pref-1',
  fit_score: 85,
  listing_title: 'Engineer',
  listing_company: 'Example',
  listing_location: 'Remote',
  listing_url: 'https://example.com/job',
  status: 'PENDING',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  score_breakdown: {},
};

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('useRecordFeedback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test.each([
    'SAVED',
    'APPLIED',
    'DISMISSED',
  ] as const)('sends the exact %s feedback payload', async (feedbackType) => {
    mockPost.mockResolvedValue({ data: { request_id: 'test-request-id' }, error: undefined });
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useRecordFeedback(), { wrapper });

    await act(() =>
      result.current.mutateAsync({
        params: { path: { correlation_id: 'corr-123' } },
        body: { feedback_type: feedbackType },
      }),
    );

    expect(mockPost).toHaveBeenCalledWith('/api/v1/correlations/{correlation_id}/feedback', {
      params: { path: { correlation_id: 'corr-123' } },
      body: { feedback_type: feedbackType },
    });
  });

  test('optimistically updates the exact detail and every list cache, then reconciles them', async () => {
    const request = deferred<{ data: { request_id: string }; error: undefined }>();
    mockPost.mockReturnValue(request.promise);
    const { queryClient, wrapper } = createHarness();
    const detailKey = correlationDetailQueryOptions(correlation.id).queryKey;
    const firstListKey = correlationsQueryOptions().queryKey;
    const filteredListKey = correlationsQueryOptions({ prefId: 'pref-1', page: 2 }).queryKey;
    queryClient.setQueryData(detailKey, correlation);
    queryClient.setQueryData(firstListKey, {
      items: [correlation],
      total: 1,
      page: 1,
      page_size: 20,
    });
    queryClient.setQueryData(filteredListKey, {
      items: [correlation],
      total: 1,
      page: 2,
      page_size: 20,
    });
    const { result } = renderHook(() => useRecordFeedback(), { wrapper });

    act(() =>
      result.current.mutate({
        params: { path: { correlation_id: correlation.id } },
        body: { feedback_type: 'APPLIED' },
      }),
    );

    await waitFor(() => {
      expect(queryClient.getQueryData<JobCorrelationResponse>(detailKey)?.status).toBe('APPLIED');
      expect(
        queryClient.getQueryData<{ items: JobCorrelationResponse[] }>(firstListKey)?.items[0]
          ?.status,
      ).toBe('APPLIED');
      expect(
        queryClient.getQueryData<{ items: JobCorrelationResponse[] }>(filteredListKey)?.items[0]
          ?.status,
      ).toBe('APPLIED');
    });

    request.resolve({ data: { request_id: 'request-1' }, error: undefined });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(firstListKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(filteredListKey)?.isInvalidated).toBe(true);
  });

  test('rolls back detail and list caches when feedback recording fails', async () => {
    const request = deferred<never>();
    mockPost.mockReturnValue(request.promise);
    const { queryClient, wrapper } = createHarness();
    const detailKey = correlationDetailQueryOptions(correlation.id).queryKey;
    const listKey = correlationsQueryOptions().queryKey;
    queryClient.setQueryData(detailKey, correlation);
    queryClient.setQueryData(listKey, { items: [correlation], total: 1, page: 1, page_size: 20 });
    const { result } = renderHook(() => useRecordFeedback(), { wrapper });

    act(() =>
      result.current.mutate({
        params: { path: { correlation_id: correlation.id } },
        body: { feedback_type: 'SAVED' },
      }),
    );
    await waitFor(() =>
      expect(queryClient.getQueryData<JobCorrelationResponse>(detailKey)?.status).toBe('SAVED'),
    );
    request.reject(new Error('network failure'));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(queryClient.getQueryData<JobCorrelationResponse>(detailKey)).toEqual(correlation);
    expect(
      queryClient.getQueryData<{ items: JobCorrelationResponse[] }>(listKey)?.items[0],
    ).toEqual(correlation);
    expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true);
  });
});

describe('useScoreFeedback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls score feedback API', async () => {
    mockPost.mockResolvedValue({
      data: { request_id: 'test-request-id' },
      error: undefined,
    });

    const { result } = renderHook(() => useScoreFeedback(), { wrapper: createHarness().wrapper });

    await result.current.mutateAsync({
      params: { path: { correlation_id: 'corr-123' } },
      body: { feedback_type: 'GOOD' as const },
    });

    expect(mockPost).toHaveBeenCalledWith('/api/v1/correlations/{correlation_id}/score-feedback', {
      params: { path: { correlation_id: 'corr-123' } },
      body: { feedback_type: 'GOOD' as const },
    });
  });
});

describe('useAdjustScore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls score adjustment API', async () => {
    mockPost.mockResolvedValue({
      data: { request_id: 'test-request-id' },
      error: undefined,
    });

    const { result } = renderHook(() => useAdjustScore(), { wrapper: createHarness().wrapper });

    await result.current.mutateAsync({
      params: { path: { correlation_id: 'corr-123' } },
      body: { adjusted_score: 0.1, reasoning: 'test' },
    });

    expect(mockPost).toHaveBeenCalledWith('/api/v1/correlations/{correlation_id}/adjust-score', {
      params: { path: { correlation_id: 'corr-123' } },
      body: { adjusted_score: 0.1, reasoning: 'test' },
    });
  });
});
