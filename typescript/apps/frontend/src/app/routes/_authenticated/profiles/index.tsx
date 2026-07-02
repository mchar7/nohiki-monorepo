import type { QueryClient } from '@tanstack/react-query';
import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { ProfileList } from '@/pages/profiles/index.ts';
import { listSearchSchema } from '@/shared/lib/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';
import { RoutePendingFallback } from '@/shared/ui/route-pending-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/profiles/')({
  validateSearch: listSearchSchema(['name', 'keywords']),
  loader: async ({ context: { queryClient } }: { context: { queryClient: QueryClient } }) => {
    const { profilesListQueryOptions } = await import('@/features/profile-management/index.ts');
    return queryClient.ensureQueryData(profilesListQueryOptions);
  },
  pendingComponent: RoutePendingFallback,
  errorComponent: RouteErrorFallback,
  component: ProfileListPage,
});

function ProfileListPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="profileList">
      <ProfileList />
    </FeatureErrorBoundary>
  );
}

export { Route };
