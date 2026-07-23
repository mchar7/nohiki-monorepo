import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type RenderResult, render } from '@testing-library/react';
import type { RefObject } from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { MyMatches } from './MyMatches.tsx';

// --- Mock data-fetching hooks ---

const mockRefetchCorrelations = vi.fn();

const mockUseMyCorrelations = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  data: { items: [], total: 0 },
  isLoading: false,
  isFetching: false,
  dataUpdatedAt: Date.now(),
  error: null,
  refetch: mockRefetchCorrelations,
});

const mockUseMatchesFilters = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  filters: { page: 1, prefId: null, minScore: null },
  setPrefId: vi.fn(),
  setMinScore: vi.fn(),
  clearFilters: vi.fn(),
  hasActiveFilters: false,
  activeFilterCount: 0,
});

vi.mock('@/features/job-matching/index.ts', () => ({
  useMyCorrelations: (...args: unknown[]) => mockUseMyCorrelations(...args),
  useMatchesFilters: (...args: unknown[]) => mockUseMatchesFilters(...args),
  useRecordFeedback: () => ({ mutate: vi.fn(), isPending: false }),
  useScoreFeedback: () => ({ mutateAsync: vi.fn() }),
  MatchesDataTable: () => <div data-testid="matches-table" />,
  MatchesFiltersBar: () => <div data-testid="matches-filters" />,
  MatchesStatsCards: () => <div data-testid="matches-stats" />,
  MatchingMethodologyInfo: () => <div data-testid="matching-methodology-info" />,
}));

vi.mock('@/features/profile-management/index.ts', () => ({
  useProfiles: () => ({ data: { items: [] }, isLoading: false }),
}));

// --- Mock usePullToRefresh ---

const mockUsePullToRefresh = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  pullDistance: 0,
  isRefreshing: false,
});

vi.mock('@/shared/lib/hooks/usePullToRefresh.ts', () => ({
  usePullToRefresh: (...args: unknown[]) => mockUsePullToRefresh(...args),
  PULL_THRESHOLD_PX: 60,
}));

// --- Mock useMainScrollRef (requires context provider otherwise) ---

const mockScrollRef: RefObject<HTMLElement | null> = { current: document.createElement('div') };

vi.mock('@/shared/lib/contexts/MainScrollRefContext.ts', () => ({
  useMainScrollRef: () => mockScrollRef,
}));

// --- Helpers ---

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

async function renderMyMatches(): Promise<RenderResult> {
  const queryClient = createTestQueryClient();
  return render(
    await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <MyMatches />
        </I18nextProvider>
      </QueryClientProvider>,
    ),
  );
}

// --- Tests ---

describe('MyMatches pull-to-refresh wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseMyCorrelations.mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      error: null,
      refetch: mockRefetchCorrelations,
    });
    mockUsePullToRefresh.mockReturnValue({
      pullDistance: 0,
      isRefreshing: false,
    });
  });

  test('calls usePullToRefresh with mainScrollRef, refetchCorrelations, and isMobile guard', async () => {
    await renderMyMatches();

    expect(mockUsePullToRefresh).toHaveBeenCalledWith({
      ref: mockScrollRef,
      onRefresh: mockRefetchCorrelations,
      enabled: expect.any(Boolean),
    });
  });

  test('renders PullIndicator when hook reports active pull state', async () => {
    mockUsePullToRefresh.mockReturnValue({ pullDistance: 45, isRefreshing: false });

    const { container } = await renderMyMatches();

    const indicator = container.querySelector('div.justify-center.py-2[aria-hidden="true"]');
    expect(indicator).toBeInTheDocument();
  });

  test('hides PullIndicator when hook reports idle state', async () => {
    mockUsePullToRefresh.mockReturnValue({ pullDistance: 0, isRefreshing: false });

    const { container } = await renderMyMatches();

    const indicator = container.querySelector('div.justify-center.py-2[aria-hidden="true"]');
    expect(indicator).not.toBeInTheDocument();
  });

  test('wires onRefresh to useMyCorrelations refetch', async () => {
    await renderMyMatches();

    const hookArgs = nonNull(mockUsePullToRefresh.mock.calls[0])[0] as { onRefresh: () => void };
    hookArgs.onRefresh();

    expect(mockRefetchCorrelations).toHaveBeenCalledTimes(1);
  });
});
