import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import {
  useAttachment,
  useAttachments,
  useCompleteUpload,
  useDeleteAttachment,
  useInitiateUpload,
  useLinkAttachmentToProfile,
  useUnlinkAttachmentFromProfile,
} from './index.ts';

const {
  mockGet,
  mockPost,
  mockDelete,
}: {
  mockGet: ReturnType<typeof vi.fn>;
  mockPost: ReturnType<typeof vi.fn>;
  mockDelete: ReturnType<typeof vi.fn>;
} = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockDelete: vi.fn(),
}));

vi.mock('@/shared/api/client', async () => {
  const { default: createQueryClient } =
    await vi.importActual<typeof import('openapi-react-query')>('openapi-react-query');
  const client = {
    GET: mockGet,
    POST: mockPost,
    DELETE: mockDelete,
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

describe('useAttachments', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches attachments list', async () => {
    const mockAttachments = {
      items: [{ id: '1' }],
      total: 1,
      page: 1,
      page_size: 100,
      total_pages: 1,
      has_next: false,
      has_prev: false,
    };
    mockGet.mockResolvedValue(mockFetchResponse(mockAttachments));

    const { result } = renderHook(() => useAttachments(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(mockAttachments);
  });
});

describe('useAttachment', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches single attachment', async () => {
    const mockAttachment = { id: 'att-123', filename: 'test.pdf' };
    mockGet.mockResolvedValue(mockFetchResponse(mockAttachment));

    const { result } = renderHook(() => useAttachment('att-123'), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(mockAttachment);
  });

  test('does not fetch when uploadId is empty', () => {
    renderHook(() => useAttachment(''), { wrapper: createWrapper() });

    expect(mockGet).not.toHaveBeenCalled();
  });
});

describe('useInitiateUpload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('returns provider-required upload headers from the initiate API', async () => {
    mockPost.mockResolvedValue(
      mockFetchResponse({
        upload_id: 'upload-123',
        upload_url: 'https://example.com/upload',
        upload_headers: { 'x-ms-blob-type': 'BlockBlob' },
      }),
    );

    const { result } = renderHook(() => useInitiateUpload(), { wrapper: createWrapper() });

    const response = await result.current.mutateAsync({
      body: {
        filename: 'test.pdf',
        content_type: 'application/pdf',
        file_size: 1024,
      },
    });

    expect(response).toEqual({
      upload_id: 'upload-123',
      upload_url: 'https://example.com/upload',
      upload_headers: { 'x-ms-blob-type': 'BlockBlob' },
    });
    expect(mockPost).toHaveBeenCalledWith(
      '/api/v1/attachments/initiate',
      expect.objectContaining({
        body: {
          filename: 'test.pdf',
          content_type: 'application/pdf',
          file_size: 1024,
        },
      }),
    );
  });
});

describe('useCompleteUpload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls complete upload API', async () => {
    mockPost.mockResolvedValue(mockFetchResponse({}));

    const { result } = renderHook(() => useCompleteUpload(), { wrapper: createWrapper() });

    await result.current.mutateAsync({
      params: { path: { upload_id: 'upload-123' } },
      body: {
        filename: 'test.pdf',
        content_type: 'application/pdf',
        file_size: 1024,
      },
    });

    expect(mockPost).toHaveBeenCalledWith(
      '/api/v1/attachments/{upload_id}/complete',
      expect.objectContaining({
        params: { path: { upload_id: 'upload-123' } },
        body: {
          filename: 'test.pdf',
          content_type: 'application/pdf',
          file_size: 1024,
        },
      }),
    );
  });
});

describe('useDeleteAttachment', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls delete attachment API', async () => {
    mockDelete.mockResolvedValue(mockFetchResponse(undefined));

    const { result } = renderHook(() => useDeleteAttachment(), { wrapper: createWrapper() });

    await result.current.mutateAsync({
      params: { path: { upload_id: 'att-123' } },
    });

    expect(mockDelete).toHaveBeenCalledWith(
      '/api/v1/attachments/{upload_id}',
      expect.objectContaining({
        params: { path: { upload_id: 'att-123' } },
      }),
    );
  });
});

describe('useLinkAttachmentToProfile', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls POST to associate attachment with profile', async () => {
    mockPost.mockResolvedValue(mockFetchResponse({ request_id: 'req-1', status: 'accepted' }));

    const { result } = renderHook(() => useLinkAttachmentToProfile(), {
      wrapper: createWrapper(),
    });

    await result.current.mutateAsync({
      params: { path: { pref_id: 'pref-1', upload_id: 'upload-1' } },
    });

    expect(mockPost).toHaveBeenCalledWith(
      '/api/v1/profiles/{pref_id}/attachments/{upload_id}',
      expect.objectContaining({
        params: { path: { pref_id: 'pref-1', upload_id: 'upload-1' } },
      }),
    );
  });

  test('throws on API error', async () => {
    mockPost.mockResolvedValue({
      data: undefined,
      error: { detail: 'Not found' },
      response: { status: 404, headers: new Headers() },
    });

    const { result } = renderHook(() => useLinkAttachmentToProfile(), {
      wrapper: createWrapper(),
    });

    await expect(
      result.current.mutateAsync({
        params: { path: { pref_id: 'pref-1', upload_id: 'upload-1' } },
      }),
    ).rejects.toEqual({ detail: 'Not found' });
  });
});

describe('useUnlinkAttachmentFromProfile', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls DELETE to disassociate attachment from profile', async () => {
    mockDelete.mockResolvedValue(mockFetchResponse({ request_id: 'req-2', status: 'accepted' }));

    const { result } = renderHook(() => useUnlinkAttachmentFromProfile(), {
      wrapper: createWrapper(),
    });

    await result.current.mutateAsync({
      params: { path: { pref_id: 'pref-2', upload_id: 'upload-2' } },
    });

    expect(mockDelete).toHaveBeenCalledWith(
      '/api/v1/profiles/{pref_id}/attachments/{upload_id}',
      expect.objectContaining({
        params: { path: { pref_id: 'pref-2', upload_id: 'upload-2' } },
      }),
    );
  });

  test('throws on API error', async () => {
    mockDelete.mockResolvedValue({
      data: undefined,
      error: { detail: 'Server error' },
      response: { status: 500, headers: new Headers() },
    });

    const { result } = renderHook(() => useUnlinkAttachmentFromProfile(), {
      wrapper: createWrapper(),
    });

    await expect(
      result.current.mutateAsync({
        params: { path: { pref_id: 'pref-2', upload_id: 'upload-2' } },
      }),
    ).rejects.toEqual({ detail: 'Server error' });
  });
});
