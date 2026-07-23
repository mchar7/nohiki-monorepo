import { type RenderResult, render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { ReturningUserDashboard } from './ReturningUserDashboard.tsx';

// --- Mock child components to isolate composition tests ---

vi.mock('./DashboardNewMatchesBanner.tsx', () => ({
  DashboardNewMatchesBanner: ({ newMatchCount }: { newMatchCount: number }) => (
    <div data-testid="new-matches-banner" data-count={newMatchCount}>
      Banner
    </div>
  ),
}));

vi.mock('./DashboardStatsCards.tsx', () => ({
  DashboardStatsCards: () => <div data-testid="stats-cards">Stats</div>,
}));

vi.mock('./DashboardHighlights.tsx', () => ({
  DashboardHighlights: () => <div data-testid="highlights">Highlights</div>,
}));

vi.mock('./DashboardActionItems.tsx', () => ({
  DashboardActionItems: () => <div data-testid="action-items">Actions</div>,
  computeActionItems: () => [],
}));

vi.mock('./CommonMissingSkillsWidget.tsx', () => ({
  CommonMissingSkillsWidget: ({
    hasSkills,
    profileId,
  }: {
    hasSkills: boolean;
    profileId?: string;
  }) => (
    <div data-testid="missing-skills" data-has-skills={hasSkills} data-profile-id={profileId}>
      Skills
    </div>
  ),
}));

vi.mock('./DashboardActivityChart.tsx', () => ({
  DashboardActivityChart: () => <div data-testid="activity-chart">Chart</div>,
}));

vi.mock('./DashboardRecentMatches.tsx', () => ({
  DashboardRecentMatches: () => <div data-testid="recent-matches">Matches</div>,
}));

// --- Helpers ---

const defaultProps: ReturningUserDashboardProps = {
  stats: { jobMatches: 5, profiles: 2, documents: 3, savedJobs: 1 },
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
  ] as ReturningUserDashboardProps['correlations'],
  profiles: [{ id: 'prof-1', pref_name: 'Engineer', user_skills: ['ts', 'react'] }],
  documents: [{ request_id: 'doc-1', status: 'completed', download_url: null }],
  topMatch: {
    id: 'cor-1',
    listing_title: 'Engineer',
    listing_company: 'Acme',
    listing_location: 'Remote',
    fit_score: 90,
  },
  latestDocument: { request_id: 'doc-1', status: 'completed', download_url: null },
  newMatchCount: 2,
  isLoading: false,
};

type ReturningUserDashboardProps = Parameters<typeof ReturningUserDashboard>[0];

async function renderComponent(
  overrides: Partial<ReturningUserDashboardProps> = {},
): Promise<RenderResult> {
  const props = { ...defaultProps, ...overrides } as ReturningUserDashboardProps;
  return render(
    await wrapWithRouter(
      <I18nextProvider i18n={i18n}>
        <ReturningUserDashboard {...props} />
      </I18nextProvider>,
    ),
  );
}

// --- Tests ---

describe('ReturningUserDashboard', () => {
  test('renders all child components', async () => {
    await renderComponent();

    expect(screen.getByTestId('new-matches-banner')).toBeInTheDocument();
    expect(screen.getByTestId('stats-cards')).toBeInTheDocument();
    expect(screen.getByTestId('highlights')).toBeInTheDocument();
    expect(screen.getByTestId('action-items')).toBeInTheDocument();
    expect(screen.getByTestId('missing-skills')).toBeInTheDocument();
    expect(screen.getByTestId('recent-matches')).toBeInTheDocument();
  });

  test('passes newMatchCount to banner', async () => {
    await renderComponent({ newMatchCount: 7 });

    const banner = screen.getByTestId('new-matches-banner');
    expect(banner).toHaveAttribute('data-count', '7');
  });

  test('passes hasSkills=true when first profile has skills', async () => {
    await renderComponent();

    const widget = screen.getByTestId('missing-skills');
    expect(widget).toHaveAttribute('data-has-skills', 'true');
    expect(widget).toHaveAttribute('data-profile-id', 'prof-1');
  });

  test('passes hasSkills=false when first profile has no skills', async () => {
    await renderComponent({
      profiles: [{ id: 'prof-1', pref_name: 'Test', user_skills: [] }],
    });

    const widget = screen.getByTestId('missing-skills');
    expect(widget).toHaveAttribute('data-has-skills', 'false');
  });

  test('passes hasSkills=false when first profile has undefined skills', async () => {
    await renderComponent({
      profiles: [{ id: 'prof-1', pref_name: 'Test' }],
    });

    const widget = screen.getByTestId('missing-skills');
    expect(widget).toHaveAttribute('data-has-skills', 'false');
  });

  test('handles empty profiles gracefully', async () => {
    await renderComponent({ profiles: [] });

    const widget = screen.getByTestId('missing-skills');
    expect(widget).toHaveAttribute('data-has-skills', 'false');
  });
});
