import type { JSX, LazyExoticComponent } from 'react';
import { lazy, Suspense } from 'react';

import { Card, CardContent, CardHeader } from '@/shared/ui/card.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { CommonMissingSkillsWidget } from './CommonMissingSkillsWidget.tsx';
import type {
  DashboardActivityChartProps,
  ReturningUserDashboardProps,
} from './Dashboard.types.ts';
import { DashboardActionItems } from './DashboardActionItems.tsx';
import { DashboardHighlights } from './DashboardHighlights.tsx';
import { DashboardNewMatchesBanner } from './DashboardNewMatchesBanner.tsx';
import { DashboardRecentMatches } from './DashboardRecentMatches.tsx';
import { DashboardStatsCards } from './DashboardStatsCards.tsx';

const LazyDashboardActivityChart: LazyExoticComponent<
  (props: DashboardActivityChartProps) => JSX.Element
> = lazy(() =>
  import('./DashboardActivityChart.tsx').then((m) => ({
    default: m.DashboardActivityChart,
  })),
);

/** Chart-sized skeleton shown while Recharts loads. */
function ChartFallback(): JSX.Element {
  return (
    <Card className="@container/card">
      <CardHeader className="relative">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="mt-1 h-4 w-64" />
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        <Skeleton className="h-44 w-full" />
      </CardContent>
    </Card>
  );
}

/**
 * Composite dashboard view for returning users (stages 'active' and 'getting-started').
 *
 * Composes: banner → stats → highlights → action items + skills widget → chart → recent matches.
 */
function ReturningUserDashboard({
  stats,
  correlations,
  profiles,
  documents,
  topMatch,
  latestDocument,
  newMatchCount,
  isLoading,
}: ReturningUserDashboardProps): JSX.Element {
  const [firstProfile] = profiles;
  const hasSkills = firstProfile?.user_skills ? firstProfile.user_skills.length > 0 : false;

  return (
    <div className="space-y-6">
      <DashboardNewMatchesBanner newMatchCount={newMatchCount} />

      <DashboardStatsCards stats={stats} isLoading={isLoading} />

      <DashboardHighlights topMatch={topMatch} latestDocument={latestDocument} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <DashboardActionItems
          profiles={profiles}
          correlations={correlations}
          documents={documents}
        />
        <CommonMissingSkillsWidget hasSkills={hasSkills} profileId={firstProfile?.id} />
      </div>

      <Suspense fallback={<ChartFallback />}>
        <LazyDashboardActivityChart correlations={correlations} isLoading={isLoading} />
      </Suspense>

      <DashboardRecentMatches correlations={correlations} isLoading={isLoading} />
    </div>
  );
}

export { ReturningUserDashboard };
