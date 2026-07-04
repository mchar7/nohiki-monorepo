import { type RenderResult, render, screen } from '@testing-library/react';

const FIT_SCORE_HIGH: number = 85;
const FIT_SCORE_MEDIUM: number = 72;
const MS_PER_DAY: number = 86_400_000;
const DAYS_AGO_3: number = 3;

import { I18nextProvider } from 'react-i18next';
import { describe, expect } from 'vitest';
import type { JobCorrelationResponse } from '@/shared/api';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/setup.ts';
import { DashboardRecentMatches } from './DashboardRecentMatches.tsx';

const CREATE_RE = /create/iu;

const mockCorrelations: JobCorrelationResponse[] = [
  {
    id: '1',
    pref_id: 'pref-1',
    listing_id: 'listing-1',
    fit_score: FIT_SCORE_HIGH,
    status: 'PENDING',
    score_breakdown: {},
    listing_title: 'Software Engineer',
    listing_company: 'Test Corp',
    listing_url: 'https://example.com/job/1',
    listing_location: 'Remote',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: '2',
    pref_id: 'pref-1',
    listing_id: 'listing-2',
    fit_score: FIT_SCORE_MEDIUM,
    status: 'PENDING',
    score_breakdown: {},
    listing_title: 'Frontend Developer',
    listing_company: 'Another Corp',
    listing_url: 'https://example.com/job/2',
    listing_location: 'New York',
    created_at: new Date(Date.now() - MS_PER_DAY * DAYS_AGO_3).toISOString(),
    updated_at: new Date(Date.now() - MS_PER_DAY * DAYS_AGO_3).toISOString(),
  },
];

async function renderComponent(props: Record<string, unknown> = {}): Promise<RenderResult> {
  return render(
    await wrapWithRouter(
      <I18nextProvider i18n={i18n}>
        <DashboardRecentMatches correlations={mockCorrelations} {...props} />
      </I18nextProvider>,
    ),
  );
}

describe('DashboardRecentMatches', () => {
  test('renders match cards', async () => {
    await renderComponent();
    expect(screen.getByText('Software Engineer')).toBeInTheDocument();
    expect(screen.getByText('Frontend Developer')).toBeInTheDocument();
  });

  test('renders company names', async () => {
    await renderComponent();
    expect(screen.getByText('Test Corp')).toBeInTheDocument();
    expect(screen.getByText('Another Corp')).toBeInTheDocument();
  });

  test('renders fit scores as points out of 100', async () => {
    await renderComponent();
    expect(screen.getByText('85 / 100')).toBeInTheDocument();
    expect(screen.getByText('72 / 100')).toBeInTheDocument();
    expect(screen.queryByText('85%')).not.toBeInTheDocument();
    expect(screen.queryByText('72%')).not.toBeInTheDocument();
  });

  test('renders empty state when no correlations', async () => {
    render(
      await wrapWithRouter(
        <I18nextProvider i18n={i18n}>
          <DashboardRecentMatches correlations={[]} />
        </I18nextProvider>,
      ),
    );
    expect(screen.getByRole('link', { name: CREATE_RE })).toBeInTheDocument();
  });

  test('renders loading skeleton when isLoading', async () => {
    render(
      await wrapWithRouter(
        <I18nextProvider i18n={i18n}>
          <DashboardRecentMatches correlations={[]} isLoading={true} />
        </I18nextProvider>,
      ),
    );
    expect(screen.queryByText('Software Engineer')).not.toBeInTheDocument();
  });
});
