import type { QueryClient } from '@tanstack/react-query';
import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { Editor } from '@/pages/omakase/editor/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';
import { RoutePendingFallback } from '@/shared/ui/route-pending-fallback.tsx';

const Route: AnyRoute = createFileRoute('/_authenticated/documents/editor/$datasetId')({
  staticData: { breadcrumb: 'Editor' },
  loader: async ({ context: { queryClient } }: { context: { queryClient: QueryClient } }) => {
    const { templateFamiliesQueryOptions } = await import(
      '@features/omakase/document-builder/index.ts'
    );
    return queryClient.ensureQueryData(templateFamiliesQueryOptions);
  },
  pendingComponent: RoutePendingFallback,
  errorComponent: RouteErrorFallback,
  component: EditorWithDatasetPage,
});

function EditorWithDatasetPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="documentEditor">
      <Editor />
    </FeatureErrorBoundary>
  );
}

export { Route };
