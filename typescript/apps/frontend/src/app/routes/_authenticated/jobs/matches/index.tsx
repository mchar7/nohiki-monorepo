import type { QueryClient } from '@tanstack/react-query';
import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type ZodTypeAny, z } from 'zod';
import { MyMatches } from '@/pages/jobs/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';
import { RoutePendingFallback } from '@/shared/ui/route-pending-fallback.tsx';

const matchesSearchSchema: ZodTypeAny = z.object({
  page: z.number().int().min(1).optional().default(1),
  prefId: z.string().optional(),
  minScore: z.number().min(0).max(100).optional(),
});

interface MatchesSearch {
  page?: number;
  prefId?: string;
  minScore?: number;
}

const Route: AnyRoute = createFileRoute('/_authenticated/jobs/matches/')({
  validateSearch: matchesSearchSchema,
  loaderDeps: ({ search }: { search: MatchesSearch }): MatchesSearch => search,
  loader: async ({
    context: { queryClient },
    deps,
  }: {
    context: { queryClient: QueryClient };
    deps: MatchesSearch;
  }) => {
    const [{ profilesListQueryOptions }, { correlationsQueryOptions }] = await Promise.all([
      import('@/features/profile-management/index.ts'),
      import('@/features/job-matching/index.ts'),
    ]);
    return Promise.all([
      queryClient.ensureQueryData(profilesListQueryOptions),
      queryClient.ensureQueryData(
        correlationsQueryOptions({ page: deps.page, prefId: deps.prefId, minScore: deps.minScore }),
      ),
    ]);
  },
  pendingComponent: RoutePendingFallback,
  errorComponent: RouteErrorFallback,
  component: MyMatchesPage,
});

function MyMatchesPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="jobMatches">
      <MyMatches />
    </FeatureErrorBoundary>
  );
}

export { Route };
