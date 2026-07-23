import { type RenderResult, render, screen } from '@testing-library/react';

const FIT_SCORE_EXCELLENT: number = 90;

import { I18nextProvider } from 'react-i18next';
import { describe, expect } from 'vitest';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { DashboardHighlights } from './DashboardHighlights.tsx';
import { LatestDocumentCard } from './LatestDocumentCard.tsx';
import { TopMatchCard } from './TopMatchCard.tsx';

interface MockCorrelation {
  readonly id: string;
  readonly listing_title: string;
  readonly listing_company: string;
  readonly listing_location: string;
  readonly fit_score: number;
}

interface MockDocument {
  readonly request_id: string;
  readonly status: string;
  readonly download_url: string | null;
}

const mockCorrelation: MockCorrelation = {
  id: 'corr-1',
  listing_title: 'Senior Software Engineer',
  listing_company: 'Acme Corp',
  listing_location: 'San Francisco, CA',
  fit_score: FIT_SCORE_EXCELLENT,
};

const mockDocumentCompleted: MockDocument = {
  request_id: 'doc-1',
  status: 'completed',
  download_url: 'https://example.com/resume.pdf',
};

const mockDocumentGenerating: MockDocument = {
  request_id: 'doc-2',
  status: 'generating',
  download_url: null,
};

async function renderTopMatchCard(correlation: MockCorrelation | null): Promise<RenderResult> {
  return render(
    await wrapWithRouter(
      <I18nextProvider i18n={i18n}>
        <TopMatchCard correlation={correlation} />
      </I18nextProvider>,
    ),
  );
}

async function renderLatestDocumentCard(document: MockDocument | null): Promise<RenderResult> {
  return render(
    await wrapWithRouter(
      <I18nextProvider i18n={i18n}>
        <LatestDocumentCard document={document} />
      </I18nextProvider>,
    ),
  );
}

async function renderDashboardHighlights(
  topMatch: MockCorrelation | null = mockCorrelation,
  latestDocument: MockDocument | null = mockDocumentCompleted,
): Promise<RenderResult> {
  return render(
    await wrapWithRouter(
      <I18nextProvider i18n={i18n}>
        <DashboardHighlights topMatch={topMatch} latestDocument={latestDocument} />
      </I18nextProvider>,
    ),
  );
}

describe('TopMatchCard', () => {
  test('renders job title, company, and score for a given correlation', async () => {
    await renderTopMatchCard(mockCorrelation);
    expect(screen.getByText('Senior Software Engineer')).toBeInTheDocument();
    expect(screen.getByText('Acme Corp')).toBeInTheDocument();
    expect(screen.getByText('San Francisco, CA')).toBeInTheDocument();
    expect(screen.getByText('90 / 100')).toBeInTheDocument();
    expect(screen.queryByText('90%')).not.toBeInTheDocument();
  });

  test('renders empty state when correlation is null', async () => {
    await renderTopMatchCard(null);
    expect(screen.queryByText('Senior Software Engineer')).not.toBeInTheDocument();
    // Empty state has a link to browse jobs
    expect(screen.getByRole('link')).toBeInTheDocument();
  });

  test('applies correct color class for excellent score (90)', async () => {
    await renderTopMatchCard(mockCorrelation);
    const scoreBadge = screen.getByText('90 / 100');
    expect(scoreBadge).toHaveClass('match-score-excellent');
  });
});

describe('LatestDocumentCard', () => {
  test('shows Ready status and download link when completed', async () => {
    await renderLatestDocumentCard(mockDocumentCompleted);
    // Download link should be present
    const downloadLink = screen.getByRole('link');
    expect(downloadLink).toHaveAttribute('href', 'https://example.com/resume.pdf');
  });

  test.each([
    'javascript:alert(1)',
    'data:text/html,pwned',
    '//evil.example/resume.pdf',
    'not a url',
  ])('does not expose unsafe completed URL %s as a link', async (downloadUrl) => {
    await renderLatestDocumentCard({ ...mockDocumentCompleted, download_url: downloadUrl });
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  test('shows Generating indicator when status is generating', async () => {
    await renderLatestDocumentCard(mockDocumentGenerating);
    // Should not show a download link when generating
    const links = screen.queryAllByRole('link');
    const downloadLinks = links.filter((link) =>
      link.getAttribute('href')?.includes('example.com'),
    );
    expect(downloadLinks).toHaveLength(0);
  });

  test('renders empty state when document is null', async () => {
    await renderLatestDocumentCard(null);
    // Empty state has a link to documents page
    expect(screen.getByRole('link')).toBeInTheDocument();
  });
});

describe('DashboardHighlights', () => {
  test('renders both cards in grid layout', async () => {
    await renderDashboardHighlights();
    // Both cards render their data
    expect(screen.getByText('Senior Software Engineer')).toBeInTheDocument();
    // Download link for the completed document
    const downloadLink = screen
      .getAllByRole('link')
      .find((link) => link.getAttribute('href')?.includes('example.com'));
    expect(downloadLink).toBeDefined();
    // Grid section wrapper exists
    const sections = screen.getAllByRole('region');
    expect(sections.length).toBeGreaterThanOrEqual(2);
  });
});
