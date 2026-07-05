import { useParams } from '@tanstack/react-router';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import {
  JobDetailSkeleton,
  JobDetailView,
  SimilarJobsSection,
  useListing,
  useListings,
} from '@/features/job-search/index.ts';
import type { JobListingResponse } from '@/shared/api/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { useDocumentTitle } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import { PageHeader } from '@/shared/ui/index.ts';
import { PageLayout } from '@/widgets/layout/index.ts';

function JobDetail(): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const { listingId } = useParams({ from: '/_authenticated/jobs/$listingId' });
  const { data: listing, isLoading, error } = useListing(listingId ?? '');

  useDocumentTitle(listing?.title ?? t('pages.detail.title'));

  if (isLoading) {
    return (
      <PageLayout className="space-y-6">
        <JobDetailSkeleton />
      </PageLayout>
    );
  }

  if (error || !listing) {
    return <JobNotFound />;
  }

  return (
    <PageLayout className="space-y-6">
      <PageHeader
        title={listing.title}
        description={listing.company_name ?? ''}
        backTo={ROUTE_PATHS.JOBS.LIST}
        preferHistory={true}
      />
      <JobDetailView listing={listing} />
      <SimilarJobsContent listing={listing} />
    </PageLayout>
  );
}

/** Fetches listings for client-side similar job filtering. Renders nothing while loading. */
function SimilarJobsContent({
  listing,
}: {
  readonly listing: JobListingResponse;
}): JSX.Element | null {
  const { data: listingsData } = useListings({ pageSize: 50 });

  if (!listingsData?.items) {
    return null;
  }

  return <SimilarJobsSection currentListing={listing} allListings={listingsData.items} />;
}

function JobNotFound(): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  return (
    <PageLayout>
      <Card>
        <CardContent className="space-y-4 py-12 text-center">
          <p className="text-muted-foreground">{t('empty.noJobDetail')}</p>
          <Button asChild={true}>
            <a href={ROUTE_PATHS.JOBS.LIST}>{t('common:actions.goBack')}</a>
          </Button>
        </CardContent>
      </Card>
    </PageLayout>
  );
}

export { JobDetail };
