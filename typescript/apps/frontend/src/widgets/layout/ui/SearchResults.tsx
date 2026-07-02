/**
 * Renders grouped search results inside the command palette.
 *
 * Calls `useGlobalSearch` with the current query and displays results
 * organized by content type (jobs, skills). Each result item navigates
 * to its detail page on selection.
 */
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { CommandEmpty, CommandGroup, CommandItem } from '@/shared/ui/command.tsx';
import { useGlobalSearch } from '../api/useGlobalSearch.ts';
import { SEARCH_MIN_QUERY_LENGTH } from '../lib/constants.ts';
import type { SearchGroup, SearchResult } from '../lib/types.ts';

interface SearchResultsProps {
  readonly query: string;
  readonly onSelect: (href: string) => void;
}

function SearchGroupLoading({ labelKey }: { readonly labelKey: string }): JSX.Element {
  const { t } = useTranslation();
  return (
    <CommandGroup heading={t(labelKey)}>
      <output className="block px-2 py-3 text-muted-foreground text-sm">
        {t('common:commandPalette.searching')}
      </output>
    </CommandGroup>
  );
}

function SearchGroupResults({
  group,
  onSelect,
}: {
  readonly group: SearchGroup;
  readonly onSelect: (href: string) => void;
}): JSX.Element | null {
  const { t } = useTranslation();

  if (group.isLoading) {
    return <SearchGroupLoading labelKey={group.labelKey} />;
  }

  if (group.results.length === 0) {
    return null;
  }

  return (
    <CommandGroup heading={t(group.labelKey)}>
      {group.results.map((result: SearchResult) => (
        <CommandItem
          key={`${result.type}-${result.id}`}
          value={`${result.type}-${result.id}-${result.title}`}
          onSelect={() => onSelect(result.href)}
        >
          <span>{result.title}</span>
          {result.subtitle ? (
            <span className="ml-auto text-muted-foreground text-xs">{result.subtitle}</span>
          ) : null}
        </CommandItem>
      ))}
    </CommandGroup>
  );
}

export function SearchResults({ query, onSelect }: SearchResultsProps): JSX.Element | null {
  const { t } = useTranslation();
  const { groups, isSearching, hasResults } = useGlobalSearch(query);

  if (query.length < SEARCH_MIN_QUERY_LENGTH) {
    return null;
  }

  return (
    <>
      {groups.map((group: SearchGroup) => (
        <SearchGroupResults key={group.type} group={group} onSelect={onSelect} />
      ))}
      {isSearching || hasResults ? null : (
        <CommandEmpty>{t('common:commandPalette.noSearchResults', { query })}</CommandEmpty>
      )}
    </>
  );
}
