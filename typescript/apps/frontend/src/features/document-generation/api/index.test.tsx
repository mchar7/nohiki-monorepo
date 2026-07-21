import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useDocuments, useGenerateDocument, useGenerateTailoredDocument } from './index.ts';

const {
  mockGet,
  mockPost,
}: {
  mockGet: ReturnType<typeof vi.fn>;
  mockPost: ReturnType<typeof vi.fn>;
} = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock('@/shared/api/client', async () => {
  const { default: createQueryClient } =
    await vi.importActual<typeof import('openapi-react-query')>('openapi-react-query');
  const client = {
    GET: mockGet,
    POST: mockPost,
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

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function createWrapper(): ({ children }: { children: ReactNode }) => JSX.Element {
  const queryClient = createTestQueryClient();
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe('useDocuments', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches documents with default params', async () => {
    const mockDocuments = {
      items: [{ id: '1' }],
      total: 1,
      page: 1,
      page_size: 20,
      total_pages: 1,
      has_next: false,
      has_prev: false,
    };
    mockGet.mockResolvedValue(mockFetchResponse(mockDocuments));

    const { result } = renderHook(() => useDocuments(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(mockGet).toHaveBeenCalledWith(
      '/api/v1/documents',
      expect.objectContaining({
        params: { query: { page: 1, page_size: 20 } },
      }),
    );
    expect(result.current.data).toEqual(mockDocuments);
  });

  test('fetches documents with custom params', async () => {
    const mockDocuments = {
      items: [],
      total: 0,
      page: 2,
      page_size: 10,
      total_pages: 0,
      has_next: false,
      has_prev: false,
    };
    mockGet.mockResolvedValue(mockFetchResponse(mockDocuments));

    const { result } = renderHook(() => useDocuments(2, 10), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(mockGet).toHaveBeenCalledWith(
      '/api/v1/documents',
      expect.objectContaining({
        params: { query: { page: 2, page_size: 10 } },
      }),
    );
  });
});

describe('useGenerateDocument', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls generate document API', async () => {
    const mockResponse = { request_id: 'req-456' };
    mockPost.mockResolvedValue(mockFetchResponse(mockResponse));

    const { result } = renderHook(() => useGenerateDocument(), { wrapper: createWrapper() });

    const response = await result.current.mutateAsync({
      body: {
        template_version_id: 'tpl-123',
        data: { name: 'Test' },
        output_format: 'pdf',
      },
    });

    expect(mockPost).toHaveBeenCalledWith(
      '/api/v1/documents/generate',
      expect.objectContaining({
        body: {
          template_version_id: 'tpl-123',
          data: { name: 'Test' },
          output_format: 'pdf',
        },
      }),
    );
    expect(response).toEqual(mockResponse);
  });

  test('handles generation error', async () => {
    mockPost.mockRejectedValue(new Error('Generation failed'));

    const { result } = renderHook(() => useGenerateDocument(), { wrapper: createWrapper() });

    await expect(
      result.current.mutateAsync({
        body: {
          template_version_id: 'tpl-123',
          data: {},
          output_format: 'pdf',
        },
      }),
    ).rejects.toThrow('Generation failed');
  });
});

describe('useGenerateTailoredDocument', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('posts the exact tailored request and invalidates document queries on acceptance', async () => {
    const mockResponse = { request_id: 'request-tailored', status: 'accepted' };
    mockPost.mockResolvedValue(mockFetchResponse(mockResponse));
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const wrapper = ({ children }: { children: ReactNode }): JSX.Element => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useGenerateTailoredDocument(), { wrapper });

    const response = await result.current.mutateAsync({
      body: {
        job_correlation_id: 'correlation-42',
        template_id: 'family-modern',
        output_format: 'png',
      },
    });

    expect(mockPost).toHaveBeenCalledWith(
      '/api/v1/documents/generate-tailored',
      expect.objectContaining({
        body: {
          job_correlation_id: 'correlation-42',
          template_id: 'family-modern',
          output_format: 'png',
        },
      }),
    );
    expect(response).toEqual(mockResponse);
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledOnce());
    const invalidationFilters = invalidateSpy.mock.calls[0]?.[0];
    expect(
      invalidationFilters?.predicate?.({ queryKey: ['get', '/api/v1/documents'] } as never),
    ).toBe(true);
    expect(
      invalidationFilters?.predicate?.({ queryKey: ['get', '/api/v1/profiles'] } as never),
    ).toBe(false);
  });
});
