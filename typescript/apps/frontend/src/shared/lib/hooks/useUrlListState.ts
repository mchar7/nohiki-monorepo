import { useRouter, useRouterState } from '@tanstack/react-router';
import { handleNavigationPromise } from '../utils/navigation.ts';

/** Sort direction for list pages - structurally identical to SortDirection from sort-select.tsx. */
type ListSortDirection = 'asc' | 'desc';

interface ListSearchParams {
  page?: number;
  sort?: string;
  dir?: string;
}

/** Narrows raw router search state to the list-search param shape. */
function selectListSearch(state: {
  location: { search: Record<string, unknown> };
}): ListSearchParams {
  const { page, sort, dir } = state.location.search;
  return {
    page: typeof page === 'number' ? page : undefined,
    sort: typeof sort === 'string' ? sort : undefined,
    dir: typeof dir === 'string' && (dir === 'asc' || dir === 'desc') ? dir : undefined,
  };
}

interface UseUrlListStateOptions<TSortField extends string> {
  /** Route path for navigation (e.g. '/profiles'). */
  readonly route: string;
  /** Default sort field when URL has no `sort` param. */
  readonly defaultSort: TSortField;
  /** Default sort direction when URL has no `dir` param. */
  readonly defaultDirection?: ListSortDirection;
}

interface UseUrlListStateResult<TSortField extends string> {
  /** Current page number (1-indexed). */
  page: number;
  /** Active sort field. */
  sortField: TSortField;
  /** Active sort direction. */
  sortDirection: ListSortDirection;
  /** Navigate to a specific page. */
  setPage: (page: number) => void;
  /** Change sort field and reset to page 1. */
  setSortField: (field: TSortField) => void;
  /** Change sort direction and reset to page 1. */
  setSortDirection: (direction: ListSortDirection) => void;
}

/**
 * Syncs list sort + pagination state to URL search params.
 *
 * Replaces the common `useState` triple (sortField, sortDirection, page) with
 * URL-backed state that survives navigation and browser refresh.
 *
 * Changing sort field or direction auto-resets page to 1.
 *
 * Uses the same `useRouterState` + `router.navigate` pattern established by
 * useJobListingsFilters and useMatchesFilters. The route's Zod `validateSearch`
 * schema (built with `listSearchSchema`) handles runtime validation.
 *
 * @param options - Configuration with route path and sort defaults.
 * @returns Current state values and setter functions compatible with SortSelect and
 *   ListPagination props.
 *
 * Examples:
 *   const { page, sortField, sortDirection, setPage, setSortField, setSortDirection } =
 *     useUrlListState<ProfileSortField>({ route: '/profiles', defaultSort: 'name' });
 */
export function useUrlListState<TSortField extends string>(
  options: UseUrlListStateOptions<TSortField>,
): UseUrlListStateResult<TSortField> {
  const router = useRouter();
  const search = useRouterState({ select: selectListSearch });

  const page = search.page ?? 1;
  const sortField = (search.sort as TSortField | undefined) ?? options.defaultSort;
  const sortDirection: ListSortDirection =
    (search.dir as ListSortDirection | undefined) ?? options.defaultDirection ?? 'asc';

  const navigate = (params: ListSearchParams): void => {
    handleNavigationPromise(router.navigate({ to: options.route, search: params }));
  };

  return {
    page,
    sortField,
    sortDirection,
    setPage: (p: number): void => navigate({ sort: search.sort, dir: search.dir, page: p }),
    setSortField: (field: TSortField): void => navigate({ sort: field, dir: search.dir, page: 1 }),
    setSortDirection: (dir: ListSortDirection): void =>
      navigate({ sort: search.sort, dir, page: 1 }),
  };
}
