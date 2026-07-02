import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type ZodTypeAny, z } from 'zod';
import { GeneratePage } from '@/pages/documents';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';

const generateSearchSchema: ZodTypeAny = z.object({
  templateId: z.string().optional(),
});

const Route: AnyRoute = createFileRoute('/_authenticated/documents/generate')({
  staticData: { breadcrumb: 'Generate' },
  validateSearch: generateSearchSchema,
  errorComponent: RouteErrorFallback,
  component: GeneratePageWrapper,
});

function GeneratePageWrapper(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="documents">
      <GeneratePage />
    </FeatureErrorBoundary>
  );
}

export { Route };
