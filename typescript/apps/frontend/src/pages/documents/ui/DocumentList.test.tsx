import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type RenderResult, render } from '@testing-library/react';
import type { RefObject } from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { DocumentList } from './DocumentList.tsx';

// Mock data-fetching hooks

const mockDocRefetch = vi.fn<() => void>();
const mockAttachRefetch = vi.fn<() => void>();

const mockUseDocuments = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  data: { items: [], total: 0 },
  isLoading: false,
  isFetching: false,
  dataUpdatedAt: Date.now(),
  error: null,
  refetch: mockDocRefetch,
});

const mockUseAttachments = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  data: { items: [], total: 0 },
  isLoading: false,
  isFetching: false,
  dataUpdatedAt: Date.now(),
  error: null,
  refetch: mockAttachRefetch,
});

vi.mock('@/features/document-generation/index.ts', () => ({
  useDocuments: (...args: unknown[]) => mockUseDocuments(...args),
}));

vi.mock('@/features/attachments/index.ts', () => ({
  useAttachments: (...args: unknown[]) => mockUseAttachments(...args),
  useFileUpload: () => ({
    isUploading: false,
    uploadProgress: 0,
    handleUpload: vi.fn(),
    lastUploadId: null,
  }),
  UploadDialog: () => <button type="button">Upload</button>,
}));

// Mock child components that aren't relevant to pull-to-refresh

vi.mock('./DocumentTabContent.tsx', () => ({
  AllTabContent: () => <div data-testid="all-tab" />,
  UploadedTabContent: () => <div data-testid="uploaded-tab" />,
  GeneratedTabContent: () => <div data-testid="generated-tab" />,
  PAGE_SIZE: 10,
}));

// Mock usePullToRefresh

const mockUsePullToRefresh = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  pullDistance: 0,
  isRefreshing: false,
});

vi.mock('@/shared/lib/hooks/usePullToRefresh.ts', () => ({
  usePullToRefresh: (...args: unknown[]) => mockUsePullToRefresh(...args),
  PULL_THRESHOLD_PX: 60,
}));

// Mock useMainScrollRef (requires context provider otherwise)

const mockScrollRef: RefObject<HTMLElement | null> = { current: document.createElement('div') };

vi.mock('@/shared/lib/contexts/MainScrollRefContext.ts', () => ({
  useMainScrollRef: () => mockScrollRef,
}));

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

async function renderDocumentList(): Promise<RenderResult> {
  const queryClient = createTestQueryClient();
  return render(
    await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <DocumentList />
        </I18nextProvider>
      </QueryClientProvider>,
    ),
  );
}

describe('DocumentList pull-to-refresh wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseDocuments.mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      error: null,
      refetch: mockDocRefetch,
    });
    mockUseAttachments.mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      error: null,
      refetch: mockAttachRefetch,
    });
    mockUsePullToRefresh.mockReturnValue({
      pullDistance: 0,
      isRefreshing: false,
    });
  });

  test('calls usePullToRefresh with mainScrollRef and isMobile guard', async () => {
    await renderDocumentList();

    expect(mockUsePullToRefresh).toHaveBeenCalledWith({
      ref: mockScrollRef,
      onRefresh: expect.any(Function),
      enabled: false,
    });
  });

  test('renders PullIndicator when hook reports active pull state', async () => {
    mockUsePullToRefresh.mockReturnValue({ pullDistance: 45, isRefreshing: false });
    const { container } = await renderDocumentList();

    const indicator = container.querySelector('div.justify-center.py-2[aria-hidden="true"]');
    expect(indicator).toBeInTheDocument();
  });

  test('hides PullIndicator when hook reports idle state', async () => {
    mockUsePullToRefresh.mockReturnValue({ pullDistance: 0, isRefreshing: false });
    const { container } = await renderDocumentList();

    const indicator = container.querySelector('div.justify-center.py-2[aria-hidden="true"]');
    expect(indicator).not.toBeInTheDocument();
  });

  test('wires onRefresh to call both refetch functions', async () => {
    await renderDocumentList();

    const hookArgs = nonNull(mockUsePullToRefresh.mock.calls[0])[0] as { onRefresh: () => void };
    hookArgs.onRefresh();

    expect(mockDocRefetch).toHaveBeenCalledTimes(1);
    expect(mockAttachRefetch).toHaveBeenCalledTimes(1);
  });
});
