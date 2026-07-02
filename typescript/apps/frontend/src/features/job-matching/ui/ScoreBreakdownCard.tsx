import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type {
  FitFactorContributionResponse,
  FitFactorName,
  FitRankingBreakdownResponse,
} from '@/shared/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card.tsx';

interface ScoreBreakdownCardProps {
  readonly breakdown: FitRankingBreakdownResponse | null | undefined;
  readonly fitScore: number;
}

const FACTOR_LABEL_KEYS: Record<FitFactorName, string> = {
  ROLE_RELEVANCE: 'match.breakdown.factors.roleRelevance',
  SKILLS: 'match.breakdown.factors.skills',
  LOCATION: 'match.breakdown.factors.location',
  WORK_ARRANGEMENT: 'match.breakdown.factors.workArrangement',
  EXPERIENCE: 'match.breakdown.factors.experience',
  SALARY: 'match.breakdown.factors.salary',
  RECENCY: 'match.breakdown.factors.recency',
};

function influencePresentation(points: number): {
  readonly directionKey: string;
  readonly textClass: string;
  readonly value: string;
} {
  if (points > 0) {
    return {
      directionKey: 'match.breakdown.influence.positive',
      textClass: 'text-green-700 dark:text-green-400',
      value: `+${points.toFixed(1)}`,
    };
  }
  if (points < 0) {
    return {
      directionKey: 'match.breakdown.influence.negative',
      textClass: 'text-red-700 dark:text-red-400',
      value: `−${Math.abs(points).toFixed(1)}`,
    };
  }
  return {
    directionKey: 'match.breakdown.influence.neutral',
    textClass: 'text-muted-foreground',
    value: '0.0',
  };
}

function FactorRow({ factor }: { readonly factor: FitFactorContributionResponse }): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const influence = influencePresentation(factor.contribution_points);

  return (
    <li className="space-y-1 border-border border-t py-3 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-4">
        <span className="font-medium">{t(FACTOR_LABEL_KEYS[factor.factor])}</span>
        <span className={`shrink-0 font-medium tabular-nums ${influence.textClass}`}>
          <span className="sr-only">{`${t(influence.directionKey)}: `}</span>
          {t('match.breakdown.influence.points', { points: influence.value })}
        </span>
      </div>
      <p className="text-muted-foreground text-sm tabular-nums">
        {t('match.breakdown.compatibility', {
          score: Math.round(factor.compatibility_score),
        })}
      </p>
    </li>
  );
}

export function ScoreBreakdownCard({ breakdown, fitScore }: ScoreBreakdownCardProps): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const score = Math.round(fitScore);

  return (
    <Card role="region" aria-labelledby="fit-ranking-breakdown-title">
      <CardHeader className="space-y-2 pb-3">
        <CardTitle id="fit-ranking-breakdown-title">{t('match.breakdown.title')}</CardTitle>
        <p className="font-bold text-2xl tabular-nums">
          {t('match.breakdown.fitRanking', { score })}
        </p>
      </CardHeader>
      <CardContent>
        {breakdown && breakdown.factors.length > 0 ? (
          <ul>
            {breakdown.factors.map((factor) => (
              <FactorRow key={factor.factor} factor={factor} />
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">{t('match.breakdown.unavailable')}</p>
        )}
      </CardContent>
    </Card>
  );
}
