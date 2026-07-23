import { render, screen } from '@testing-library/react';
import type { JSX } from 'react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';

import type { JobListingResponse } from '@/shared/api';
import { i18n } from '@/test/i18n-setup.ts';

// Mock router - Link renders as plain anchor for test inspectability
vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    to,
    params,
  }: {
    readonly children: React.ReactNode;
    readonly to: string;
    readonly params?: Record<string, string>;
  }): JSX.Element => (
    <a href={`${to}/${params?.listingId ?? ''}`} data-testid="listing-link">
      {children}
    </a>
  ),
}));

import { JobListingCard } from './JobListingCard.tsx';

const LISTING_LANGUAGE_RE = /listing language/iu;
const AGO_RE = /ago/u;
const MORE_RE = /more/u;

/** Fully populated listing fixture. Override fields as needed per test. */
const MOCK_LISTING: JobListingResponse = {
  id: 'test-listing-1',
  listing_url: 'https://example.com/job/1',
  source: 'LinkedIn',
  title: 'Senior Software Engineer',
  company_name: 'Acme Corp',
  description: 'Build distributed systems at scale.',
  location_raw: 'Montreal, QC',
  work_arrangement: 'remote',
  seniority_level: 'senior',
  language: 'fr-CA',
  required_skills: ['TypeScript', 'React', 'Python'],
  posted_at: '2026-03-10T12:00:00Z',
  discovered_at: '2026-03-10T12:00:00Z',
  created_at: '2026-03-10T12:00:00Z',
};

const SKILLS_OVERFLOW_COUNT = 7;
const MAX_VISIBLE_SKILLS = 5;

/** Helper to render card with optional listing and card-prop overrides. */
function renderCard(
  overrides: Partial<JobListingResponse> = {},
  cardProps: Partial<React.ComponentProps<typeof JobListingCard>> = {},
): void {
  render(
    <I18nextProvider i18n={i18n}>
      <JobListingCard listing={{ ...MOCK_LISTING, ...overrides }} {...cardProps} />
    </I18nextProvider>,
  );
}

describe('LanguageBadge', () => {
  test('displays a human-readable language name for foreign-language listings', () => {
    renderCard({ language: 'fr-CA' });
    // UI language is 'en' (from test setup), listing is French → badge shown
    expect(screen.getByText('Canadian French')).toBeInTheDocument();
  });

  test('hides the badge when language is null', () => {
    renderCard({ language: null });
    expect(screen.queryByText('Canadian French')).not.toBeInTheDocument();
  });

  test('hides the badge when listing base language matches UI base language', () => {
    renderCard({ language: 'en-US' });
    // Both base languages are 'en' → no badge
    expect(screen.queryByLabelText(LISTING_LANGUAGE_RE)).not.toBeInTheDocument();
  });

  test('hides the badge when listing language exactly matches UI language', () => {
    renderCard({ language: 'en' });
    expect(screen.queryByLabelText(LISTING_LANGUAGE_RE)).not.toBeInTheDocument();
  });

  test('includes an accessible aria-label with the formatted language name', () => {
    renderCard({ language: 'de' });
    // i18n key: "Listing language: {{language}}" with language = "German"
    expect(screen.getByLabelText('Listing language: German')).toBeInTheDocument();
  });
});

describe('JobListingCard - content', () => {
  test('renders the listing title', () => {
    renderCard();
    expect(screen.getByText('Senior Software Engineer')).toBeInTheDocument();
  });

  test('renders the company name', () => {
    renderCard();
    expect(screen.getByText('Acme Corp')).toBeInTheDocument();
  });

  test('renders the source badge', () => {
    renderCard();
    expect(screen.getByText('LinkedIn')).toBeInTheDocument();
  });

  test('renders location when present', () => {
    renderCard();
    expect(screen.getByText('Montreal, QC')).toBeInTheDocument();
  });

  test('hides location when missing', () => {
    renderCard({ location_raw: undefined });
    expect(screen.queryByText('Montreal, QC')).not.toBeInTheDocument();
  });

  test('renders work arrangement when present', () => {
    renderCard();
    expect(screen.getByText('remote')).toBeInTheDocument();
  });

  test('hides work arrangement when null', () => {
    renderCard({ work_arrangement: null });
    expect(screen.queryByText('remote')).not.toBeInTheDocument();
  });

  test('hides posted time when null', () => {
    renderCard({ posted_at: null });
    expect(screen.queryByText(AGO_RE)).not.toBeInTheDocument();
  });

  test('uses the company i18n fallback when company_name is missing', () => {
    renderCard({ company_name: undefined });
    // i18n key: jobs:card.company → "Company"
    expect(screen.getByText('Company')).toBeInTheDocument();
  });
});

describe('JobListingCard - description preview', () => {
  test('renders description text when description is present', () => {
    renderCard({ description: 'Build distributed systems at scale.' });
    expect(screen.getByText('Build distributed systems at scale.')).toBeInTheDocument();
  });

  test('does not render description when description is missing', () => {
    renderCard({ description: undefined });
    expect(screen.queryByText('Build distributed systems at scale.')).not.toBeInTheDocument();
  });

  test('strips HTML tags from description before rendering', () => {
    renderCard({ description: '<p>Build <strong>distributed</strong> systems.</p>' });
    expect(screen.getByText('Build distributed systems.')).toBeInTheDocument();
  });
});

describe('JobListingCard - skills', () => {
  test('renders skill badges up to the visible limit', () => {
    renderCard();
    expect(screen.getByText('TypeScript')).toBeInTheDocument();
    expect(screen.getByText('React')).toBeInTheDocument();
    expect(screen.getByText('Python')).toBeInTheDocument();
  });
  test('renders duplicate skills without duplicate React keys', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    try {
      renderCard({ required_skills: ['TypeScript', 'TypeScript', 'React'] });

      expect(screen.getAllByText('TypeScript')).toHaveLength(2);
      expect(screen.getByText('React')).toBeInTheDocument();
      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  });
  test('renders duplicate and cross-category factors without duplicate React keys', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    try {
      renderCard(
        {},
        {
          matchExplanation:
            'Strengths: location (+0.5), location (+0.4). Concerns: location (-0.2).',
        },
      );

      expect(screen.getAllByText('Location')).toHaveLength(3);
      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  });

  test('shows overflow count when skills exceed the limit', () => {
    const manySkills = Array.from({ length: SKILLS_OVERFLOW_COUNT }, (_, i) => `Skill${i + 1}`);
    renderCard({ required_skills: manySkills });
    const overflow = SKILLS_OVERFLOW_COUNT - MAX_VISIBLE_SKILLS;
    expect(screen.getByText(`+${overflow} more`)).toBeInTheDocument();
  });

  test('hides skills footer when no skills exist', () => {
    renderCard({ required_skills: [] });
    expect(screen.queryByText(MORE_RE)).not.toBeInTheDocument();
  });
});
