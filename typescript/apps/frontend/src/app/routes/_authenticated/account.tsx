import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { AccountSettings } from '@/pages/account/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/account')({
  staticData: { breadcrumb: 'navigation:sidebar.account' },
  component: AccountPage,
});

function AccountPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="accountSettings">
      <AccountSettings />
    </FeatureErrorBoundary>
  );
}

export { Route };
