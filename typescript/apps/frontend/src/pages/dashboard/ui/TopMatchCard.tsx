import { Link } from '@tanstack/react-router';
import { ArrowRight, Search, Trophy } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { ROUTE_PATHS } from '@/shared/config';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/index.ts';
import { getScoreClassName } from '../lib/utils.ts';
import type { TopMatchCardProps } from './Dashboard.types.ts';

function TopMatchEmptyState(): JSX.Element {
  const { t } = useTranslation('dashboard');

  return (
    <CardContent>
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-muted">
          <Search className="size-6 text-muted-foreground" />
        </div>
        <p className="font-medium text-muted-foreground">{t('highlights.topMatch.emptyTitle')}</p>
        <p className="mt-1 text-muted-foreground/70 text-sm">
          {t('highlights.topMatch.emptyDescription')}
        </p>
        <Button asChild={true} className="mt-4" size="sm">
          <Link to={ROUTE_PATHS.JOBS.LIST}>{t('highlights.topMatch.browseJobs')}</Link>
        </Button>
      </div>
    </CardContent>
  );
}

function TopMatchCard({ correlation }: TopMatchCardProps): JSX.Element {
  const { t } = useTranslation('dashboard');
  const score = correlation ? Math.round(correlation.fit_score) : 0;

  return (
    <section aria-label={t('highlights.topMatch.ariaLabel')}>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <div className="flex size-7 items-center justify-center rounded-md bg-primary/10">
              <Trophy className="size-4 text-primary" />
            </div>
            {t('highlights.topMatch.title')}
          </CardTitle>
        </CardHeader>
        {correlation ? (
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <p className="font-semibold">{correlation.listing_title}</p>
              <p className="text-muted-foreground text-sm">{correlation.listing_company}</p>
              {correlation.listing_location ? (
                <p className="text-muted-foreground/70 text-xs">{correlation.listing_location}</p>
              ) : null}
            </div>
            <div className="flex items-center justify-between">
              <Badge className={getScoreClassName(score)}>{`${score} / 100`}</Badge>
              <Button variant="ghost" size="sm" asChild={true}>
                <Link
                  to={ROUTE_PATHS.JOBS.MATCH_DETAIL}
                  params={{ correlationId: correlation.id }}
                  className="gap-1"
                >
                  {t('highlights.topMatch.viewMatch')}
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </div>
          </CardContent>
        ) : (
          <TopMatchEmptyState />
        )}
      </Card>
    </section>
  );
}

export { TopMatchCard };
