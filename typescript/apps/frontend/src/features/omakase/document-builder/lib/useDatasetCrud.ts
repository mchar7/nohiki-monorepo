import { useNavigate } from '@tanstack/react-router';
import { useState } from 'react';
import { handleNavigationPromise } from '@/shared/lib/index.ts';
import type { Dataset } from '../model/index.ts';
import { useDocumentBuilderStore } from '../model/index.ts';

interface UseDatasetCrudOptions {
  readonly onDatasetSelect?: ((dataset: Dataset) => void) | undefined;
}

interface UseDatasetCrudReturn {
  readonly datasets: Dataset[];
  readonly getDataset: (datasetId: string) => Dataset | undefined;
  readonly showCreateModal: boolean;
  readonly showExportModal: boolean;
  readonly selectedForExport: string[];
  readonly openCreateModal: () => void;
  readonly closeCreateModal: () => void;
  readonly closeExportModal: () => void;
  readonly handleCreate: (datasetId: string) => void;
  readonly handleEdit: (datasetId: string) => void;
  readonly handleClone: (datasetId: string) => void;
  readonly handleRename: (datasetId: string, newName: string) => void;
  readonly handleExport: (datasetId: string) => void;
  readonly handleBulkExport: () => void;
}

interface CloneContext {
  readonly lookupDataset: (datasetId: string) => Dataset | undefined;
  readonly addDataset: (dataset: Omit<Dataset, 'id' | 'createdAt' | 'updatedAt'>) => string;
  readonly activateDataset: (datasetId: string | null) => void;
  readonly navigateTo: (datasetId: string) => void;
}

/** Clones a dataset, activates the clone, and navigates to its editor page. */
function cloneAndNavigate(datasetId: string, ctx: CloneContext): void {
  const dataset = ctx.lookupDataset(datasetId);
  if (!dataset) {
    return;
  }

  const newDatasetId = ctx.addDataset({
    name: `${dataset.name} (Copy)`,
    templateVersionId: dataset.templateVersionId,
    data: { ...dataset.data },
  });

  ctx.activateDataset(newDatasetId);
  ctx.navigateTo(newDatasetId);
}

/**
 * Encapsulates dataset CRUD operations, navigation, and modal state.
 *
 * Uses the store's built-in `getDataset` for O(1) lookups instead of
 * maintaining a redundant index Map.
 */
function useDatasetCrudModals(): {
  showCreateModal: boolean;
  showExportModal: boolean;
  selectedForExport: string[];
  openCreateModal: () => void;
  closeCreateModal: () => void;
  closeExportModal: () => void;
  handleExport: (datasetId: string) => void;
  handleBulkExport: () => void;
} {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [selectedForExport, setSelectedForExport] = useState<string[]>([]);

  return {
    showCreateModal,
    showExportModal,
    selectedForExport,
    openCreateModal: () => setShowCreateModal(true),
    closeCreateModal: () => setShowCreateModal(false),
    closeExportModal: () => setShowExportModal(false),
    handleExport: (datasetId: string) => {
      setSelectedForExport([datasetId]);
      setShowExportModal(true);
    },
    handleBulkExport: () => {
      setSelectedForExport([]);
      setShowExportModal(true);
    },
  };
}

export function useDatasetCrud({
  onDatasetSelect,
}: UseDatasetCrudOptions = {}): UseDatasetCrudReturn {
  const navigate = useNavigate();
  const datasets = useDocumentBuilderStore((state) => state.datasets);
  const getDataset = useDocumentBuilderStore((state) => state.getDataset);
  const createDataset = useDocumentBuilderStore((state) => state.createDataset);
  const updateDataset = useDocumentBuilderStore((state) => state.updateDataset);
  const setActiveDataset = useDocumentBuilderStore((state) => state.setActiveDataset);
  const modals = useDatasetCrudModals();

  const handleCreate = (datasetId: string) => {
    setActiveDataset(datasetId);
    handleNavigationPromise(
      navigate({ to: '/documents/editor/$datasetId', params: { datasetId } }),
    );
  };

  const handleEdit = (datasetId: string) => {
    const dataset = getDataset(datasetId);
    if (dataset) {
      onDatasetSelect?.(dataset);
    }
  };

  const handleClone = (datasetId: string) =>
    cloneAndNavigate(datasetId, {
      lookupDataset: getDataset,
      addDataset: createDataset,
      activateDataset: setActiveDataset,
      navigateTo: (id: string) =>
        handleNavigationPromise(
          navigate({ to: '/documents/editor/$datasetId', params: { datasetId: id } }),
        ),
    });

  const handleRename = (datasetId: string, newName: string) =>
    updateDataset(datasetId, { name: newName });

  return {
    datasets,
    getDataset,
    ...modals,
    handleCreate,
    handleEdit,
    handleClone,
    handleRename,
  } as const;
}
