import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { JobDetail } from '@/pages/jobs/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/jobs/$listingId')({
  staticData: { breadcrumb: 'common:features.jobDetail' },
  component: JobDetailPage,
});

function JobDetailPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="jobDetail">
      <JobDetail />
    </FeatureErrorBoundary>
  );
}

export { Route };
