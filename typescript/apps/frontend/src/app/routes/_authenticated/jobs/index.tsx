import type { QueryClient } from '@tanstack/react-query';
import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type ZodTypeAny, z } from 'zod';
import { JobListings } from '@/pages/jobs/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';
import { RouteErrorFallback } from '@/shared/ui/route-error-fallback.tsx';
import { RoutePendingFallback } from '@/shared/ui/route-pending-fallback.tsx';

const PAGE_SIZE = 20;

const jobSearchSchema: ZodTypeAny = z.object({
  page: z.number().int().min(1).optional().default(1),
  sort: z.enum(['posted_at', 'company_name', 'title', 'match_score']).catch('posted_at'),
  dir: z.enum(['asc', 'desc']).catch('desc'),
  source: z.string().optional(),
  company: z.string().optional(),
  q: z.string().optional(),
  workArrangement: z.string().optional(),
  showDismissed: z.boolean().optional(),
  hasSalary: z.boolean().optional(),
  seniority: z.string().optional(),
  dateRange: z.string().optional(),
});

interface JobSearch {
  page?: number;
  sort?: string;
  dir?: string;
  source?: string;
  company?: string;
  q?: string;
  showDismissed?: boolean;
  hasSalary?: boolean;
  workArrangement?: string;
  seniority?: string;
  dateRange?: string;
}

const Route: AnyRoute = createFileRoute('/_authenticated/jobs/')({
  validateSearch: jobSearchSchema,
  loaderDeps: ({ search }: { search: JobSearch }): JobSearch => search,
  loader: async ({
    context: { queryClient },
    deps,
  }: {
    context: { queryClient: QueryClient };
    deps: JobSearch;
  }) => {
    const { listingsQueryOptions } = await import('@/features/job-search/index.ts');
    return queryClient.ensureQueryData(
      listingsQueryOptions({
        page: deps.page,
        pageSize: PAGE_SIZE,
        source: deps.source,
        company: deps.company,
        q: deps.q,
        sort: deps.sort as 'posted_at' | 'company_name' | 'title' | 'match_score' | undefined,
        dir: deps.dir as 'asc' | 'desc' | undefined,
        showDismissed: deps.showDismissed,
        hasSalary: deps.hasSalary,
        workArrangement: deps.workArrangement,
        dateRange: deps.dateRange as '24h' | '7d' | '30d' | undefined,
      }),
    );
  },
  pendingComponent: RoutePendingFallback,
  errorComponent: RouteErrorFallback,
  component: JobListingsPage,
});

function JobListingsPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="jobListings">
      <JobListings />
    </FeatureErrorBoundary>
  );
}

export { Route };
