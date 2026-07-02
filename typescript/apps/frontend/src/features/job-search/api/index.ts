import { $api, CACHE_CONFIG } from '@/shared/api/index.ts';

const DEFAULT_LISTINGS_PAGE: number = 1;
const DEFAULT_LISTINGS_PAGE_SIZE: number = 20;

type ListingsSortField = 'posted_at' | 'company_name' | 'title' | 'match_score';
type ListingsSortDirection = 'asc' | 'desc';

interface ListingsFilters {
  page?: number | undefined;
  pageSize?: number | undefined;
  source?: string | undefined;
  company?: string | undefined;
  q?: string | undefined;
  sort?: ListingsSortField | undefined;
  dir?: ListingsSortDirection | undefined;
  showDismissed?: boolean | undefined;
  hasSalary?: boolean | undefined;
  workArrangement?: string | undefined;
  seniority?: string | undefined;
  dateRange?: '24h' | '7d' | '30d' | undefined;
}

function listingsQueryOptions(filters: ListingsFilters = {}) {
  const {
    page = DEFAULT_LISTINGS_PAGE,
    pageSize = DEFAULT_LISTINGS_PAGE_SIZE,
    source,
    company,
    q,
    sort = 'posted_at',
    dir = 'desc',
    showDismissed = false,
    hasSalary = false,
    workArrangement,
    seniority,
    dateRange,
  } = filters;

  return $api.queryOptions(
    'get',
    '/api/v1/listings',
    {
      params: {
        query: {
          page,
          page_size: pageSize,
          source: source ?? null,
          company: company ?? null,
          q: q ?? null,
          sort,
          dir,
          show_dismissed: showDismissed,
          has_salary: hasSalary,
          work_arrangement: workArrangement ?? null,
          seniority: seniority ?? null,
          date_range: dateRange ?? null,
        },
      },
    },
    { ...CACHE_CONFIG.DYNAMIC },
  );
}

function useListings(filters: ListingsFilters = {}) {
  const {
    page = DEFAULT_LISTINGS_PAGE,
    pageSize = DEFAULT_LISTINGS_PAGE_SIZE,
    source,
    company,
    q,
    sort = 'posted_at',
    dir = 'desc',
    showDismissed = false,
    hasSalary = false,
    workArrangement,
    seniority,
    dateRange,
  } = filters;

  return $api.useQuery(
    'get',
    '/api/v1/listings',
    {
      params: {
        query: {
          page,
          page_size: pageSize,
          source: source ?? null,
          company: company ?? null,
          q: q ?? null,
          sort,
          dir,
          show_dismissed: showDismissed,
          has_salary: hasSalary,
          work_arrangement: workArrangement ?? null,
          seniority: seniority ?? null,
          date_range: dateRange ?? null,
        },
      },
    },
    { ...CACHE_CONFIG.DYNAMIC },
  );
}
function useInfiniteListings(filters: Omit<ListingsFilters, 'page'> = {}) {
  const {
    pageSize = DEFAULT_LISTINGS_PAGE_SIZE,
    source,
    company,
    q,
    sort = 'posted_at',
    dir = 'desc',
    showDismissed = false,
    hasSalary = false,
    workArrangement,
    seniority,
    dateRange,
  } = filters;

  return $api.useInfiniteQuery(
    'get',
    '/api/v1/listings',
    {
      params: {
        query: {
          page_size: pageSize,
          source: source ?? null,
          company: company ?? null,
          q: q ?? null,
          sort,
          dir,
          show_dismissed: showDismissed,
          has_salary: hasSalary,
          work_arrangement: workArrangement ?? null,
          seniority: seniority ?? null,
          date_range: dateRange ?? null,
        },
      },
    },
    {
      pageParamName: 'page',
      initialPageParam: 1,
      getNextPageParam: (lastPage, allPages) => {
        const totalFetched = allPages.reduce((acc, page) => acc + (page?.items.length ?? 0), 0);
        return totalFetched < (lastPage?.total ?? 0) ? allPages.length + 1 : undefined;
      },
      ...CACHE_CONFIG.DYNAMIC,
    },
  );
}

function useListing(listingId: string) {
  return $api.useQuery(
    'get',
    '/api/v1/listings/{listing_id}',
    { params: { path: { listing_id: listingId } } },
    { enabled: Boolean(listingId), ...CACHE_CONFIG.DYNAMIC },
  );
}

export { listingsQueryOptions, useInfiniteListings, useListing, useListings };
