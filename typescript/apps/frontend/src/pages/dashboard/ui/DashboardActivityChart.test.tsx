import { type RenderResult, render, screen } from '@testing-library/react';
import type { PropsWithChildren } from 'react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';

import type { JobCorrelationResponse } from '@/shared/api';
import { i18n } from '@/test/setup.ts';
import { DashboardActivityChart } from './DashboardActivityChart.tsx';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: PropsWithChildren) => <div>{children}</div>,
  AreaChart: () => null,
  Area: () => null,
  CartesianGrid: () => null,
  Line: () => null,
  XAxis: () => null,
  Tooltip: () => null,
  Legend: () => null,
}));

const TREND_ARROW_PATTERN = /↑|↓|→/u;
const UP_TREND_PATTERN = /↑.*more matches/u;
const DAYS_AGO_PREVIOUS_HALF = 25;

function makeCorrelation(daysAgo: number): JobCorrelationResponse {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return {
    id: crypto.randomUUID(),
    pref_id: 'pref-1',
    listing_id: 'listing-1',
    fit_score: 80,
    status: 'EVALUATED',
    score_breakdown: {},
    listing_title: 'Engineer',
    listing_company: 'Acme',
    listing_url: 'https://example.com',
    listing_location: 'Remote',
    created_at: date.toISOString(),
    updated_at: date.toISOString(),
  } as JobCorrelationResponse;
}

/** Correlations concentrated in the recent half → "up" trend. */
const upTrendCorrelations: JobCorrelationResponse[] = [
  ...Array.from({ length: 8 }, () => makeCorrelation(2)),
  makeCorrelation(DAYS_AGO_PREVIOUS_HALF),
];

function renderComponent(
  correlations: readonly JobCorrelationResponse[] = upTrendCorrelations,
  props: Record<string, unknown> = {},
): RenderResult {
  return render(
    <I18nextProvider i18n={i18n}>
      <DashboardActivityChart correlations={correlations} {...props} />
    </I18nextProvider>,
  );
}

describe('DashboardActivityChart', () => {
  test('renders without error', () => {
    renderComponent();
    expect(screen.getByText('Activity Overview')).toBeInTheDocument();
  });

  test('displays trend summary text', () => {
    renderComponent();
    const trendElement = screen.getByText(TREND_ARROW_PATTERN);
    expect(trendElement).toBeInTheDocument();
  });

  test('applies green color class for upward trend', () => {
    renderComponent(upTrendCorrelations);
    const trendElement = screen.getByText(UP_TREND_PATTERN);
    expect(trendElement).toHaveClass('text-green-600');
  });

  test('renders info tooltip trigger', () => {
    renderComponent();
    expect(screen.getByLabelText('Chart information')).toBeInTheDocument();
  });

  test('renders time range selector buttons', () => {
    renderComponent();
    expect(screen.getByText('90 days')).toBeInTheDocument();
    expect(screen.getByText('30 days')).toBeInTheDocument();
    expect(screen.getByText('7 days')).toBeInTheDocument();
  });
});
