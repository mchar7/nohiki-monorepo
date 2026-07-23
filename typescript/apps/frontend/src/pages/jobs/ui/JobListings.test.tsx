import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type RenderResult, render } from '@testing-library/react';
import type { JSX, RefObject } from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { JobListingResponse } from '@/shared/api';
import { nonNull } from '@/shared/test-utils';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { JobListings } from './JobListings.tsx';

// --- Mock data-fetching hooks ---

const mockJobListingsGrid =
  vi.fn<(props: { listings: readonly JobListingResponse[] }) => JSX.Element>();
const mockRefetch = vi.fn();

const mockUseListings = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  data: { items: [], total: 0 },
  isLoading: false,
  isFetching: false,
  dataUpdatedAt: Date.now(),
  error: null,
  refetch: mockRefetch,
});

const mockUseJobListingsFilters = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  filters: {
    page: 1,
    sort: 'posted_at',
    dir: 'desc',
    source: null,
    q: null,
    company: null,
    showDismissed: false,
    hasSalary: false,
    workArrangement: null,
    seniority: null,
    dateRange: null,
  },
  setPage: vi.fn(),
  setSortField: vi.fn(),
  setSortDirection: vi.fn(),
  setSource: vi.fn(),
  setCompany: vi.fn(),
  setQuery: vi.fn(),
  setShowDismissed: vi.fn(),
  setHasSalary: vi.fn(),
  setWorkArrangement: vi.fn(),
  setSeniority: vi.fn(),
  setDateRange: vi.fn(),
  clearFilters: vi.fn(),
  hasActiveFilters: false,
  activeFilterCount: 0,
});

vi.mock('@/features/job-search/index.ts', () => ({
  useListings: (...args: unknown[]) => mockUseListings(...args),
  useJobListingsFilters: (...args: unknown[]) => mockUseJobListingsFilters(...args),
  JobListingsFiltersBar: () => <div data-testid="filters-bar" />,
  JobListingsGrid: (props: { listings: readonly JobListingResponse[] }) => {
    mockJobListingsGrid(props);
    return <div data-testid="listings-grid" />;
  },
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

async function renderJobListings(): Promise<RenderResult> {
  const queryClient = createTestQueryClient();
  return render(
    await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <JobListings />
        </I18nextProvider>
      </QueryClientProvider>,
    ),
  );
}

// --- Tests ---

describe('JobListings pull-to-refresh wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseListings.mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      error: null,
      refetch: mockRefetch,
    });
    mockUsePullToRefresh.mockReturnValue({
      pullDistance: 0,
      isRefreshing: false,
    });
  });

  test('calls usePullToRefresh with mainScrollRef, refetch, and isMobile guard', async () => {
    await renderJobListings();

    expect(mockUsePullToRefresh).toHaveBeenCalledWith({
      ref: mockScrollRef,
      onRefresh: mockRefetch,
      enabled: expect.any(Boolean),
    });
  });

  test('renders PullIndicator when hook reports active pull state', async () => {
    mockUsePullToRefresh.mockReturnValue({ pullDistance: 45, isRefreshing: false });

    const { container } = await renderJobListings();

    const indicator = container.querySelector('div.justify-center.py-2[aria-hidden="true"]');
    expect(indicator).toBeInTheDocument();
  });

  test('hides PullIndicator when hook reports idle state', async () => {
    mockUsePullToRefresh.mockReturnValue({ pullDistance: 0, isRefreshing: false });

    const { container } = await renderJobListings();

    const indicator = container.querySelector('div.justify-center.py-2[aria-hidden="true"]');
    expect(indicator).not.toBeInTheDocument();
  });

  test('wires onRefresh to useListings refetch', async () => {
    await renderJobListings();

    const hookArgs = nonNull(mockUsePullToRefresh.mock.calls[0])[0] as { onRefresh: () => void };
    hookArgs.onRefresh();

    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });
});

describe('JobListings server-owned page results', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('passes the API page through without local filtering or re-sorting', async () => {
    const items = [{ id: 'page-two-first' }, { id: 'page-two-second' }] as JobListingResponse[];
    mockUseListings.mockReturnValue({
      data: { items, total: 12 },
      isLoading: false,
      isFetching: false,
      dataUpdatedAt: 1,
      error: null,
      refetch: mockRefetch,
    });
    mockUseJobListingsFilters.mockReturnValue({
      filters: {
        page: 2,
        sort: 'match_score',
        dir: 'desc',
        source: 'linkedin',
        company: null,
        q: 'python',
        showDismissed: false,
        hasSalary: true,
        workArrangement: null,
        seniority: null,
        dateRange: null,
      },
      setPage: vi.fn(),
      setSortField: vi.fn(),
      setSortDirection: vi.fn(),
      setSource: vi.fn(),
      setCompany: vi.fn(),
      setQuery: vi.fn(),
      setShowDismissed: vi.fn(),
      setHasSalary: vi.fn(),
      setWorkArrangement: vi.fn(),
      setSeniority: vi.fn(),
      setDateRange: vi.fn(),
      clearFilters: vi.fn(),
      hasActiveFilters: true,
      activeFilterCount: 3,
    });

    await renderJobListings();

    expect(mockJobListingsGrid).toHaveBeenLastCalledWith(
      expect.objectContaining({ listings: items }),
    );
  });
});
