import type {
  JobDateRange,
  JobListingsFilters,
  JobSortField,
} from '@/features/job-search/index.ts';

interface CorrelationInfo {
  readonly id: string;
  readonly fitScore: number;
  readonly status: string;
}

type CorrelationMap = ReadonlyMap<string, CorrelationInfo>;

const PAGE_SIZE: number = 20;

/** Builds the query params for the listings API from filter state. */
function buildListingsQuery(
  filters: JobListingsFilters,
  debouncedQ: string | null,
): {
  page: number;
  pageSize: number;
  source?: string;
  company?: string;
  q?: string;
  sort: JobSortField;
  dir: 'asc' | 'desc';
  showDismissed: boolean;
  hasSalary: boolean;
  workArrangement?: string;
  seniority?: string;
  dateRange?: JobDateRange;
} {
  return {
    page: filters.page,
    pageSize: PAGE_SIZE,
    source: filters.source ?? undefined,
    company: filters.company ?? undefined,
    q: debouncedQ ?? undefined,
    sort: filters.sort,
    dir: filters.dir,
    showDismissed: filters.showDismissed,
    hasSalary: filters.hasSalary,
    workArrangement: filters.workArrangement ?? undefined,
    seniority: filters.seniority ?? undefined,
    dateRange: filters.dateRange ?? undefined,
  };
}

/** Builds a lookup map from listing ID to correlation info. */
function buildCorrelationMap(
  items: readonly { id: string; listing_id: string; fit_score: number; status: string }[],
): CorrelationMap {
  const map = new Map<string, CorrelationInfo>();
  for (const c of items) {
    map.set(c.listing_id, { id: c.id, fitScore: c.fit_score, status: c.status });
  }
  return map;
}

const EMPTY_CORRELATION_MAP: CorrelationMap = new Map();

export type { CorrelationMap };
export { buildCorrelationMap, buildListingsQuery, EMPTY_CORRELATION_MAP, PAGE_SIZE };
