import { Link } from '@tanstack/react-router';

/** Number of skeleton rows shown during loading */
const LOADING_SKELETON_COUNT: number = 3;
/** Maximum number of recent matches to show in the dashboard widget */
const RECENT_MATCHES_DISPLAY_LIMIT: number = 5;
/** Bullet separator between location and timestamp */
const SEPARATOR_BULLET: string = '\u2022';

import { ArrowRight, Building2, MapPin, Star, TrendingUp } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import type { JobCorrelationResponse } from '@/shared/api';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { Progress } from '@/shared/ui/progress.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import {
  formatRelativeTime,
  getProgressClassName,
  getScoreClassName,
  isWithinWeek,
} from '../lib/index.ts';

interface DashboardRecentMatchesProps {
  readonly correlations: readonly JobCorrelationResponse[];
  readonly isLoading?: boolean;
}

interface MatchCardProps {
  readonly correlation: JobCorrelationResponse;
}

function MatchCard({ correlation }: MatchCardProps): JSX.Element {
  const { t } = useTranslation('dashboard');
  const matchScore = Math.round(correlation.fit_score);
  const isNew = isWithinWeek(correlation.created_at);
  const postedAt = formatRelativeTime(correlation.created_at);
  const newLabel = t('recentMatches.new');
  const unknownCompany = t('recentMatches.unknownCompany');
  const remoteLabel = t('recentMatches.remote');

  return (
    <Link
      to="/jobs/matches/$correlationId"
      params={{ correlationId: correlation.id }}
      className="group flex items-start gap-3 rounded-lg border p-3 transition-colors hover:bg-accent/50"
    >
      <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
        <Building2 className="size-4 text-primary" />
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center gap-2">
          <p className="truncate font-medium">{correlation.listing_title}</p>
          {isNew && (
            <Badge variant="secondary" className="match-new-badge text-xs">
              {newLabel}
            </Badge>
          )}
        </div>
        <p className="truncate text-muted-foreground text-sm">
          {correlation.listing_company ?? unknownCompany}
        </p>
        <div className="flex items-center gap-2 text-muted-foreground text-xs">
          <MapPin className="size-3" />
          <span className="truncate">{correlation.listing_location ?? remoteLabel}</span>
          <span className="text-muted-foreground/50">{SEPARATOR_BULLET}</span>
          <span>{postedAt}</span>
        </div>
      </div>
      <div className="flex flex-col items-end gap-1">
        <span className={`font-semibold tabular-nums ${getScoreClassName(matchScore)}`}>
          {`${matchScore} / 100`}
        </span>
        <Progress value={matchScore} className={`h-1.5 w-16 ${getProgressClassName(matchScore)}`} />
      </div>
    </Link>
  );
}

function EmptyState(): JSX.Element {
  const { t } = useTranslation('dashboard');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Star className="size-5 text-primary" />
          {t('recentMatches.title')}
        </CardTitle>
        <CardDescription>{t('recentMatches.subtitle')}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-muted">
            <TrendingUp className="size-6 text-muted-foreground" />
          </div>
          <p className="font-medium text-muted-foreground">{t('recentMatches.emptyTitle')}</p>
          <p className="mt-1 text-muted-foreground/70 text-sm">
            {t('recentMatches.emptyDescription')}
          </p>
          <Button asChild={true} className="mt-4" size="sm">
            <Link to="/profiles/new">{t('recentMatches.createProfile')}</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function LoadingSkeleton(): JSX.Element {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <Skeleton className="h-6 w-40" />
          <Skeleton className="mt-1 h-4 w-32" />
        </div>
        <Skeleton className="h-8 w-20" />
      </CardHeader>
      <CardContent className="space-y-4">
        {Array.from({ length: LOADING_SKELETON_COUNT }, (_, i) => i).map((i) => (
          <div key={i} className="flex items-start gap-4 rounded-lg border p-4">
            <Skeleton className="size-10 rounded" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-3 w-32" />
              <Skeleton className="h-3 w-24" />
            </div>
            <Skeleton className="h-6 w-12" />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export function DashboardRecentMatches({
  correlations,
  isLoading,
}: DashboardRecentMatchesProps): JSX.Element {
  const { t } = useTranslation('dashboard');

  if (isLoading) {
    return <LoadingSkeleton />;
  }

  if (correlations.length === 0) {
    return <EmptyState />;
  }

  const displayedMatches = correlations.slice(0, RECENT_MATCHES_DISPLAY_LIMIT);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <div className="flex size-7 items-center justify-center rounded-md bg-primary/10">
            <Star className="size-4 text-primary" />
          </div>
          {t('recentMatches.title')}
        </CardTitle>
        <Button variant="ghost" size="sm" asChild={true}>
          <Link to="/jobs/matches" className="gap-1">
            {t('recentMatches.viewAll')}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="space-y-2 pt-0">
        {displayedMatches.map((correlation) => (
          <MatchCard key={correlation.id} correlation={correlation} />
        ))}
      </CardContent>
    </Card>
  );
}
