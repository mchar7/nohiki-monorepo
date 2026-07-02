import type { QueryClient } from '@tanstack/react-query';
import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { MatchDetail } from '@/pages/jobs/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';
import { RoutePendingFallback } from '@/shared/ui/route-pending-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/jobs/matches/$correlationId')({
  staticData: { breadcrumb: 'common:features.matchDetail' },
  loader: async ({
    context: { queryClient },
    params: { correlationId },
  }: {
    context: { queryClient: QueryClient };
    params: { correlationId: string };
  }) => {
    const { correlationDetailQueryOptions } = await import('@/features/job-matching/index.ts');
    return queryClient.ensureQueryData(correlationDetailQueryOptions(correlationId));
  },
  pendingComponent: RoutePendingFallback,
  errorComponent: RouteErrorFallback,
  component: MatchDetailPage,
});

function MatchDetailPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="matchDetail">
      <MatchDetail />
    </FeatureErrorBoundary>
  );
}

export { Route };
