import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import {
  TopMatchesWidget,
  useMyCorrelations,
  useRecordFeedback,
} from '@/features/job-matching/index.ts';
import {
  type JobListingsFilters,
  JobListingsFiltersBar,
  JobListingsGrid,
  type JobSortField,
  useJobListingsFilters,
  useListings,
} from '@/features/job-search/index.ts';
import type { JobCorrelationResponse, JobListingResponse } from '@/shared/api';
import {
  useDebouncedValue,
  useDocumentTitle,
  useIsMobileLayout,
  useMainScrollRef,
  usePullToRefresh,
} from '@/shared/lib/index.ts';
import { DensityToggle } from '@/shared/ui/density-toggle.tsx';
import { PageHeader } from '@/shared/ui/index.ts';
import { ListPagination } from '@/shared/ui/list-pagination.tsx';
import { PullIndicator } from '@/shared/ui/pull-indicator.tsx';
import { SortSelect } from '@/shared/ui/sort-select.tsx';
import type { SortDirection, SortOption } from '@/shared/ui/sort-select.types.ts';
import { PageLayout } from '@/widgets/layout/index.ts';
import {
  buildCorrelationMap,
  buildListingsQuery,
  type CorrelationMap,
  EMPTY_CORRELATION_MAP,
  PAGE_SIZE,
} from './jobListingsUtils.ts';

const CORRELATIONS_PAGE_SIZE: number = 200;

const JOB_SORT_OPTIONS: readonly SortOption[] = [
  { value: 'posted_at', label: 'Date Posted' },
  { value: 'company_name', label: 'Company' },
  { value: 'title', label: 'Title' },
  { value: 'match_score', label: 'Match Score' },
];

/** Toolbar with filter bar and sort controls */
function ListingsToolbar({
  filters,
  onSourceChange,
  onQueryChange,
  onClear,
  hasActiveFilters,
  activeFilterCount,
  sortField,
  sortDirection,
  onSortFieldChange,
  onSortDirectionChange,
  showDismissed,
  onShowDismissedChange,
  hasSalary,
  onHasSalaryChange,
  onWorkArrangementChange,
  onSeniorityChange,
  onDateRangeChange,
}: {
  readonly filters: JobListingsFilters;
  readonly onSourceChange: (source: string | null) => void;
  readonly onQueryChange: (q: string | null) => void;
  readonly onClear: () => void;
  readonly hasActiveFilters: boolean;
  readonly activeFilterCount: number;
  readonly sortField: JobSortField;
  readonly sortDirection: SortDirection;
  readonly onSortFieldChange: (value: string) => void;
  readonly onSortDirectionChange: (dir: SortDirection) => void;
  readonly showDismissed: boolean;
  readonly onShowDismissedChange: (show: boolean) => void;
  readonly hasSalary: boolean;
  readonly onHasSalaryChange: (hasSalary: boolean) => void;
  readonly onWorkArrangementChange: (workArrangement: string | null) => void;
  readonly onSeniorityChange: (seniority: string | null) => void;
  readonly onDateRangeChange: (dateRange: string | null) => void;
}): JSX.Element {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <JobListingsFiltersBar
        filters={filters}
        onSourceChange={onSourceChange}
        onQueryChange={onQueryChange}
        onClear={onClear}
        hasActiveFilters={hasActiveFilters}
        activeFilterCount={activeFilterCount}
        showDismissed={showDismissed}
        onShowDismissedChange={onShowDismissedChange}
        hasSalary={hasSalary}
        onHasSalaryChange={onHasSalaryChange}
        onWorkArrangementChange={onWorkArrangementChange}
        onSeniorityChange={onSeniorityChange}
        onDateRangeChange={onDateRangeChange}
      />
      <div className="flex items-center gap-2">
        <SortSelect
          options={JOB_SORT_OPTIONS}
          value={sortField}
          direction={sortDirection}
          onValueChange={onSortFieldChange}
          onDirectionChange={onSortDirectionChange}
        />
        <DensityToggle />
      </div>
    </div>
  );
}

/** Encapsulates listings data fetching and pull-to-refresh state. */
interface ListingsData {
  data: { items: JobListingResponse[]; total: number } | undefined;
  items: readonly JobListingResponse[];
  isLoading: boolean;
  isFetching: boolean;
  dataUpdatedAt: number;
  error: unknown;
  isRefreshing: boolean;
  pullDistance: number;
}

/** Encapsulates listings data fetching and pull-to-refresh state. */
function useListingsData(filters: JobListingsFilters): ListingsData {
  const debouncedQ = useDebouncedValue(filters.q);
  const { data, isLoading, isFetching, dataUpdatedAt, error, refetch } = useListings(
    buildListingsQuery(filters, debouncedQ),
  );
  const isMobile = useIsMobileLayout();
  const mainScrollRef = useMainScrollRef();
  const { isRefreshing, pullDistance } = usePullToRefresh({
    ref: mainScrollRef,
    onRefresh: refetch,
    enabled: isMobile,
  });
  return {
    data,
    items: data?.items ?? [],
    isLoading,
    isFetching,
    dataUpdatedAt,
    error,
    isRefreshing,
    pullDistance,
  };
}

/** Encapsulates save/dismiss feedback actions for correlated job listings. */
interface CorrelationActions {
  readonly handleSave: (correlationId: string) => void;
  readonly handleDismiss: (correlationId: string) => void;
}

/** Encapsulates save/dismiss feedback actions for correlated job listings. */
function useCorrelationActions(correlationMap: CorrelationMap): CorrelationActions {
  const { mutate: recordFeedback } = useRecordFeedback();

  const handleSave = (correlationId: string): void => {
    const current = correlationMap.get(correlationId);
    const feedbackType = current?.status === 'SAVED' ? 'VIEWED' : 'SAVED';
    recordFeedback({
      params: { path: { correlation_id: correlationId } },
      body: { feedback_type: feedbackType },
    });
  };

  const handleDismiss = (correlationId: string): void => {
    recordFeedback({
      params: { path: { correlation_id: correlationId } },
      body: { feedback_type: 'DISMISSED' },
    });
  };

  return { handleSave, handleDismiss };
}

interface JobListingsPageData {
  correlationsData: { items: readonly JobCorrelationResponse[] } | undefined;
  correlationMap: CorrelationMap;
  handleSave: (id: string) => void;
  handleDismiss: (id: string) => void;
  listings: ListingsData;
  visibleListings: readonly JobListingResponse[];
}

function useJobListingsPageData(filters: JobListingsFilters): JobListingsPageData {
  const { data: correlationsData } = useMyCorrelations({ pageSize: CORRELATIONS_PAGE_SIZE });
  const correlationMap = correlationsData?.items
    ? buildCorrelationMap(correlationsData.items)
    : EMPTY_CORRELATION_MAP;
  const { handleSave, handleDismiss } = useCorrelationActions(correlationMap);
  const listings = useListingsData(filters);
  return {
    correlationsData,
    correlationMap,
    handleSave,
    handleDismiss,
    listings,
    visibleListings: listings.items,
  };
}

export function JobListings(): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const filterState = useJobListingsFilters();
  const { filters } = filterState;
  useDocumentTitle(t('pages.listings.title'));
  const pageData = useJobListingsPageData(filters);
  const { correlationsData, correlationMap, listings, visibleListings } = pageData;
  return (
    <PageLayout className="space-y-6">
      <PullIndicator pullDistance={listings.pullDistance} isRefreshing={listings.isRefreshing} />
      <PageHeader
        title={t('jobs:pages.listings.title')}
        description={t('jobs:pages.listings.description')}
      />
      {correlationsData?.items ? <TopMatchesWidget correlations={correlationsData.items} /> : null}
      <ListingsToolbar
        filters={filters}
        onSourceChange={filterState.setSource}
        onQueryChange={filterState.setQuery}
        onClear={filterState.clearFilters}
        hasActiveFilters={filterState.hasActiveFilters}
        activeFilterCount={filterState.activeFilterCount}
        sortField={filters.sort}
        sortDirection={filters.dir}
        onSortFieldChange={(v: string) => filterState.setSortField(v as JobSortField)}
        onSortDirectionChange={filterState.setSortDirection}
        showDismissed={filters.showDismissed}
        onShowDismissedChange={filterState.setShowDismissed}
        onWorkArrangementChange={filterState.setWorkArrangement}
        onSeniorityChange={filterState.setSeniority}
        onDateRangeChange={filterState.setDateRange}
        hasSalary={filters.hasSalary}
        onHasSalaryChange={filterState.setHasSalary}
      />
      <JobListingsGrid
        listings={visibleListings}
        isLoading={listings.isLoading}
        error={listings.error}
        searchQuery={filters.q}
        correlationMap={correlationMap}
        onSave={pageData.handleSave}
        onDismiss={pageData.handleDismiss}
      />
      <ListPagination
        page={filters.page}
        pageSize={PAGE_SIZE}
        total={listings.data ? listings.data.total : 0}
        onPageChange={filterState.setPage}
      />
    </PageLayout>
  );
}
