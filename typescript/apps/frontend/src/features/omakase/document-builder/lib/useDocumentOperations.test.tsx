import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

const { mockAwaitDocumentReady, mockLoggerInfo, mockPost } = vi.hoisted(() => ({
  mockAwaitDocumentReady: vi.fn(),
  mockLoggerInfo: vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock('@/entities/document', () => ({ awaitDocumentReady: mockAwaitDocumentReady }));
vi.mock('@/shared/api/index.ts', () => ({ fetchClient: { POST: mockPost } }));
vi.mock('@/shared/lib/index.ts', () => ({ logger: { info: mockLoggerInfo } }));
vi.mock('../api/hooks.ts', () => ({
  useDownloadDocument: () => ({ isPending: false, mutateAsync: vi.fn() }),
}));

import { useDocumentOperations } from './useDocumentOperations.ts';

function wrapper({ children }: { children: ReactNode }): JSX.Element {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('useDocumentOperations generated URL safety', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPost.mockResolvedValue({ data: { request_id: 'req-1' }, error: undefined });
  });

  test('fetches HTML only after readiness returns a valid HTTPS URL', async () => {
    mockAwaitDocumentReady.mockResolvedValue({
      downloadUrl: 'https://storage.example.com/rendered/doc.html',
      status: 'completed',
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('<p>safe</p>'),
    });
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useDocumentOperations(), { wrapper });

    await expect(
      act(() => result.current.generateHtml({ template_version_id: 'tpl-1', data: {} })),
    ).resolves.toBe('<p>safe</p>');
    expect(fetchMock).toHaveBeenCalledWith('https://storage.example.com/rendered/doc.html');
    vi.unstubAllGlobals();
  });

  test('rejects an unsuccessful generated HTML response without reading its body', async () => {
    mockAwaitDocumentReady.mockResolvedValue({
      downloadUrl: 'https://storage.example.com/rendered/doc.html',
      status: 'completed',
    });
    const text = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, text }));
    const { result } = renderHook(() => useDocumentOperations(), { wrapper });

    await expect(
      act(() => result.current.generateHtml({ template_version_id: 'tpl-1', data: {} })),
    ).rejects.toThrow('Generated document fetch failed with status 502');
    expect(text).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  test.each([
    'javascript:',
    'data:',
    'credentialed',
    'protocol-relative',
    'malformed',
    'unavailable',
  ])('does not fetch when readiness rejects a %s generated URL', async () => {
    mockAwaitDocumentReady.mockRejectedValue(new Error('Document generation failed'));
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useDocumentOperations(), { wrapper });

    await expect(
      act(() => result.current.generateHtml({ template_version_id: 'tpl-1', data: {} })),
    ).rejects.toThrow('Document generation failed');
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
  test('does not log a generated image download URL or its SAS query', async () => {
    const downloadUrl =
      'https://storage.example.com/rendered/preview.png?sv=2026-01-01&sig=private-signature';
    mockAwaitDocumentReady.mockResolvedValue({ downloadUrl, status: 'completed' });
    const { result } = renderHook(() => useDocumentOperations(), { wrapper });

    await expect(
      act(() => result.current.generateImage({ template_version_id: 'tpl-1', data: {} })),
    ).resolves.toBe(downloadUrl);

    expect(JSON.stringify(mockLoggerInfo.mock.calls)).not.toContain(downloadUrl);
    expect(JSON.stringify(mockLoggerInfo.mock.calls)).not.toContain('private-signature');
  });
});
