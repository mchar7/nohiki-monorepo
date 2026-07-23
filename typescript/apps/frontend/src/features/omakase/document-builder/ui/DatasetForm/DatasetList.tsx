import { EmptyState } from '@shared/ui/empty-state.tsx';
import { FileText } from 'lucide-react';
import type React from 'react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { TemplateFamilyResponse } from '@/shared/api';
import { useDatasetCrud } from '../../lib/useDatasetCrud.ts';
import { useDatasetFiltering } from '../../lib/useDatasetFiltering.ts';
import { useDeleteConfirmation } from '../../lib/useDeleteConfirmation.ts';
import type { Dataset } from '../../model/index.ts';
import { useDocumentBuilderStore } from '../../model/index.ts';
import { ConfirmDialog } from './ConfirmDialog.tsx';
import { CreateDatasetModal } from './CreateDatasetModal.tsx';
import { DatasetCard } from './DatasetCard.tsx';
import { DatasetToolbar } from './DatasetToolbar.tsx';
import { ExportJSON } from './ExportJSON.tsx';

const EMPTY_SELECTION: ReadonlySet<string> = new Set<string>();

interface DatasetListProps {
  readonly showCreateButton?: boolean;
  readonly maxItems?: number;
  readonly onDatasetSelect?: (dataset: Dataset) => void;
  readonly selectedDatasetIds?: ReadonlySet<string>;
}

interface EmptyStateConfig {
  title: string;
  description: string;
  action: { label: string; onClick: () => void } | undefined;
}

interface BuildEmptyStateParams {
  hasFilterApplied: boolean;
  showCreateButton: boolean;
  searchTerm: string;
  selectedTemplateFilter: string;
  openCreateModal: () => void;
  t: (key: string) => string;
}

function buildEmptyStateConfig({
  hasFilterApplied,
  showCreateButton,
  searchTerm,
  selectedTemplateFilter,
  openCreateModal,
  t,
}: BuildEmptyStateParams): EmptyStateConfig {
  const title: string = hasFilterApplied ? t('datasets.noResults') : t('datasets.noDatasets');
  const description: string = hasFilterApplied
    ? t('datasets.noResultsDescription')
    : t('datasets.noDatasetsDescription');
  const action: { label: string; onClick: () => void } | undefined =
    showCreateButton && !searchTerm && selectedTemplateFilter === 'all'
      ? { label: t('datasets.createDataset'), onClick: openCreateModal }
      : undefined;

  return { title, description, action };
}

interface DatasetCardGridProps {
  readonly datasets: Dataset[];
  readonly templateFamilyIndex: Map<string, TemplateFamilyResponse>;
  readonly selectedDatasetIds: ReadonlySet<string>;
  readonly onEdit: (d: Dataset) => void;
  readonly onDuplicate: (d: Dataset) => void;
  readonly onDelete: (d: Dataset) => void;
  readonly onRename: (d: Dataset, newName: string) => void;
  readonly onDownload: (d: Dataset) => void;
  readonly emptyState: EmptyStateConfig;
}

function DatasetCardGrid({
  datasets,
  templateFamilyIndex,
  selectedDatasetIds,
  onEdit,
  onDuplicate,
  onDelete,
  onRename,
  onDownload,
  emptyState,
}: DatasetCardGridProps): JSX.Element {
  if (datasets.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        title={emptyState.title}
        description={emptyState.description}
        action={emptyState.action}
        size="md"
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
      {datasets.map((dataset) => (
        <DatasetCard
          key={dataset.id}
          dataset={dataset}
          template={templateFamilyIndex.get(dataset.templateVersionId)}
          onEdit={onEdit}
          onDuplicate={onDuplicate}
          onDelete={onDelete}
          onRename={onRename}
          onDownload={onDownload}
          isSelected={selectedDatasetIds.has(dataset.id)}
        />
      ))}
    </div>
  );
}

interface DatasetListState {
  crud: ReturnType<typeof useDatasetCrud>;
  deletion: ReturnType<typeof useDeleteConfirmation>;
  filtering: ReturnType<typeof useDatasetFiltering>;
  uniqueTemplateVersionIds: string[];
  templateFamilyIndex: Map<string, TemplateFamilyResponse>;
  handleSearchChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleSortChange: (value: string) => void;
}

function useDatasetListState({
  maxItems,
  onDatasetSelect,
}: {
  maxItems: number | undefined;
  onDatasetSelect: ((dataset: Dataset) => void) | undefined;
}): DatasetListState {
  const templateFamilies = useDocumentBuilderStore((state) => state.templateFamilies);
  const deleteDataset = useDocumentBuilderStore((state) => state.deleteDataset);
  const crud = useDatasetCrud({ onDatasetSelect });
  const deletion = useDeleteConfirmation(deleteDataset);
  const filtering = useDatasetFiltering({ datasets: crud.datasets, maxItems });

  const uniqueTemplateVersionIds = [...new Set(crud.datasets.map((d) => d.templateVersionId))];
  const templateFamilyIndex = new Map(templateFamilies.map((f) => [f.id, f]));

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>): void =>
    filtering.setSearchTerm(e.target.value);
  const handleSortChange = (value: string): void => {
    const [field, order] = value.split('-') as [
      typeof filtering.sortBy,
      typeof filtering.sortOrder,
    ];
    filtering.setSortBy(field);
    filtering.setSortOrder(order);
  };

  return {
    crud,
    deletion,
    filtering,
    uniqueTemplateVersionIds,
    templateFamilyIndex,
    handleSearchChange,
    handleSortChange,
  };
}

interface DatasetModalsProps {
  readonly crud: ReturnType<typeof useDatasetCrud>;
  readonly deletion: ReturnType<typeof useDeleteConfirmation>;
  readonly deleteMessage: string;
}

function DatasetModals({ crud, deletion, deleteMessage }: DatasetModalsProps): JSX.Element {
  const { t } = useTranslation('omakase.editor');
  return (
    <>
      <CreateDatasetModal
        isOpen={crud.showCreateModal}
        onClose={crud.closeCreateModal}
        onSuccess={crud.handleCreate}
      />
      <ConfirmDialog
        isOpen={deletion.pendingDeleteId !== null}
        onClose={deletion.cancelDelete}
        onConfirm={deletion.confirmDelete}
        title={t('dataset.delete.title')}
        message={deleteMessage}
        confirmText={t('dataset.delete.confirm')}
        variant="danger"
      />
      <ExportJSON
        isOpen={crud.showExportModal}
        onClose={crud.closeExportModal}
        preselectedDatasets={crud.selectedForExport}
      />
    </>
  );
}

function getDeleteMessage(
  crud: ReturnType<typeof useDatasetCrud>,
  deletion: ReturnType<typeof useDeleteConfirmation>,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const pendingDataset: Dataset | undefined = deletion.pendingDeleteId
    ? crud.getDataset(deletion.pendingDeleteId)
    : undefined;
  return pendingDataset ? t('dataset.delete.message', { name: pendingDataset.name }) : '';
}

export function DatasetList({
  showCreateButton = true,
  maxItems,
  onDatasetSelect,
  selectedDatasetIds = EMPTY_SELECTION,
}: DatasetListProps): JSX.Element {
  const { t } = useTranslation('omakase.editor');
  const state = useDatasetListState({ maxItems, onDatasetSelect });
  const { crud, deletion, filtering, uniqueTemplateVersionIds, templateFamilyIndex } = state;

  const hasFilterApplied =
    Boolean(filtering.searchTerm) || filtering.selectedTemplateFilter !== 'all';
  const emptyState = buildEmptyStateConfig({
    hasFilterApplied,
    showCreateButton,
    searchTerm: filtering.searchTerm,
    selectedTemplateFilter: filtering.selectedTemplateFilter,
    openCreateModal: crud.openCreateModal,
    t,
  });

  return (
    <div className="space-y-6">
      <DatasetToolbar
        searchTerm={filtering.searchTerm}
        onSearchChange={state.handleSearchChange}
        selectedTemplateFilter={filtering.selectedTemplateFilter}
        onTemplateFilterChange={filtering.setSelectedTemplateFilter}
        sortValue={`${filtering.sortBy}-${filtering.sortOrder}`}
        onSortChange={state.handleSortChange}
        uniqueTemplateVersionIds={uniqueTemplateVersionIds}
        templateFamilyIndex={templateFamilyIndex}
        hasDatasets={filtering.filteredAndSortedDatasets.length > 0}
        showCreateButton={showCreateButton}
        onBulkExport={crud.handleBulkExport}
        onCreateNew={crud.openCreateModal}
      />

      <DatasetCardGrid
        datasets={filtering.filteredAndSortedDatasets}
        templateFamilyIndex={templateFamilyIndex}
        selectedDatasetIds={selectedDatasetIds}
        onEdit={(d: Dataset) => crud.handleEdit(d.id)}
        onDuplicate={(d: Dataset) => crud.handleClone(d.id)}
        onDelete={(d: Dataset) => deletion.requestDelete(d.id)}
        onRename={(d: Dataset, newName: string) => crud.handleRename(d.id, newName)}
        onDownload={(d: Dataset) => crud.handleExport(d.id)}
        emptyState={emptyState}
      />

      <DatasetModals
        crud={crud}
        deletion={deletion}
        deleteMessage={getDeleteMessage(crud, deletion, t)}
      />
    </div>
  );
}
