import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, test } from 'vitest';
import { axe } from 'vitest-axe';
import '@/test/axe-setup.ts';
import type { FitRankingBreakdownResponse } from '@/shared/api';
import { i18n } from '@/test/i18n-setup.ts';
import { ScoreBreakdownCard } from './ScoreBreakdownCard.tsx';

const BREAKDOWN: FitRankingBreakdownResponse = {
  method_version: 'deterministic-fit-v1',
  factors: [
    {
      factor: 'ROLE_RELEVANCE',
      compatibility_score: 84,
      importance: 100,
      contribution_points: 84,
    },
    {
      factor: 'SKILLS',
      compatibility_score: 96,
      importance: 75,
      contribution_points: 3,
    },
    {
      factor: 'LOCATION',
      compatibility_score: 36,
      importance: 50,
      contribution_points: -2,
    },
    {
      factor: 'WORK_ARRANGEMENT',
      compatibility_score: 84,
      importance: 50,
      contribution_points: 0,
    },
  ],
};

const EMPTY_BREAKDOWN: FitRankingBreakdownResponse = {
  method_version: 'deterministic-fit-v1',
  factors: [],
};

function renderCard(
  breakdown: FitRankingBreakdownResponse | null | undefined,
  fitScore = 85,
): ReturnType<typeof render> {
  return render(
    <I18nextProvider i18n={i18n}>
      <ScoreBreakdownCard breakdown={breakdown} fitScore={fitScore} />
    </I18nextProvider>,
  );
}

describe('ScoreBreakdownCard public fit-ranking contract', () => {
  test('renders human labels, compatibility, and signed factor directions that reconcile', () => {
    renderCard(BREAKDOWN);

    expect(screen.getByRole('region', { name: 'Fit breakdown' })).toBeInTheDocument();
    expect(screen.getByText('Match score 85 / 100')).toBeInTheDocument();
    expect(screen.getByText('Role relevance')).toBeInTheDocument();
    expect(screen.getByText('Skills')).toBeInTheDocument();
    expect(screen.getByText('Location')).toBeInTheDocument();
    expect(screen.getByText('Work arrangement')).toBeInTheDocument();
    expect(screen.getByText('Compatibility 96 / 100')).toBeInTheDocument();
    expect(screen.getByText('+3.0 points')).toHaveTextContent('Strength: +3.0 points');
    expect(screen.getByText('−2.0 points')).toHaveTextContent('Concern: −2.0 points');
    expect(screen.getByText('0.0 points')).toHaveTextContent('Neutral: 0.0 points');

    expect(BREAKDOWN.factors.reduce((total, factor) => total + factor.contribution_points, 0)).toBe(
      85,
    );
  });

  test('does not expose technical, probability, confidence, or SHAP language', () => {
    const { container } = renderCard(BREAKDOWN);
    const publicText = container.textContent?.toLowerCase() ?? '';

    for (const forbidden of [
      'maxsim',
      'rerank',
      'cosine',
      'feature_vector',
      'raw_feature',
      'technical',
      'probability',
      'confidence',
      'shap',
      'machine learning',
      'model score',
      'percent',
      '%',
      'deterministic-fit-v1',
    ]) {
      expect(publicText).not.toContain(forbidden);
    }
  });

  test.each([
    ['missing', undefined],
    ['null', null],
    ['empty', EMPTY_BREAKDOWN],
  ] as const)('renders unavailable when the typed breakdown is %s', (_state, breakdown) => {
    renderCard(breakdown);

    expect(screen.getByText('Match score 85 / 100')).toBeInTheDocument();
    expect(screen.getByText(i18n.t('jobs:match.breakdown.unavailable'))).toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  test('has no automated accessibility violations', async () => {
    const { container } = renderCard(BREAKDOWN);

    expect(await axe(container)).toHaveNoViolations();
  });
});
