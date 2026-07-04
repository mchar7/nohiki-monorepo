import { type RenderResult, render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect } from 'vitest';
import { i18n } from '@/test/setup.ts';
import type { DashboardStats } from './Dashboard.types.ts';
import { DashboardStatsCards } from './DashboardStatsCards.tsx';

const TREND_LABEL_PATTERN = /this week/u;

const mockStats = {
  jobMatches: 42,
  profiles: 3,
  documents: 15,
  savedJobs: 8,
};

function renderComponent(
  stats: DashboardStats = mockStats,
  props: Record<string, unknown> = {},
): RenderResult {
  return render(
    <I18nextProvider i18n={i18n}>
      <DashboardStatsCards stats={stats} {...props} />
    </I18nextProvider>,
  );
}

describe('DashboardStatsCards', () => {
  test('renders all stat cards', () => {
    renderComponent();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('15')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();
  });

  test('renders loading skeletons when isLoading is true', () => {
    renderComponent(mockStats, { isLoading: true });
    expect(screen.queryByText('42')).not.toBeInTheDocument();
  });

  test('formats large numbers with locale', () => {
    const largeStats = {
      jobMatches: 1_234_567,
      profiles: 0,
      documents: 0,
      savedJobs: 0,
    };
    render(
      <I18nextProvider i18n={i18n}>
        <DashboardStatsCards stats={largeStats} />
      </I18nextProvider>,
    );
    expect(screen.getByText('1,234,567')).toBeInTheDocument();
  });

  test('shows upward trend indicator with correct delta', () => {
    const stats: DashboardStats = {
      ...mockStats,
      trends: { jobMatches: { direction: 'up', delta: 5 } },
    };
    renderComponent(stats);
    const trend = screen.getByLabelText('Up 5 this week');
    expect(trend).toHaveTextContent('↑ 5');
    expect(trend).toHaveClass('text-green-600');
  });

  test('shows downward trend indicator with absolute delta', () => {
    const stats: DashboardStats = {
      ...mockStats,
      trends: { documents: { direction: 'down', delta: -3 } },
    };
    renderComponent(stats);
    const trend = screen.getByLabelText('Down 3 this week');
    expect(trend).toHaveTextContent('↓ 3');
    expect(trend).toHaveClass('text-amber-600');
  });

  test('shows no trend indicator when trends is undefined', () => {
    renderComponent();
    expect(screen.queryByLabelText(TREND_LABEL_PATTERN)).not.toBeInTheDocument();
  });

  test('shows no trend indicator when direction is unavailable', () => {
    const stats: DashboardStats = {
      ...mockStats,
      trends: { jobMatches: { direction: 'unavailable', delta: 0 } },
    };
    renderComponent(stats);
    expect(screen.queryByLabelText(TREND_LABEL_PATTERN)).not.toBeInTheDocument();
  });
});
