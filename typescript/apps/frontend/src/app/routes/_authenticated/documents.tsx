import { type AnyRoute, createFileRoute, Outlet } from '@tanstack/react-router';
import type { JSX } from 'react';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/documents')({
  staticData: { breadcrumb: 'navigation:sidebar.documents.title' },
  component: DocumentsLayout,
  errorComponent: RouteErrorFallback,
});

function DocumentsLayout(): JSX.Element {
  return <Outlet />;
}

export { Route };
