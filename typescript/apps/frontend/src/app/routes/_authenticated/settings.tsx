import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { Settings } from '@/pages/settings/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/settings')({
  staticData: { breadcrumb: 'common:features.settings' },
  component: SettingsPage,
});

function SettingsPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="settings">
      <Settings />
    </FeatureErrorBoundary>
  );
}

export { Route };
