import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { ProfileCreate } from '@/pages/profiles/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/profiles/new')({
  staticData: { breadcrumb: 'navigation:sidebar.profiles.create' },
  component: ProfileCreatePage,
});

function ProfileCreatePage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="profileCreate">
      <ProfileCreate />
    </FeatureErrorBoundary>
  );
}

export { Route };
