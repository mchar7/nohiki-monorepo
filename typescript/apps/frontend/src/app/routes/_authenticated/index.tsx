import type { QueryClient } from '@tanstack/react-query';
import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { Dashboard } from '@/pages/dashboard/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';
import { RoutePendingFallback } from '@/shared/ui/route-pending-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/')({
  loader: async ({ context: { queryClient } }: { context: { queryClient: QueryClient } }) => {
    const [
      { profilesListQueryOptions },
      { correlationsQueryOptions },
      { documentsListQueryOptions },
    ] = await Promise.all([
      import('@/features/profile-management/index.ts'),
      import('@/features/job-matching/index.ts'),
      import('@/features/document-generation/index.ts'),
    ]);
    return Promise.all([
      queryClient.ensureQueryData(profilesListQueryOptions),
      queryClient.ensureQueryData(correlationsQueryOptions({ page: 1, pageSize: 5 })),
      queryClient.ensureQueryData(documentsListQueryOptions),
    ]);
  },
  staticData: { breadcrumb: 'navigation:sidebar.dashboard' },
  pendingComponent: RoutePendingFallback,
  errorComponent: RouteErrorFallback,
  component: DashboardPage,
});

function DashboardPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="dashboard">
      <Dashboard />
    </FeatureErrorBoundary>
  );
}

export { Route };
