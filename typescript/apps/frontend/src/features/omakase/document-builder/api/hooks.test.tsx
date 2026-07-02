import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

const { mockAwaitDocumentReady, mockPost } = vi.hoisted(() => ({
  mockAwaitDocumentReady: vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock('@/entities/document', () => ({ awaitDocumentReady: mockAwaitDocumentReady }));
vi.mock('@/shared/api/index.ts', () => ({
  $api: { queryOptions: vi.fn(), useQuery: vi.fn(), useMutation: vi.fn() },
  CACHE_CONFIG: { STATIC: { staleTime: 0, gcTime: 0 } },
  fetchClient: { POST: mockPost },
}));

import { useDownloadDocument } from './hooks.ts';

function wrapper({ children }: { children: ReactNode }): JSX.Element {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const request = { template_version_id: 'tpl-1', data: {}, output_format: 'pdf' as const };

describe('useDownloadDocument generated URL safety', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPost.mockResolvedValue({ data: { request_id: 'req-1' }, error: undefined });
  });

  test('downloads only after readiness returns a valid HTTPS URL', async () => {
    mockAwaitDocumentReady.mockResolvedValue({
      downloadUrl: 'https://storage.example.com/rendered/doc.pdf',
      status: 'completed',
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob(['pdf'])),
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const { result } = renderHook(() => useDownloadDocument(), { wrapper });

    await act(() => result.current.mutateAsync(request));
    expect(fetchMock).toHaveBeenCalledWith('https://storage.example.com/rendered/doc.pdf');
    vi.unstubAllGlobals();
  });

  test('rejects an unsuccessful artifact response before creating a browser download', async () => {
    mockAwaitDocumentReady.mockResolvedValue({
      downloadUrl: 'https://storage.example.com/rendered/doc.pdf',
      status: 'completed',
    });
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 503 });
    vi.stubGlobal('fetch', fetchMock);
    const createObjectURL = vi.spyOn(URL, 'createObjectURL');
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click');
    const { result } = renderHook(() => useDownloadDocument(), { wrapper });

    await expect(act(() => result.current.mutateAsync(request))).rejects.toThrow(
      'Document download failed with status 503',
    );
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  test.each([
    'javascript:',
    'data:',
    'credentialed',
    'protocol-relative',
    'malformed',
    'unavailable',
  ])('does not fetch or create a download when readiness rejects a %s generated URL', async () => {
    mockAwaitDocumentReady.mockRejectedValue(new Error('Document generation failed'));
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click');
    const { result } = renderHook(() => useDownloadDocument(), { wrapper });

    await expect(act(() => result.current.mutateAsync(request))).rejects.toThrow(
      'Document generation failed',
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
