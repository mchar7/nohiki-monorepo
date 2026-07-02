import { act, renderHook } from '@testing-library/react';
import { describe, expect } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { useDatasetFiltering } from './useDatasetFiltering.ts';

const RANDOM_ID_START_INDEX: number = 2;
/** Base-36 radix used for compact random ID generation */
const BASE36_RADIX: number = 36;

const createMockDataset = (
  overrides: Record<string, unknown> = {},
): {
  id: string;
  name: string;
  templateVersionId: string;
  data: Record<string, never>;
  createdAt: string;
  updatedAt: string;
} => ({
  id: `dataset-${Math.random().toString(BASE36_RADIX).slice(RANDOM_ID_START_INDEX)}`,
  name: 'Test Dataset',
  templateVersionId: 'template-1',
  data: {},
  createdAt: '2024-01-01T00:00:00Z',
  updatedAt: '2024-01-02T00:00:00Z',
  ...overrides,
});

describe('useDatasetFiltering - initial state', () => {
  test('returns all datasets when no filters applied', () => {
    const datasets = [
      createMockDataset({ name: 'Dataset 1' }),
      createMockDataset({ name: 'Dataset 2' }),
    ];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    expect(result.current.filteredAndSortedDatasets).toHaveLength(2);
    expect(result.current.searchTerm).toBe('');
    expect(result.current.selectedTemplateFilter).toBe('all');
    expect(result.current.sortBy).toBe('updated');
    expect(result.current.sortOrder).toBe('desc');
  });
});

describe('useDatasetFiltering - search filtering', () => {
  test('filters datasets by search term', () => {
    const datasets = [
      createMockDataset({ name: 'Alpha Dataset' }),
      createMockDataset({ name: 'Beta Dataset' }),
      createMockDataset({ name: 'Gamma Dataset' }),
    ];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSearchTerm('Alpha');
    });

    expect(result.current.filteredAndSortedDatasets).toHaveLength(1);
    expect(nonNull(result.current.filteredAndSortedDatasets[0]).name).toBe('Alpha Dataset');
  });

  test('search is case insensitive', () => {
    const datasets = [createMockDataset({ name: 'Alpha Dataset' })];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSearchTerm('alpha');
    });

    expect(result.current.filteredAndSortedDatasets).toHaveLength(1);
  });

  test('returns empty when no match', () => {
    const datasets = [createMockDataset({ name: 'Alpha Dataset' })];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSearchTerm('xyz');
    });

    expect(result.current.filteredAndSortedDatasets).toHaveLength(0);
  });
});

describe('useDatasetFiltering - template filtering', () => {
  test('filters by template', () => {
    const datasets = [
      createMockDataset({ name: 'Dataset 1', templateVersionId: 'template-1' }),
      createMockDataset({ name: 'Dataset 2', templateVersionId: 'template-2' }),
    ];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSelectedTemplateFilter('template-1');
    });

    expect(result.current.filteredAndSortedDatasets).toHaveLength(1);
    expect(nonNull(result.current.filteredAndSortedDatasets[0]).templateVersionId).toBe(
      'template-1',
    );
  });
});

describe('useDatasetFiltering - sorting by name', () => {
  test('sorts by name ascending', () => {
    const datasets = [
      createMockDataset({ name: 'Zebra' }),
      createMockDataset({ name: 'Alpha' }),
      createMockDataset({ name: 'Beta' }),
    ];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSortBy('name');
      result.current.setSortOrder('asc');
    });

    expect(nonNull(result.current.filteredAndSortedDatasets[0]).name).toBe('Alpha');
    expect(nonNull(result.current.filteredAndSortedDatasets[2]).name).toBe('Zebra');
  });

  test('sorts by name descending', () => {
    const datasets = [createMockDataset({ name: 'Alpha' }), createMockDataset({ name: 'Zebra' })];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSortBy('name');
      result.current.setSortOrder('desc');
    });

    expect(nonNull(result.current.filteredAndSortedDatasets[0]).name).toBe('Zebra');
  });
});

describe('useDatasetFiltering - sorting by date', () => {
  test('sorts by created date', () => {
    const datasets = [
      createMockDataset({ name: 'Newer', createdAt: '2024-02-01T00:00:00Z' }),
      createMockDataset({ name: 'Older', createdAt: '2024-01-01T00:00:00Z' }),
    ];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSortBy('created');
      result.current.setSortOrder('desc');
    });

    expect(nonNull(result.current.filteredAndSortedDatasets[0]).name).toBe('Newer');
  });

  test('sorts by updated date', () => {
    const datasets = [
      createMockDataset({ name: 'Older', updatedAt: '2024-01-01T00:00:00Z' }),
      createMockDataset({ name: 'Newer', updatedAt: '2024-02-01T00:00:00Z' }),
    ];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSortBy('updated');
      result.current.setSortOrder('desc');
    });

    expect(nonNull(result.current.filteredAndSortedDatasets[0]).name).toBe('Newer');
  });

  test('sets sort criteria together', () => {
    const datasets = [createMockDataset({ name: 'Test' })];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSortCriteria('name', 'asc');
    });

    expect(result.current.sortBy).toBe('name');
    expect(result.current.sortOrder).toBe('asc');
  });
});

describe('useDatasetFiltering - maxItems', () => {
  test('limits results when maxItems is set', () => {
    const datasets = [
      createMockDataset({ name: 'Dataset 1' }),
      createMockDataset({ name: 'Dataset 2' }),
      createMockDataset({ name: 'Dataset 3' }),
    ];

    const { result } = renderHook(() => useDatasetFiltering({ datasets, maxItems: 2 }));

    expect(result.current.filteredAndSortedDatasets).toHaveLength(2);
  });
});

describe('useDatasetFiltering - resetFilters', () => {
  test('resets all filters to defaults', () => {
    const datasets = [createMockDataset({ name: 'Test' })];

    const { result } = renderHook(() => useDatasetFiltering({ datasets }));

    act(() => {
      result.current.setSearchTerm('search');
      result.current.setSelectedTemplateFilter('template-1');
      result.current.setSortBy('name');
      result.current.setSortOrder('asc');
    });

    act(() => {
      result.current.resetFilters();
    });

    expect(result.current.searchTerm).toBe('');
    expect(result.current.selectedTemplateFilter).toBe('all');
    expect(result.current.sortBy).toBe('updated');
    expect(result.current.sortOrder).toBe('desc');
  });
});
