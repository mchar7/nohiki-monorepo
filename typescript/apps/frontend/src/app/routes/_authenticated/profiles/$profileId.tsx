import type { QueryClient } from '@tanstack/react-query';
import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { ProfileDetail } from '@/pages/profiles/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';
import { RoutePendingFallback } from '@/shared/ui/route-pending-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/profiles/$profileId')({
  staticData: { breadcrumb: 'common:features.profileDetail' },
  loader: async ({
    context: { queryClient },
    params: { profileId },
  }: {
    context: { queryClient: QueryClient };
    params: { profileId: string };
  }) => {
    const { profileDetailQueryOptions } = await import('@/features/profile-management/index.ts');
    return queryClient.ensureQueryData(profileDetailQueryOptions(profileId));
  },
  pendingComponent: RoutePendingFallback,
  errorComponent: RouteErrorFallback,
  component: ProfileDetailPage,
});

function ProfileDetailPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="profileDetail">
      <ProfileDetail />
    </FeatureErrorBoundary>
  );
}

export { Route };
