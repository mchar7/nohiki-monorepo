import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type LazyExoticComponent, lazy, Suspense } from 'react';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { LoadingSpinner } from '@/shared/ui/loading-spinner.tsx';

const LazyTemplateStudio: LazyExoticComponent<() => JSX.Element> = lazy(() =>
  import('@/pages/omakase/templates/index.ts').then((m) => ({ default: m.TemplateStudio })),
);

const Route: AnyRoute = createFileRoute('/_authenticated/documents/templates/studio')({
  staticData: { breadcrumb: 'Studio' },
  component: TemplateStudioPage,
});

function TemplateStudioPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="omakaseTemplates">
      <Suspense fallback={<LoadingSpinner size="lg" text="Loading Template Studio..." />}>
        <LazyTemplateStudio />
      </Suspense>
    </FeatureErrorBoundary>
  );
}

export { Route };
