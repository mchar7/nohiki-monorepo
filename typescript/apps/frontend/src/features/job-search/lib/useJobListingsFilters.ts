import { useRouter, useRouterState } from '@tanstack/react-router';
import { handleNavigationPromise } from '@/shared/lib/index.ts';

type JobSortField = 'posted_at' | 'company_name' | 'title' | 'match_score';
type SortDirection = 'asc' | 'desc';
type JobDateRange = '24h' | '7d' | '30d';

interface JobListingsFilters {
  page: number;
  sort: JobSortField;
  dir: SortDirection;
  source: string | null;
  company: string | null;
  q: string | null;
  showDismissed: boolean;
  hasSalary: boolean;
  workArrangement: string | null;
  seniority: string | null;
  dateRange: JobDateRange | null;
}

interface JobSearchParams {
  page?: number | undefined;
  sort?: string | undefined;
  dir?: string | undefined;
  source?: string | undefined;
  company?: string | undefined;
  q?: string | undefined;
  showDismissed?: boolean | undefined;
  hasSalary?: boolean | undefined;
  workArrangement?: string | undefined;
  seniority?: string | undefined;
  dateRange?: string | undefined;
}

/** Valid sort fields for runtime validation */
const VALID_SORT_FIELDS: ReadonlySet<string> = new Set([
  'posted_at',
  'company_name',
  'title',
  'match_score',
]);

/** Valid work arrangement values for runtime validation */
const VALID_WORK_ARRANGEMENTS: ReadonlySet<string> = new Set(['remote', 'hybrid', 'onsite']);

/** Valid seniority level values for runtime validation */
const VALID_SENIORITY_LEVELS: ReadonlySet<string> = new Set([
  'entry',
  'mid',
  'senior',
  'lead',
  'manager',
  'director',
  'executive',
]);

/** Valid date range values for runtime validation */
const VALID_DATE_RANGES: ReadonlySet<string> = new Set(['24h', '7d', '30d']);

/** Validates a string value against an allowed set, returning undefined if invalid. */
function validateSetMember(raw: unknown, allowed: ReadonlySet<string>): string | undefined {
  return typeof raw === 'string' && allowed.has(raw) ? raw : undefined;
}

function selectSearch(state: { location: { search: Record<string, unknown> } }): JobSearchParams {
  const s = state.location.search;
  return {
    page: typeof s.page === 'number' ? s.page : undefined,
    sort: validateSetMember(s.sort, VALID_SORT_FIELDS),
    dir: typeof s.dir === 'string' && (s.dir === 'asc' || s.dir === 'desc') ? s.dir : undefined,
    source: typeof s.source === 'string' ? s.source : undefined,
    company: typeof s.company === 'string' ? s.company : undefined,
    q: typeof s.q === 'string' ? s.q : undefined,
    showDismissed: typeof s.showDismissed === 'boolean' ? s.showDismissed : undefined,
    hasSalary: typeof s.hasSalary === 'boolean' ? s.hasSalary : undefined,
    workArrangement: validateSetMember(s.workArrangement, VALID_WORK_ARRANGEMENTS),
    seniority: validateSetMember(s.seniority, VALID_SENIORITY_LEVELS),
    dateRange: validateSetMember(s.dateRange, VALID_DATE_RANGES),
  };
}

/**
 * Hook for managing job listings filter and sort state via URL search params.
 *
 * Uses useRouterState with a select function because TanStack Router's
 * generated routeTree.gen.ts uses `as any` on .update() calls, which
 * degrades the Register.router type and prevents useSearch({ from })
 * from resolving search param types. The route's Zod validateSearch
 * schema validates at runtime; this selector narrows the already-validated state.
 *
 * Sort state is persisted in the URL alongside filter params so it survives
 * navigation and browser refresh (consistent with profiles/documents/attachments).
 */
interface UseJobListingsFiltersResult {
  filters: JobListingsFilters;
  setPage: (page: number) => void;
  setSortField: (field: JobSortField) => void;
  setSortDirection: (direction: SortDirection) => void;
  setSource: (source: string | null) => void;
  setCompany: (company: string | null) => void;
  setQuery: (q: string | null) => void;
  setShowDismissed: (show: boolean) => void;
  setHasSalary: (hasSalary: boolean) => void;
  setWorkArrangement: (workArrangement: string | null) => void;
  setSeniority: (seniority: string | null) => void;
  setDateRange: (dateRange: string | null) => void;
  clearFilters: () => void;
  hasActiveFilters: boolean;
  activeFilterCount: number;
}

/** Derives typed filter state from raw search params. */
function buildFilters(search: JobSearchParams): JobListingsFilters {
  return {
    page: search.page ?? 1,
    sort: (search.sort as JobSortField | undefined) ?? 'posted_at',
    dir: (search.dir as SortDirection | undefined) ?? 'desc',
    source: search.source ?? null,
    company: search.company ?? null,
    q: search.q ?? null,
    showDismissed: search.showDismissed ?? false,
    hasSalary: search.hasSalary ?? false,
    workArrangement: search.workArrangement ?? null,
    seniority: search.seniority ?? null,
    dateRange: (search.dateRange as JobDateRange | undefined) ?? null,
  };
}

/** Counts how many filters are currently active. */
function countActiveFilters(f: JobListingsFilters): number {
  const booleans = [
    Boolean(f.source),
    Boolean(f.company),
    Boolean(f.q),
    f.showDismissed,
    f.hasSalary,
    Boolean(f.workArrangement),
    Boolean(f.seniority),
    Boolean(f.dateRange),
  ];
  return booleans.filter(Boolean).length;
}

function useJobListingsFilters(): UseJobListingsFiltersResult {
  const router = useRouter();
  const search = useRouterState({ select: selectSearch });
  const filters = buildFilters(search);

  const navigate = (params: JobSearchParams): void => {
    handleNavigationPromise(router.navigate({ to: '/jobs', search: params }));
  };

  return {
    filters,
    setPage: (page: number): void => navigate({ ...search, page }),
    setSortField: (field: JobSortField): void => navigate({ ...search, sort: field, page: 1 }),
    setSortDirection: (direction: SortDirection): void =>
      navigate({ ...search, dir: direction, page: 1 }),
    setSource: (source: string | null): void =>
      navigate({ ...search, source: source ?? undefined, page: 1 }),
    setCompany: (company: string | null): void =>
      navigate({ ...search, company: company ?? undefined, page: 1 }),
    setQuery: (q: string | null): void => navigate({ ...search, q: q ?? undefined, page: 1 }),
    setShowDismissed: (show: boolean): void =>
      navigate({ ...search, showDismissed: show || undefined, page: 1 }),
    setHasSalary: (hasSalary: boolean): void =>
      navigate({ ...search, hasSalary: hasSalary || undefined, page: 1 }),
    setWorkArrangement: (wa: string | null): void =>
      navigate({ ...search, workArrangement: wa ?? undefined, page: 1 }),
    setSeniority: (seniority: string | null): void =>
      navigate({ ...search, seniority: seniority ?? undefined, page: 1 }),
    setDateRange: (dateRange: string | null): void =>
      navigate({ ...search, dateRange: dateRange ?? undefined, page: 1 }),
    clearFilters: (): void => navigate({ page: 1 }),
    hasActiveFilters: countActiveFilters(filters) > 0,
    activeFilterCount: countActiveFilters(filters),
  };
}

export type { JobDateRange, JobListingsFilters, JobSortField };
export { useJobListingsFilters };
