import { useRouter, useRouterState } from '@tanstack/react-router';
import { handleNavigationPromise } from '@/shared/lib/index.ts';

interface MatchesFilters {
  page: number;
  prefId: string | null;
  minScore: number;
}

interface MatchesSearchParams {
  page?: number | undefined;
  prefId?: string | undefined;
  minScore?: number | undefined;
}

function selectSearch(state: {
  location: { search: Record<string, unknown> };
}): MatchesSearchParams {
  const { page: rawPage, prefId: rawPrefId, minScore: rawMinScore } = state.location.search;
  const page = typeof rawPage === 'number' ? rawPage : undefined;
  const prefId = typeof rawPrefId === 'string' ? rawPrefId : undefined;
  const minScore = typeof rawMinScore === 'number' ? rawMinScore : undefined;
  return { page, prefId, minScore };
}

/**
 * Hook for managing job matches filter state via URL search params.
 *
 * Reads search params from router state and navigates with explicit search
 * objects. The route's zod `validateSearch` schema handles runtime validation;
 * this hook reads the already-validated state.
 */
interface UseMatchesFiltersResult {
  filters: MatchesFilters;
  setPage: (page: number) => void;
  setPrefId: (prefId: string | null) => void;
  setMinScore: (minScore: number | null) => void;
  clearFilters: () => void;
  hasActiveFilters: boolean;
  activeFilterCount: number;
}

function useMatchesFilters(): UseMatchesFiltersResult {
  const router = useRouter();
  const search = useRouterState({ select: selectSearch });

  const filters: MatchesFilters = {
    page: search.page ?? 1,
    prefId: search.prefId ?? null,
    minScore: search.minScore ?? 60,
  };

  const navigate = (params: MatchesSearchParams): void => {
    handleNavigationPromise(router.navigate({ to: '/jobs/matches', search: params }));
  };

  return {
    filters,
    setPage: (page: number): void => navigate({ ...search, page }),
    setPrefId: (prefId: string | null): void =>
      navigate({ ...search, prefId: prefId ?? undefined }),
    setMinScore: (minScore: number | null): void =>
      navigate({ ...search, minScore: minScore ?? undefined }),
    clearFilters: (): void => navigate({ page: 1 }),
    hasActiveFilters: Boolean(filters.prefId) || filters.minScore !== 60,
    activeFilterCount: (filters.prefId ? 1 : 0) + (filters.minScore !== 60 ? 1 : 0),
  };
}

export type { MatchesFilters };
export { useMatchesFilters };
