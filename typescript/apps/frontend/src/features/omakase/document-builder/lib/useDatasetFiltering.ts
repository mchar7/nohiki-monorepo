import { useState } from 'react';
import type { Dataset } from '../model/index.ts';

type SortField = 'name' | 'created' | 'updated';
type SortOrder = 'asc' | 'desc';

interface UseDatasetFilteringOptions {
  datasets: Dataset[];
  maxItems?: number | undefined;
}

// Helper function to get sort value for a dataset
function getSortValue(dataset: Dataset, sortBy: SortField): string | number {
  switch (sortBy) {
    case 'name':
      return dataset.name.toLowerCase();
    case 'created':
      return new Date(dataset.createdAt).getTime();
    case 'updated':
      return new Date(dataset.updatedAt).getTime();
    default: {
      const _exhaustive: never = sortBy;
      return _exhaustive;
    }
  }
}

// Helper function to compare two values
function compareValues(aValue: string | number, bValue: string | number, order: SortOrder): number {
  if (order === 'desc') {
    if (aValue > bValue) {
      return -1;
    }
    if (aValue < bValue) {
      return 1;
    }
    return 0;
  }
  if (aValue < bValue) {
    return -1;
  }
  if (aValue > bValue) {
    return 1;
  }
  return 0;
}

interface DecoratedDataset {
  readonly dataset: Dataset;
  readonly sortValue: string | number;
}

function buildFilteredAndSortedDatasets({
  datasets,
  searchTermLower,
  selectedTemplateFilter,
  sortBy,
  sortOrder,
  maxItems,
}: {
  readonly datasets: Dataset[];
  readonly searchTermLower: string;
  readonly selectedTemplateFilter: string;
  readonly sortBy: SortField;
  readonly sortOrder: SortOrder;
  readonly maxItems: number | undefined;
}): Dataset[] {
  const decorated: DecoratedDataset[] = [];

  for (const dataset of datasets) {
    const matchesSearch = dataset.name.toLowerCase().includes(searchTermLower);
    const matchesTemplate =
      selectedTemplateFilter === 'all' || dataset.templateVersionId === selectedTemplateFilter;

    if (matchesSearch && matchesTemplate) {
      decorated.push({
        dataset,
        sortValue: getSortValue(dataset, sortBy),
      });
    }
  }

  decorated.sort((a, b) => compareValues(a.sortValue, b.sortValue, sortOrder));

  const sorted = decorated.map(({ dataset }) => dataset);
  if (maxItems) {
    return sorted.slice(0, maxItems);
  }
  return sorted;
}

export function useDatasetFiltering({ datasets, maxItems }: UseDatasetFilteringOptions): {
  searchTerm: string;
  selectedTemplateFilter: string;
  sortBy: SortField;
  sortOrder: SortOrder;
  filteredAndSortedDatasets: Dataset[];
  setSearchTerm: (value: string) => void;
  setSelectedTemplateFilter: (value: string) => void;
  setSortBy: (value: SortField) => void;
  setSortOrder: (value: SortOrder) => void;
  setSortCriteria: (field: SortField, order: SortOrder) => void;
  resetFilters: () => void;
} {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedTemplateFilter, setSelectedTemplateFilter] = useState('all');
  const [sortBy, setSortBy] = useState<SortField>('updated');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const searchTermLower = searchTerm.toLowerCase();

  const filteredAndSortedDatasets = buildFilteredAndSortedDatasets({
    datasets,
    searchTermLower,
    selectedTemplateFilter,
    sortBy,
    sortOrder,
    maxItems,
  });

  const setSortCriteria = (field: SortField, order: SortOrder): void => {
    setSortBy(field);
    setSortOrder(order);
  };

  const resetFilters = (): void => {
    setSearchTerm('');
    setSelectedTemplateFilter('all');
    setSortBy('updated');
    setSortOrder('desc');
  };

  return {
    // State
    searchTerm,
    selectedTemplateFilter,
    sortBy,
    sortOrder,
    filteredAndSortedDatasets,

    // Actions
    setSearchTerm,
    setSelectedTemplateFilter,
    setSortBy,
    setSortOrder,
    setSortCriteria,
    resetFilters,
  };
}
