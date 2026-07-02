/**
 * Parallel search hook for listings and skills.
 *
 * Debounces the raw query, then fires two independent TanStack Query requests
 * against `/api/v1/listings` and `/api/v1/skills/search`. Results are mapped
 * into a unified `SearchGroup[]` structure for the command palette.
 */
import { $api, type JobListingResponse, type SkillSearchResult } from '@/shared/api/index.ts';
import { useDebouncedValue } from '@/shared/lib/index.ts';
import {
  SEARCH_DEBOUNCE_MS,
  SEARCH_MAX_RESULTS_PER_GROUP,
  SEARCH_MIN_QUERY_LENGTH,
} from '../lib/constants.ts';
import type { SearchGroup, SearchResult, UseGlobalSearchResult } from '../lib/types.ts';

/** Maps a listing API response item to a unified search result. */
function mapListingToSearchResult(listing: JobListingResponse): SearchResult {
  return {
    type: 'listing',
    id: listing.id,
    title: listing.title,
    subtitle: listing.company_name,
    href: `/jobs/${listing.id}`,
  };
}

/** Maps a skill search result item to a unified search result. */
function mapSkillToSearchResult(skill: SkillSearchResult): SearchResult {
  return {
    type: 'skill',
    id: skill.id,
    title: skill.display_name ?? skill.name,
    subtitle: skill.category ?? null,
    href: '',
  };
}

export function useGlobalSearch(query: string): UseGlobalSearchResult {
  const debouncedQuery: string = useDebouncedValue(query, SEARCH_DEBOUNCE_MS);
  const isEnabled: boolean = debouncedQuery.length >= SEARCH_MIN_QUERY_LENGTH;

  const listingsQuery = $api.useQuery(
    'get',
    '/api/v1/listings',
    {
      params: {
        query: { q: debouncedQuery, page_size: SEARCH_MAX_RESULTS_PER_GROUP },
      },
    },
    { enabled: isEnabled },
  );

  const skillsQuery = $api.useQuery(
    'get',
    '/api/v1/skills/search',
    {
      params: {
        query: { q: debouncedQuery, limit: SEARCH_MAX_RESULTS_PER_GROUP },
      },
    },
    { enabled: isEnabled },
  );

  const listingResults: readonly SearchResult[] =
    listingsQuery.data?.items?.map(mapListingToSearchResult) ?? [];
  const skillResults: readonly SearchResult[] =
    skillsQuery.data?.skills?.map(mapSkillToSearchResult) ?? [];

  const groups: readonly SearchGroup[] = [
    {
      type: 'listing' as const,
      labelKey: 'common:commandPalette.searchResultsJobs',
      results: listingResults,
      isLoading: listingsQuery.isLoading && isEnabled,
      isError: listingsQuery.isError,
    },
    {
      type: 'skill' as const,
      labelKey: 'common:commandPalette.searchResultsSkills',
      results: skillResults,
      isLoading: skillsQuery.isLoading && isEnabled,
      isError: skillsQuery.isError,
    },
  ];

  const isSearching: boolean = isEnabled && (listingsQuery.isLoading || skillsQuery.isLoading);
  const hasResults: boolean = groups.some((g) => g.results.length > 0);

  return { groups, isSearching, hasResults };
}
