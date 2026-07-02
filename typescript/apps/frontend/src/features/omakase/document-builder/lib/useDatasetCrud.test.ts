import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { Dataset, DatasetData } from '../model/index.ts';
import { useDocumentBuilderStore } from '../model/index.ts';
import { useDatasetCrud } from './useDatasetCrud.ts';

const mockNavigate: ReturnType<typeof vi.fn> = vi.fn().mockResolvedValue(undefined);
vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockCreateDataset = vi
  .fn<
    <TData extends DatasetData>(
      dataset: Omit<Dataset<TData>, 'id' | 'createdAt' | 'updatedAt'>,
    ) => string
  >()
  .mockReturnValue('new-id');
const mockUpdateDataset =
  vi.fn<<TData extends DatasetData>(id: string, updates: Partial<Dataset<TData>>) => void>();
const mockSetActiveDataset = vi.fn<(id: string | null) => void>();

const mockDataset: Dataset = {
  id: 'ds-1',
  name: 'Test Dataset',
  templateVersionId: 'tpl-1',
  data: { field: 'value' },
  createdAt: '2024-01-01T00:00:00Z',
  updatedAt: '2024-01-02T00:00:00Z',
};

const mockDataset2: Dataset = {
  id: 'ds-2',
  name: 'Other Dataset',
  templateVersionId: 'tpl-2',
  data: {},
  createdAt: '2024-01-03T00:00:00Z',
  updatedAt: '2024-01-04T00:00:00Z',
};

const mockDatasets: Dataset[] = [mockDataset, mockDataset2];
const mockDatasetIndex: Map<string, Dataset> = new Map(mockDatasets.map((d) => [d.id, d]));

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentBuilderStore.setState({
    datasets: mockDatasets,
    templateFamilies: [],
    createDataset: mockCreateDataset,
    updateDataset: mockUpdateDataset,
    deleteDataset: vi.fn(),
    setActiveDataset: mockSetActiveDataset,
    datasetIndex: mockDatasetIndex,
    getDataset: (id: string) => mockDatasetIndex.get(id),
  });
});

describe('useDatasetCrud - datasets', () => {
  test('exposes datasets from the store', () => {
    const { result } = renderHook(() => useDatasetCrud());
    expect(result.current.datasets).toBe(mockDatasets);
  });

  test('exposes getDataset from the store', () => {
    const { result } = renderHook(() => useDatasetCrud());
    expect(result.current.getDataset('ds-1')).toBe(mockDataset);
    expect(result.current.getDataset('nonexistent')).toBeUndefined();
  });
});

describe('useDatasetCrud - handleCreate', () => {
  test('sets active dataset and navigates to editor', () => {
    const { result } = renderHook(() => useDatasetCrud());

    act(() => {
      result.current.handleCreate('ds-1');
    });

    expect(mockSetActiveDataset).toHaveBeenCalledWith('ds-1');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/documents/editor/$datasetId',
      params: { datasetId: 'ds-1' },
    });
  });
});

describe('useDatasetCrud - handleEdit', () => {
  test('calls onDatasetSelect with the found dataset', () => {
    const onDatasetSelect = vi.fn();
    const { result } = renderHook(() => useDatasetCrud({ onDatasetSelect }));

    act(() => {
      result.current.handleEdit('ds-1');
    });

    expect(onDatasetSelect).toHaveBeenCalledWith(mockDataset);
  });

  test('does nothing when dataset not found', () => {
    const onDatasetSelect = vi.fn();
    const { result } = renderHook(() => useDatasetCrud({ onDatasetSelect }));

    act(() => {
      result.current.handleEdit('nonexistent');
    });

    expect(onDatasetSelect).not.toHaveBeenCalled();
  });

  test('does nothing when onDatasetSelect is not provided', () => {
    const { result } = renderHook(() => useDatasetCrud());

    expect(() => {
      act(() => {
        result.current.handleEdit('ds-1');
      });
    }).not.toThrow();
  });
});

describe('useDatasetCrud - handleClone', () => {
  test('creates a copy and navigates to the new dataset', () => {
    const { result } = renderHook(() => useDatasetCrud());

    act(() => {
      result.current.handleClone('ds-1');
    });

    expect(mockCreateDataset).toHaveBeenCalledWith({
      name: 'Test Dataset (Copy)',
      templateVersionId: 'tpl-1',
      data: { field: 'value' },
    });
    expect(mockSetActiveDataset).toHaveBeenCalledWith('new-id');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/documents/editor/$datasetId',
      params: { datasetId: 'new-id' },
    });
  });

  test('does nothing when dataset not found', () => {
    const { result } = renderHook(() => useDatasetCrud());

    act(() => {
      result.current.handleClone('nonexistent');
    });

    expect(mockCreateDataset).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

describe('useDatasetCrud - handleRename', () => {
  test('calls updateDataset with new name', () => {
    const { result } = renderHook(() => useDatasetCrud());

    act(() => {
      result.current.handleRename('ds-1', 'New Name');
    });

    expect(mockUpdateDataset).toHaveBeenCalledWith('ds-1', { name: 'New Name' });
  });
});

describe('useDatasetCrud - modal state', () => {
  test('starts with create modal closed', () => {
    const { result } = renderHook(() => useDatasetCrud());
    expect(result.current.showCreateModal).toBe(false);
  });

  test('toggles create modal', () => {
    const { result } = renderHook(() => useDatasetCrud());

    act(() => {
      result.current.openCreateModal();
    });
    expect(result.current.showCreateModal).toBe(true);

    act(() => {
      result.current.closeCreateModal();
    });
    expect(result.current.showCreateModal).toBe(false);
  });

  test('starts with export modal closed', () => {
    const { result } = renderHook(() => useDatasetCrud());
    expect(result.current.showExportModal).toBe(false);
    expect(result.current.selectedForExport).toEqual([]);
  });

  test('toggles export modal', () => {
    const { result } = renderHook(() => useDatasetCrud());

    act(() => {
      result.current.handleExport('ds-1');
    });
    expect(result.current.showExportModal).toBe(true);
    expect(result.current.selectedForExport).toEqual(['ds-1']);

    act(() => {
      result.current.closeExportModal();
    });
    expect(result.current.showExportModal).toBe(false);
  });
});

describe('useDatasetCrud - handleBulkExport', () => {
  test('opens export modal with empty selection for bulk', () => {
    const { result } = renderHook(() => useDatasetCrud());

    act(() => {
      result.current.handleBulkExport();
    });

    expect(result.current.showExportModal).toBe(true);
    expect(result.current.selectedForExport).toEqual([]);
  });
});
