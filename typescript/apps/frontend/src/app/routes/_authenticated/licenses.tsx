import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { Licenses } from '@/pages/legal/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/licenses')({
  staticData: { breadcrumb: 'common:features.licenses' },
  component: LicensesPage,
});

function LicensesPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="licenses">
      <Licenses />
    </FeatureErrorBoundary>
  );
}

export { Route };
