import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type RenderResult, render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/setup.ts';
import { Dashboard } from './Dashboard.tsx';
import type { DashboardData } from './lib/useDashboardData.ts';

const SUBTITLE_PATTERN: RegExp = /welcome back|overview/iu;

// --- Mock data factories ---

function makeDefaultData(overrides: Partial<DashboardData> = {}): DashboardData {
  return {
    account: { display_name: 'Test User', first_name: 'Test' },
    profileCount: 2,
    correlationCount: 5,
    documentCount: 3,
    profiles: [{ id: 'prof-1', pref_name: 'Engineer', user_skills: ['ts'] }],
    correlations: [
      {
        id: 'cor-1',
        pref_id: 'pref-1',
        listing_id: 'listing-1',
        fit_score: 90,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        status: 'EVALUATED',
        score_breakdown: {},
        listing_title: 'Engineer',
        listing_company: 'Acme',
        listing_location: 'Remote',
        listing_url: 'https://example.com',
      },
    ] as DashboardData['correlations'],
    documents: [
      {
        request_id: 'doc-1',
        status: 'completed',
        created_at: new Date().toISOString(),
        download_url: null,
      },
    ],
    stats: { jobMatches: 5, profiles: 2, documents: 3, savedJobs: 1 },
    stage: 'active',
    topMatch: {
      id: 'cor-1',
      listing_title: 'Engineer',
      listing_company: 'Acme',
      listing_location: 'Remote',
      fit_score: 90,
    },
    latestDocument: { request_id: 'doc-1', status: 'completed', download_url: null },
    newMatchCount: 0,
    onboardingProgress: {
      completedSteps: 4,
      totalSteps: 4,
      nextStepLabel: 'Create Your Profile',
      nextStepRoute: '/profiles/new',
    },
    isLoading: false,
    ...overrides,
  };
}

// --- Mocks ---

const mockUseDashboardData: ReturnType<typeof vi.fn<() => DashboardData>> =
  vi.fn<() => DashboardData>();

vi.mock('./lib/index.ts', async (importOriginal) => {
  const original = await importOriginal<typeof import('./lib/index.ts')>();
  return {
    ...original,
    useDashboardData: () => mockUseDashboardData(),
  };
});

vi.mock('./ui/index.ts', () => ({
  DashboardSkeleton: () => <div data-testid="dashboard-skeleton">Skeleton</div>,
  OnboardingDashboard: () => <div data-testid="onboarding-dashboard">Onboarding</div>,
  OnboardingProgressStrip: () => <div data-testid="onboarding-progress-strip">Progress Strip</div>,
  ReturningUserDashboard: () => <div data-testid="returning-user-dashboard">Returning User</div>,
}));

// DashboardActivityChart is lazy-imported in ReturningUserDashboard (mocked above)
vi.mock('./ui/DashboardActivityChart.tsx', () => ({
  DashboardActivityChart: () => <div data-testid="activity-chart">Activity Chart</div>,
}));

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

async function renderDashboard(): Promise<RenderResult> {
  const queryClient = createTestQueryClient();
  return render(
    await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <Dashboard />
        </I18nextProvider>
      </QueryClientProvider>,
    ),
  );
}

describe('Dashboard orchestrator', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseDashboardData.mockReturnValue(makeDefaultData());
  });
  test('renders loading skeleton when data is loading', async () => {
    mockUseDashboardData.mockReturnValue(makeDefaultData({ isLoading: true }));
    await renderDashboard();
    expect(screen.getByTestId('dashboard-skeleton')).toBeInTheDocument();
    expect(screen.queryByTestId('returning-user-dashboard')).not.toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-dashboard')).not.toBeInTheDocument();
  });
  test('renders OnboardingDashboard for new users', async () => {
    mockUseDashboardData.mockReturnValue(
      makeDefaultData({ stage: 'new', profileCount: 0, correlationCount: 0, documentCount: 0 }),
    );
    await renderDashboard();
    expect(screen.getByTestId('onboarding-dashboard')).toBeInTheDocument();
    expect(screen.queryByTestId('returning-user-dashboard')).not.toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-progress-strip')).not.toBeInTheDocument();
  });
  test('renders ReturningUserDashboard for active users', async () => {
    mockUseDashboardData.mockReturnValue(makeDefaultData({ stage: 'active' }));
    await renderDashboard();
    expect(screen.getByTestId('returning-user-dashboard')).toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-dashboard')).not.toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-progress-strip')).not.toBeInTheDocument();
  });
  test('renders progress strip + ReturningUserDashboard for getting-started users', async () => {
    mockUseDashboardData.mockReturnValue(
      makeDefaultData({
        stage: 'getting-started',
        documentCount: 0,
        onboardingProgress: {
          completedSteps: 2,
          totalSteps: 4,
          nextStepLabel: 'View Matches',
          nextStepRoute: '/jobs/matches',
        },
      }),
    );
    await renderDashboard();
    expect(screen.getByTestId('onboarding-progress-strip')).toBeInTheDocument();
    expect(screen.getByTestId('returning-user-dashboard')).toBeInTheDocument();
    expect(screen.queryByTestId('onboarding-dashboard')).not.toBeInTheDocument();
  });
  test('renders dashboard title heading', async () => {
    await renderDashboard();
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
  });
  test('renders subtitle for non-loading state', async () => {
    await renderDashboard();
    expect(screen.getByText(SUBTITLE_PATTERN)).toBeInTheDocument();
  });
});
