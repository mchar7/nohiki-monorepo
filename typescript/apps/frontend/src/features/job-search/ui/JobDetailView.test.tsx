import { render, screen } from '@testing-library/react';
import type { JSX } from 'react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';

// Mock router: Link renders as a plain anchor to avoid RouterProvider requirement
vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    to,
    search,
    className,
    'aria-label': ariaLabel,
  }: {
    readonly children: React.ReactNode;
    readonly to: string;
    readonly search?: Record<string, string>;
    readonly className?: string;
    readonly 'aria-label'?: string;
  }): JSX.Element => {
    const query = search ? `?${new URLSearchParams(search).toString()}` : '';
    return (
      <a href={`${to}${query}`} className={className} aria-label={ariaLabel}>
        {children}
      </a>
    );
  },
}));

import type { JobListingResponse } from '@/shared/api';
import { i18n } from '@/test/setup.ts';

import { JobDetailView } from './JobDetailView.tsx';

const VIEW_ORIGINAL_RE = /view original/iu;
const MAR_2026_RE = /Mar.*2026/u;

const MOCK_LISTING: JobListingResponse = {
  id: 'test-detail-1',
  listing_url: 'https://example.com/job/1',
  source: 'Indeed',
  title: 'Backend Developer',
  company_name: 'TechCo',
  description: 'We are looking for a backend developer.',
  location_raw: 'Toronto, ON',
  work_arrangement: 'hybrid',
  seniority_level: 'mid',
  language: 'fr-CA',
  required_skills: ['Go', 'PostgreSQL', 'Kafka'],
  posted_at: '2026-03-01T10:00:00Z',
  discovered_at: '2026-03-01T10:00:00Z',
  created_at: '2026-03-01T10:00:00Z',
};

function renderDetail(overrides: Partial<JobListingResponse> = {}): void {
  render(
    <I18nextProvider i18n={i18n}>
      <JobDetailView listing={{ ...MOCK_LISTING, ...overrides }} />
    </I18nextProvider>,
  );
}

describe('JobDetailView', () => {
  test('renders the top-level layout with header, description, sidebar, and actions', () => {
    renderDetail();
    expect(screen.getByText('Backend Developer')).toBeInTheDocument();
    expect(screen.getByText('We are looking for a backend developer.')).toBeInTheDocument();
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: VIEW_ORIGINAL_RE })).toBeInTheDocument();
  });
});

describe('JobHeader', () => {
  test('renders the listing title', () => {
    renderDetail();
    expect(screen.getByText('Backend Developer')).toBeInTheDocument();
  });

  test('renders the company name', () => {
    renderDetail();
    expect(screen.getByText('TechCo')).toBeInTheDocument();
  });

  test('renders the source badge', () => {
    renderDetail();
    // "Indeed" appears in both the header badge and the sidebar MetaRow
    const matches = screen.getAllByText('Indeed');
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  test('renders location when present', () => {
    renderDetail();
    expect(screen.getByText('Toronto, ON')).toBeInTheDocument();
  });

  test('hides location when null', () => {
    renderDetail({ location_raw: null });
    expect(screen.queryByText('Toronto, ON')).not.toBeInTheDocument();
  });

  test('renders work arrangement when present', () => {
    renderDetail();
    expect(screen.getByText('hybrid')).toBeInTheDocument();
  });

  test('renders seniority level when present', () => {
    renderDetail();
    expect(screen.getByText('mid')).toBeInTheDocument();
  });

  test('shows localized fallback when company_name is null', () => {
    renderDetail({ company_name: null });
    // i18n key: jobs:detail.unknownCompany → "Unknown Company"
    expect(screen.getByText('Unknown Company')).toBeInTheDocument();
  });
});

describe('JobDescription', () => {
  test('renders description text', () => {
    renderDetail();
    expect(screen.getByText('We are looking for a backend developer.')).toBeInTheDocument();
  });

  test('shows placeholder when description is null', () => {
    renderDetail({ description: null });
    // i18n key: jobs:card.noDescription → "No description available"
    expect(screen.getByText('No description available')).toBeInTheDocument();
  });
});

describe('JobSkills', () => {
  test('renders all skills as badges', () => {
    renderDetail();
    expect(screen.getByText('Go')).toBeInTheDocument();
    expect(screen.getByText('PostgreSQL')).toBeInTheDocument();
    expect(screen.getByText('Kafka')).toBeInTheDocument();
  });
  test('renders duplicate skills without duplicate React keys', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    try {
      renderDetail({ required_skills: ['Go', 'Go', 'Kafka'] });

      expect(screen.getAllByText('Go')).toHaveLength(2);
      expect(screen.getByText('Kafka')).toBeInTheDocument();
      expect(consoleError).not.toHaveBeenCalled();
    } finally {
      consoleError.mockRestore();
    }
  });

  test('shows placeholder when skills are empty', () => {
    renderDetail({ required_skills: [] });
    expect(screen.getByText('No skills listed')).toBeInTheDocument();
  });
});

describe('JobMetaSidebar', () => {
  test('renders source in the overview section', () => {
    renderDetail();
    expect(screen.getByText('Source')).toBeInTheDocument();
    // "Indeed" appears in both the header badge and the sidebar MetaRow
    expect(screen.getAllByText('Indeed').length).toBeGreaterThanOrEqual(1);
  });

  test('renders language with a human-readable name when present', () => {
    renderDetail({ language: 'fr-CA' });
    expect(screen.getByText('Language')).toBeInTheDocument();
    expect(screen.getByText('Canadian French')).toBeInTheDocument();
  });

  test('renders language for simple codes', () => {
    renderDetail({ language: 'de' });
    expect(screen.getByText('German')).toBeInTheDocument();
  });

  test('hides language row when language is null', () => {
    renderDetail({ language: null });
    expect(screen.queryByText('Language')).not.toBeInTheDocument();
  });

  test('renders posted date when present', () => {
    renderDetail();
    expect(screen.getByText('Posted')).toBeInTheDocument();
    // formatDate returns locale string - assert date parts are present
    expect(screen.getByText(MAR_2026_RE)).toBeInTheDocument();
  });

  test('hides posted date when null', () => {
    renderDetail({ posted_at: null });
    expect(screen.queryByText('Posted')).not.toBeInTheDocument();
  });
});

describe('JobActions', () => {
  test('renders an external view original link', () => {
    renderDetail();
    const link = screen.getByRole('link', { name: VIEW_ORIGINAL_RE });
    expect(link).toHaveAttribute('href', 'https://example.com/job/1');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  test.each([
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'not a URL',
  ])('does not render a link for unsafe or malformed URL %s', (listingUrl) => {
    renderDetail({ listing_url: listingUrl });
    expect(screen.queryByRole('link', { name: VIEW_ORIGINAL_RE })).not.toBeInTheDocument();
  });
});
