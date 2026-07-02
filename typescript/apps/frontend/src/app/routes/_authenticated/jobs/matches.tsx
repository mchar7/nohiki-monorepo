import { type AnyRoute, createFileRoute, Outlet } from '@tanstack/react-router';
import type { JSX } from 'react';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/jobs/matches')({
  staticData: { breadcrumb: 'navigation:sidebar.jobs.matches' },
  component: MatchesLayout,
  errorComponent: RouteErrorFallback,
});

function MatchesLayout(): JSX.Element {
  return <Outlet />;
}

export { Route };
