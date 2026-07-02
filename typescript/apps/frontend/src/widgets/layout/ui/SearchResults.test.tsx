import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { Command } from '@/shared/ui/command.tsx';
import { i18n } from '@/test/setup.ts';
import type { UseGlobalSearchResult } from '../lib/types.ts';
import { SearchResults } from './SearchResults.tsx';

const mockOnSelect = vi.fn<(href: string) => void>();

const EMPTY_RESULT: UseGlobalSearchResult = {
  groups: [
    {
      type: 'listing',
      labelKey: 'common:commandPalette.searchResultsJobs',
      results: [],
      isLoading: false,
      isError: false,
    },
    {
      type: 'skill',
      labelKey: 'common:commandPalette.searchResultsSkills',
      results: [],
      isLoading: false,
      isError: false,
    },
  ],
  isSearching: false,
  hasResults: false,
};

const LOADING_RESULT: UseGlobalSearchResult = {
  groups: [
    {
      type: 'listing',
      labelKey: 'common:commandPalette.searchResultsJobs',
      results: [],
      isLoading: true,
      isError: false,
    },
    {
      type: 'skill',
      labelKey: 'common:commandPalette.searchResultsSkills',
      results: [],
      isLoading: true,
      isError: false,
    },
  ],
  isSearching: true,
  hasResults: false,
};

const POPULATED_RESULT: UseGlobalSearchResult = {
  groups: [
    {
      type: 'listing',
      labelKey: 'common:commandPalette.searchResultsJobs',
      results: [
        {
          type: 'listing',
          id: 'l1',
          title: 'Software Engineer',
          subtitle: 'Acme Corp',
          href: '/jobs/l1',
        },
      ],
      isLoading: false,
      isError: false,
    },
    {
      type: 'skill',
      labelKey: 'common:commandPalette.searchResultsSkills',
      results: [{ type: 'skill', id: 's1', title: 'TypeScript', subtitle: 'Language', href: '' }],
      isLoading: false,
      isError: false,
    },
  ],
  isSearching: false,
  hasResults: true,
};

let mockReturnValue: UseGlobalSearchResult = EMPTY_RESULT;

vi.mock('../api/useGlobalSearch.ts', () => ({
  useGlobalSearch: () => mockReturnValue,
}));

/** Wraps SearchResults in cmdk Command context (required by CommandGroup/CommandItem). */
function renderSearchResults(query: string): void {
  render(
    <I18nextProvider i18n={i18n}>
      <Command shouldFilter={false}>
        <SearchResults query={query} onSelect={mockOnSelect} />
      </Command>
    </I18nextProvider>,
  );
}

describe('SearchResults', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockReturnValue = EMPTY_RESULT;
  });

  test('renders nothing when query is too short', () => {
    renderSearchResults('a');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  test('renders loading indicator while searching', () => {
    mockReturnValue = LOADING_RESULT;
    renderSearchResults('test');

    const statusElements = screen.getAllByRole('status');
    expect(statusElements.length).toBeGreaterThanOrEqual(1);
  });

  test('renders grouped results with correct headings', () => {
    mockReturnValue = POPULATED_RESULT;
    renderSearchResults('test');

    expect(screen.getByText('Software Engineer')).toBeInTheDocument();
    expect(screen.getByText('TypeScript')).toBeInTheDocument();
    expect(screen.getByText('Acme Corp')).toBeInTheDocument();
    expect(screen.getByText('Language')).toBeInTheDocument();
  });

  test('renders empty state when no results and not searching', () => {
    mockReturnValue = EMPTY_RESULT;
    renderSearchResults('nonexistent');

    expect(screen.getByText('No results for "nonexistent"')).toBeInTheDocument();
  });

  test('calls onSelect with result href on item click', async () => {
    mockReturnValue = POPULATED_RESULT;
    renderSearchResults('test');

    const user = userEvent.setup();
    const item = screen.getByText('Software Engineer');
    await user.click(item);

    expect(mockOnSelect).toHaveBeenCalledWith('/jobs/l1');
  });
});
