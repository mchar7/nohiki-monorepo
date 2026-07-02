import { type AnyRoute, createFileRoute, Outlet } from '@tanstack/react-router';
import type { JSX } from 'react';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/profiles')({
  staticData: { breadcrumb: 'navigation:sidebar.profiles.title' },
  component: ProfilesLayout,
  errorComponent: RouteErrorFallback,
});

function ProfilesLayout(): JSX.Element {
  return <Outlet />;
}

export { Route };
