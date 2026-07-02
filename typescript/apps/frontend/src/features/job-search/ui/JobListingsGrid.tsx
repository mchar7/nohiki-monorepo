import { Briefcase } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { JobListingResponse } from '@/shared/api';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/shared/ui/empty.tsx';
import { CardGridSkeleton } from '@/shared/ui/index.ts';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { JobListingCard } from './JobListingCard.tsx';

interface CorrelationInfo {
  readonly id: string;
  readonly fitScore: number;
  readonly status: string;
}

interface JobListingsGridProps {
  readonly listings: readonly JobListingResponse[];
  readonly isLoading: boolean;
  readonly error: unknown;
  readonly searchQuery?: string | null;
  readonly correlationMap?: ReadonlyMap<string, CorrelationInfo>;
  readonly onSave?: (correlationId: string) => void;
  readonly onDismiss?: (correlationId: string) => void;
}

function JobListingsGrid({
  listings,
  isLoading,
  error,
  searchQuery,
  correlationMap,
  onSave,
  onDismiss,
}: JobListingsGridProps): JSX.Element {
  if (isLoading) {
    return <JobListingsSkeleton />;
  }

  if (error) {
    return <JobListingsError />;
  }

  if (listings.length === 0) {
    return <JobListingsEmpty />;
  }

  return (
    <ul aria-label="Job listings" className="grid list-none gap-4 p-0">
      {listings.map((listing) => {
        const correlation = correlationMap?.get(listing.id);
        return (
          <li key={listing.id}>
            <JobListingCard
              listing={listing}
              searchQuery={searchQuery}
              matchScore={correlation?.fitScore}
              correlationId={correlation?.id}
              correlationStatus={correlation?.status}
              onSave={onSave}
              onDismiss={onDismiss}
            />
          </li>
        );
      })}
    </ul>
  );
}

function JobListingsSkeleton(): JSX.Element {
  return (
    <CardGridSkeleton count={5} columns="">
      {(key: string) => (
        <Card key={key}>
          <div className="space-y-4 p-6">
            <div className="flex items-start justify-between">
              <div className="space-y-2">
                <Skeleton className="h-6 w-64" />
                <Skeleton className="h-4 w-32" />
              </div>
              <Skeleton className="h-6 w-20 rounded-full" />
            </div>
            <div className="flex gap-4">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 w-16" />
            </div>
            <Skeleton className="h-16 w-full" />
            <div className="flex gap-2">
              <Skeleton className="h-6 w-16 rounded-full" />
              <Skeleton className="h-6 w-20 rounded-full" />
              <Skeleton className="h-6 w-14 rounded-full" />
            </div>
          </div>
        </Card>
      )}
    </CardGridSkeleton>
  );
}

function JobListingsError(): JSX.Element {
  const { t } = useTranslation(['common']);

  return (
    <Card>
      <CardContent className="py-12 text-center">
        <p className="text-destructive">{t('common:errors.generic')}</p>
      </CardContent>
    </Card>
  );
}

function JobListingsEmpty(): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  return (
    <Empty
      role="status"
      aria-live="polite"
      aria-label={t('common:a11y.noJobsFound')}
      className="rounded-lg border"
    >
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Briefcase className="size-6" />
        </EmptyMedia>
        <EmptyTitle>{t('empty.noListings')}</EmptyTitle>
        <EmptyDescription>{t('empty.noListingsDescription')}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

export { JobListingsGrid };
