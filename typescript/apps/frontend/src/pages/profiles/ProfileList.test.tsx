import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type RenderResult, render, screen } from '@testing-library/react';
import type { RefObject } from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import type * as ProfileManagement from '@/features/profile-management/index.ts';
import type * as SharedApi from '@/shared/api';
import { nonNull } from '@/shared/test-utils';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { ProfileList } from './ProfileList.tsx';

// --- Mock data-fetching hooks ---

const mockRefetch = vi.fn<() => void>();

const mockUseProfiles = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  data: { items: [], total: 0 },
  isLoading: false,
  isFetching: false,
  dataUpdatedAt: Date.now(),
  error: null,
  refetch: mockRefetch,
});

vi.mock('@/features/profile-management/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof ProfileManagement>();
  return {
    ...actual,
    useProfiles: (...args: unknown[]) => mockUseProfiles(...args),
  };
});

const mockUseSkillBatch = vi.fn<(...args: unknown[]) => unknown>().mockReturnValue({
  data: { skills: [] },
  isLoading: false,
  error: null,
});

vi.mock('@/shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof SharedApi>();
  return {
    ...actual,
    useSkillBatch: (...args: unknown[]) => mockUseSkillBatch(...args),
  };
});

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

async function renderProfileList(): Promise<RenderResult> {
  const queryClient = createTestQueryClient();
  return render(
    await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <ProfileList />
        </I18nextProvider>
      </QueryClientProvider>,
    ),
  );
}

// --- Tests ---

describe('ProfileList pull-to-refresh wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseProfiles.mockReturnValue({
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
    await renderProfileList();

    expect(mockUsePullToRefresh).toHaveBeenCalledWith({
      ref: mockScrollRef,
      onRefresh: mockRefetch,
      enabled: expect.any(Boolean),
    });
  });

  test('renders PullIndicator when hook reports active pull state', async () => {
    mockUsePullToRefresh.mockReturnValue({ pullDistance: 45, isRefreshing: false });

    const { container } = await renderProfileList();

    const indicator = container.querySelector('div.justify-center.py-2[aria-hidden="true"]');
    expect(indicator).toBeInTheDocument();
  });

  test('hides PullIndicator when hook reports idle state', async () => {
    mockUsePullToRefresh.mockReturnValue({ pullDistance: 0, isRefreshing: false });

    const { container } = await renderProfileList();

    const indicator = container.querySelector('div.justify-center.py-2[aria-hidden="true"]');
    expect(indicator).not.toBeInTheDocument();
  });

  test('wires onRefresh to useProfiles refetch', async () => {
    await renderProfileList();

    const hookArgs = nonNull(mockUsePullToRefresh.mock.calls[0])[0] as { onRefresh: () => void };
    hookArgs.onRefresh();

    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });
});

describe('ProfileList search terms', () => {
  test('renders human search terms literally without skill hydration', async () => {
    mockUseSkillBatch.mockClear();
    mockUseProfiles.mockReturnValue({
      data: {
        items: [
          {
            id: 'profile-1',
            user_id: 'user-1',
            pref_name: 'Backend Engineer',
            search_keywords: ['backend engineer', 'distributed systems'],
            user_skills: [],
            disallowed_keywords: [],
            work_arrangements: [],
            notification_threshold: 0.7,
            auto_tailor_threshold: null,
            open_to_relocation: false,
          },
        ],
        total: 1,
      },
      isLoading: false,
      isFetching: false,
      dataUpdatedAt: Date.now(),
      error: null,
      refetch: mockRefetch,
    });

    await renderProfileList();

    expect(screen.getByText('backend engineer')).toBeInTheDocument();
    expect(screen.getByText('distributed systems')).toBeInTheDocument();
    expect(mockUseSkillBatch).not.toHaveBeenCalled();
  });
});
