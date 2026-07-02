/**
 * Discriminated union of searchable content types.
 * Extensible: add new variants as BFF endpoints gain search support.
 */
type SearchResultType = 'listing' | 'skill';

interface SearchResult {
  readonly type: SearchResultType;
  readonly id: string;
  /** Primary display text (job title, skill name). */
  readonly title: string;
  /** Secondary text (company, category). */
  readonly subtitle: string | null;
  /** Route path to navigate to on selection. */
  readonly href: string;
}

interface SearchGroup {
  readonly type: SearchResultType;
  /** i18n key for group heading. */
  readonly labelKey: string;
  readonly results: readonly SearchResult[];
  readonly isLoading: boolean;
  readonly isError: boolean;
}

interface UseGlobalSearchResult {
  readonly groups: readonly SearchGroup[];
  readonly isSearching: boolean;
  readonly hasResults: boolean;
}

export type { SearchGroup, SearchResult, UseGlobalSearchResult };
