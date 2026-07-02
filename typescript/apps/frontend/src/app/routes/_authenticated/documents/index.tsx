import type { QueryClient } from '@tanstack/react-query';
import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type ZodTypeAny, z } from 'zod';
import { DocumentList } from '@/pages/documents/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';
import { RoutePendingFallback } from '@/shared/ui/route-pending-fallback.tsx';

const positiveIntPage: ZodTypeAny = z.number().int().min(1);

const documentsSearchSchema: ZodTypeAny = z.object({
  page: positiveIntPage.optional().default(1),
  sort: z.enum(['status', 'request_id', 'name', 'size']).catch('status'),
  dir: z.enum(['asc', 'desc']).catch('asc'),
  tab: z.enum(['all', 'uploaded', 'generated']).catch('all'),
  docPage: positiveIntPage.optional().default(1),
  attachPage: positiveIntPage.optional().default(1),
});

const Route: AnyRoute = createFileRoute('/_authenticated/documents/')({
  validateSearch: documentsSearchSchema,
  loader: async ({ context: { queryClient } }: { context: { queryClient: QueryClient } }) => {
    const [{ documentsListQueryOptions }, { attachmentsListQueryOptions }] = await Promise.all([
      import('@/features/document-generation/index.ts'),
      import('@/features/attachments/index.ts'),
    ]);
    await Promise.all([
      queryClient.ensureQueryData(documentsListQueryOptions),
      queryClient.ensureQueryData(attachmentsListQueryOptions),
    ]);
  },
  pendingComponent: RoutePendingFallback,
  errorComponent: RouteErrorFallback,
  component: DocumentsPage,
});

function DocumentsPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="documents">
      <DocumentList />
    </FeatureErrorBoundary>
  );
}

export { Route };
