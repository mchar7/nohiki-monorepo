import { type AnyRoute, createFileRoute, Outlet } from '@tanstack/react-router';
import type { JSX } from 'react';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/jobs')({
  staticData: { breadcrumb: 'navigation:sidebar.jobs.title' },
  component: JobsLayout,
  errorComponent: RouteErrorFallback,
});

function JobsLayout(): JSX.Element {
  return <Outlet />;
}

export { Route };
