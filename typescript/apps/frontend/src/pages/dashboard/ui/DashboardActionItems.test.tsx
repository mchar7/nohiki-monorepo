import { render, screen } from '@testing-library/react';
import type { JSX } from 'react';
import { describe, expect, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
  }),
}));

vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    to,
    className,
  }: {
    readonly children: React.ReactNode;
    readonly to: string;
    readonly className?: string;
  }): JSX.Element => (
    <a href={to} className={className}>
      {children}
    </a>
  ),
}));

import { DashboardActionItems } from './DashboardActionItems.tsx';
import { computeActionItems } from './DashboardActionItemsModel.ts';

const MATCH_SCORE_HIGH: number = 85;
const MATCH_SCORE_GOOD: number = 75;
const MATCH_SCORE_LOW: number = 50;
const MAX_DISPLAYED_ITEMS: number = 4;

const REVIEW_MATCHES_RE = /actionItems\.reviewMatches\.title/u;

const mockT = (key: string, opts?: Record<string, unknown>): string =>
  opts?.count !== undefined ? `${key}:${opts.count}` : key;

interface ProfileStub {
  id: string;
  pref_name: string;
  user_skills?: readonly unknown[];
}

interface CorrelationStub {
  id: string;
  fit_score: number;
  status: string;
}

interface DocumentStub {
  request_id: string;
  status: string;
  download_url?: string | null;
}

const makeProfile = (id: string, skills?: readonly unknown[]): ProfileStub => ({
  id,
  pref_name: `Profile ${id}`,
  user_skills: skills,
});

const makeCorrelation = (id: string, fitScore: number, status: string): CorrelationStub => ({
  id,
  fit_score: fitScore,
  status,
});

const makeDocument = (id: string, status: string, url?: string | null): DocumentStub => ({
  request_id: id,
  status,
  download_url: url,
});

/** 3 profiles with skills triggers the "all caught up" empty state */
const threeProfilesWithSkills: ProfileStub[] = [
  makeProfile('p1', ['skill']),
  makeProfile('p2', ['skill']),
  makeProfile('p3', ['skill']),
];

function renderItems(props: {
  profiles?: ProfileStub[];
  correlations?: CorrelationStub[];
  documents?: DocumentStub[];
}): void {
  render(
    <DashboardActionItems
      profiles={props.profiles ?? []}
      correlations={props.correlations ?? []}
      documents={props.documents ?? []}
    />,
  );
}

describe('computeActionItems: skills', () => {
  test('returns "complete skills" for undefined user_skills', () => {
    const items = computeActionItems([makeProfile('p1')], [], [], mockT);
    expect(items.some((i) => i.id === 'complete-skills')).toBe(true);
  });

  test('returns "complete skills" for empty user_skills array', () => {
    const items = computeActionItems([makeProfile('p1', [])], [], [], mockT);
    expect(items.some((i) => i.id === 'complete-skills')).toBe(true);
  });

  test('omits "complete skills" when profile has skills', () => {
    const items = computeActionItems([makeProfile('p1', ['TS', 'React'])], [], [], mockT);
    expect(items.some((i) => i.id === 'complete-skills')).toBe(false);
  });
});

describe('computeActionItems: matches & documents', () => {
  test('returns matches with correct count for EVALUATED + score >= 70', () => {
    const correlations = [
      makeCorrelation('c1', MATCH_SCORE_HIGH, 'EVALUATED'),
      makeCorrelation('c2', MATCH_SCORE_GOOD, 'EVALUATED'),
      makeCorrelation('c3', MATCH_SCORE_LOW, 'EVALUATED'),
      makeCorrelation('c4', MATCH_SCORE_HIGH, 'SAVED'),
    ];
    const items = computeActionItems([makeProfile('p1', ['skill'])], correlations, [], mockT);
    const matchItem = items.find((i) => i.id === 'review-matches');
    expect(matchItem).toBeDefined();
    expect(matchItem?.title).toBe('actionItems.reviewMatches.title:2');
  });

  test('omits matches when no EVALUATED correlations with score >= 70', () => {
    const correlations = [
      makeCorrelation('c1', MATCH_SCORE_LOW, 'EVALUATED'),
      makeCorrelation('c2', MATCH_SCORE_HIGH, 'SAVED'),
    ];
    const items = computeActionItems([makeProfile('p1', ['skill'])], correlations, [], mockT);
    expect(items.some((i) => i.id === 'review-matches')).toBe(false);
  });

  test('returns download action for completed document with URL', () => {
    const docs = [makeDocument('d1', 'COMPLETED', 'https://s3.example.com/resume.pdf')];
    const items = computeActionItems([makeProfile('p1', ['skill'])], [], docs, mockT);
    expect(items.some((i) => i.id === 'download-resume')).toBe(true);
  });
});

describe('computeActionItems: profiles & limits', () => {
  test('returns "create profile" when count < 3', () => {
    const items = computeActionItems([makeProfile('p1', ['skill'])], [], [], mockT);
    expect(items.some((i) => i.id === 'create-profile')).toBe(true);
  });

  test('omits "create profile" when count >= 3', () => {
    const items = computeActionItems(threeProfilesWithSkills, [], [], mockT);
    expect(items.some((i) => i.id === 'create-profile')).toBe(false);
  });

  test('limits output to MAX_ACTION_ITEMS', () => {
    const docs = [makeDocument('d1', 'COMPLETED', 'https://s3.example.com/resume.pdf')];
    const items = computeActionItems(
      [makeProfile('p1')],
      [makeCorrelation('c1', MATCH_SCORE_HIGH, 'EVALUATED')],
      docs,
      mockT,
    );
    expect(items.length).toBeLessThanOrEqual(MAX_DISPLAYED_ITEMS);
  });
});

describe('DashboardActionItems: skills actions', () => {
  test('shows "complete skills" when profile has no user_skills', () => {
    renderItems({ profiles: [makeProfile('p1')] });
    expect(screen.getByText('actionItems.completeSkills.title')).toBeInTheDocument();
  });

  test('shows "complete skills" when profile has empty user_skills array', () => {
    renderItems({ profiles: [makeProfile('p1', [])] });
    expect(screen.getByText('actionItems.completeSkills.title')).toBeInTheDocument();
  });

  test('does NOT show "complete skills" when profile has skills', () => {
    renderItems({ profiles: threeProfilesWithSkills });
    expect(screen.queryByText('actionItems.completeSkills.title')).not.toBeInTheDocument();
  });
});

describe('DashboardActionItems: matches actions', () => {
  test('shows review matches with correct count', () => {
    const correlations = [
      makeCorrelation('c1', MATCH_SCORE_HIGH, 'EVALUATED'),
      makeCorrelation('c2', MATCH_SCORE_GOOD, 'EVALUATED'),
      makeCorrelation('c3', MATCH_SCORE_LOW, 'EVALUATED'),
    ];
    renderItems({ profiles: threeProfilesWithSkills, correlations });
    expect(screen.getByText('actionItems.reviewMatches.title:2')).toBeInTheDocument();
  });

  test('does NOT show matches when no qualifying correlations', () => {
    renderItems({
      profiles: threeProfilesWithSkills,
      correlations: [makeCorrelation('c1', MATCH_SCORE_LOW, 'EVALUATED')],
    });
    expect(screen.queryByText(REVIEW_MATCHES_RE)).not.toBeInTheDocument();
  });
});

describe('DashboardActionItems: document actions', () => {
  test('shows download resume when completed document with download_url exists', () => {
    renderItems({
      profiles: threeProfilesWithSkills,
      documents: [makeDocument('d1', 'COMPLETED', 'https://s3.example.com/resume.pdf')],
    });
    expect(screen.getByText('actionItems.downloadResume.title')).toBeInTheDocument();
  });
});

test.each([
  'javascript:alert(1)',
  'data:text/html,pwned',
  '//evil.example/resume.pdf',
  'not a url',
])('does not render a download action for unsafe URL %s', (downloadUrl) => {
  renderItems({
    profiles: threeProfilesWithSkills,
    documents: [makeDocument('d1', 'COMPLETED', downloadUrl)],
  });
  expect(screen.queryByText('actionItems.downloadResume.title')).not.toBeInTheDocument();
});

describe('DashboardActionItems: profile creation', () => {
  test('shows "create profile" when profile count < 3', () => {
    renderItems({ profiles: [makeProfile('p1', ['skill'])] });
    expect(screen.getByText('actionItems.createProfile.title')).toBeInTheDocument();
  });

  test('does NOT show "create profile" when profile count >= 3', () => {
    renderItems({ profiles: threeProfilesWithSkills });
    expect(screen.queryByText('actionItems.createProfile.title')).not.toBeInTheDocument();
  });
});

describe('DashboardActionItems: empty state & accessibility', () => {
  test('shows "all caught up" empty state when no action items apply', () => {
    renderItems({ profiles: threeProfilesWithSkills });
    expect(screen.getByText('actionItems.empty.title')).toBeInTheDocument();
    expect(screen.getByText('actionItems.browseJobs')).toBeInTheDocument();
  });

  test('action items have role="listitem" for accessibility', () => {
    renderItems({
      profiles: [makeProfile('p1')],
      correlations: [makeCorrelation('c1', MATCH_SCORE_HIGH, 'EVALUATED')],
    });
    expect(screen.getAllByRole('listitem').length).toBeGreaterThan(0);
  });

  test('limits rendered items to maximum', () => {
    renderItems({
      profiles: [makeProfile('p1')],
      correlations: [makeCorrelation('c1', MATCH_SCORE_HIGH, 'EVALUATED')],
      documents: [makeDocument('d1', 'COMPLETED', 'https://s3.example.com/resume.pdf')],
    });
    expect(screen.getAllByRole('listitem').length).toBeLessThanOrEqual(MAX_DISPLAYED_ITEMS);
  });
});
