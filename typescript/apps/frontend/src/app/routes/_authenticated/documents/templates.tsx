import { type AnyRoute, createFileRoute, Outlet } from '@tanstack/react-router';
import type { JSX } from 'react';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/documents/templates')({
  staticData: { breadcrumb: 'Templates' },
  component: TemplatesLayout,
  errorComponent: RouteErrorFallback,
});

function TemplatesLayout(): JSX.Element {
  return <Outlet />;
}

export { Route };
