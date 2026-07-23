import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { JSX, ReactNode } from 'react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import type { JobCorrelationResponse } from '@/shared/api';
import { i18n } from '@/test/i18n-setup.ts';
import { MatchDetailView } from './MatchDetailView.tsx';

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children }: { readonly children: ReactNode }): JSX.Element => <>{children}</>,
}));

const CORRELATION: JobCorrelationResponse = {
  id: 'correlation-1',
  listing_id: 'listing-1',
  pref_id: 'preference-1',
  fit_score: 85,
  listing_title: 'Software Engineer',
  listing_company: 'Example Co',
  listing_location: 'Remote',
  listing_url: 'https://example.com/jobs/1',
  status: 'PENDING',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  score_breakdown: {},
};

function renderView(listingUrl: string): void {
  render(
    <I18nextProvider i18n={i18n}>
      <MatchDetailView
        correlation={{ ...CORRELATION, listing_url: listingUrl }}
        onSave={vi.fn()}
        onApply={vi.fn()}
        onDismiss={vi.fn()}
        isSaving={false}
      />
    </I18nextProvider>,
  );
}

describe('MatchDetailView listing URL', () => {
  test.each([
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'not a URL',
  ])('does not render an external link for unsafe or malformed URL %s', (listingUrl) => {
    renderView(listingUrl);
    expect(screen.queryByRole('link', { name: 'Apply on Original Site' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply on Original Site' })).toBeDisabled();
  });

  test('renders a valid HTTPS external link', () => {
    renderView(CORRELATION.listing_url);
    expect(screen.getByRole('link', { name: 'Apply on Original Site' })).toHaveAttribute(
      'href',
      CORRELATION.listing_url,
    );
  });
});

describe('MatchDetailView status actions', () => {
  test('renders the current status badge without requiring a reload', () => {
    render(
      <I18nextProvider i18n={i18n}>
        <MatchDetailView
          correlation={{ ...CORRELATION, status: 'SAVED' }}
          onSave={vi.fn()}
          onApply={vi.fn()}
          onDismiss={vi.fn()}
          isSaving={false}
        />
      </I18nextProvider>,
    );

    expect(screen.getByText('Saved')).toBeInTheDocument();
  });
  test('renders fit scores as points out of 100', () => {
    renderView(CORRELATION.listing_url);

    expect(screen.getByText('85 / 100')).toBeInTheDocument();
    expect(screen.queryByText('85%')).not.toBeInTheDocument();
  });

  test('suppresses duplicate status actions while a request is pending', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const onApply = vi.fn();
    const onDismiss = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <MatchDetailView
          correlation={CORRELATION}
          onSave={onSave}
          onApply={onApply}
          onDismiss={onDismiss}
          isSaving={true}
        />
      </I18nextProvider>,
    );

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Apply on Original Site' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    await user.click(screen.getByRole('button', { name: 'More options' }));
    expect(screen.queryByText('Dismiss')).not.toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
    expect(onApply).not.toHaveBeenCalled();
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
