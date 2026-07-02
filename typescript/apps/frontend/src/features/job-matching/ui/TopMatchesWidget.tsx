import { Link } from '@tanstack/react-router';
import { ArrowRight, Building2, X } from 'lucide-react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { JobCorrelationResponse } from '@/shared/api';
import { useIsMobileLayout } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { ScoreBadge } from '@/shared/ui/score-badge.tsx';

const DISMISSED_KEY = 'nohiki:top-matches-dismissed';
const MIN_SCORE_THRESHOLD = 60;
const TOP_MATCHES_LIMIT = 3;

interface TopMatchesWidgetProps {
  readonly correlations: readonly JobCorrelationResponse[];
}

/** Filters, sorts, and returns the top N correlations above the score threshold. */
function getTopMatches(
  correlations: readonly JobCorrelationResponse[],
  limit: number,
): readonly JobCorrelationResponse[] {
  return correlations
    .filter((c) => c.fit_score >= MIN_SCORE_THRESHOLD)
    .slice()
    .sort((a: JobCorrelationResponse, b: JobCorrelationResponse) => b.fit_score - a.fit_score)
    .slice(0, limit);
}

/** Compact card displaying a single top match with title, company, and score. */
function TopMatchCard({
  correlation,
}: {
  readonly correlation: JobCorrelationResponse;
}): JSX.Element {
  return (
    <Link
      to="/jobs/matches/$correlationId"
      params={{ correlationId: correlation.id }}
      className="group flex min-w-0 flex-1 items-center gap-3 rounded-lg border bg-card p-3 transition-colors hover:bg-accent/50"
    >
      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
        <Building2 className="size-4 text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-sm leading-tight">{correlation.listing_title}</p>
        <p className="truncate text-muted-foreground text-xs">
          {correlation.listing_company ?? ''}
        </p>
      </div>
      <ScoreBadge score={correlation.fit_score} className="shrink-0" />
    </Link>
  );
}

/** Horizontal strip showing the user's top matches above the listings grid. */
function TopMatchesWidget({ correlations }: TopMatchesWidgetProps): JSX.Element | null {
  const { t } = useTranslation(['jobs']);
  const isMobile = useIsMobileLayout();
  const [dismissed, setDismissed] = useState<boolean>(
    () => localStorage.getItem(DISMISSED_KEY) === 'true',
  );

  const topMatches = getTopMatches(correlations, TOP_MATCHES_LIMIT);

  if (dismissed || topMatches.length === 0) {
    return null;
  }

  const handleDismiss = (): void => {
    localStorage.setItem(DISMISSED_KEY, 'true');
    setDismissed(true);
  };

  const visibleMatches = isMobile ? topMatches.slice(0, 1) : topMatches;

  return (
    <div className="relative space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-sm">{t('match.topMatches')}</h3>
        <Button
          variant="ghost"
          size="icon"
          className="size-6"
          onClick={handleDismiss}
          aria-label={t('match.topMatchesDismiss')}
        >
          <X className="size-3.5" />
        </Button>
      </div>
      <div className="flex gap-3">
        {visibleMatches.map((c) => (
          <TopMatchCard key={c.id} correlation={c} />
        ))}
        {isMobile && (
          <Link
            to="/jobs/matches"
            className="flex shrink-0 items-center gap-1 self-center font-medium text-primary text-xs hover:underline"
          >
            {t('match.viewAllMatches')}
            <ArrowRight className="size-3" />
          </Link>
        )}
      </div>
    </div>
  );
}

export { TopMatchesWidget };
