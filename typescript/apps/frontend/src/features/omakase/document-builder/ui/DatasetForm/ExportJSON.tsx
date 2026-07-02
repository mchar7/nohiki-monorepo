import { config } from '@shared/config/index.ts';

/** Divisor to derive per-file download stagger delay from the debounce delay */
const BATCH_DOWNLOAD_STAGGER_DIVISOR: number = 3;
const BULLET_SEPARATOR = ' \u2022 ';
const PIPE_SEPARATOR = '|';

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Label,
} from '@shared/ui/index.ts';
import { CheckCircle, Download, FileText } from 'lucide-react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CONTENT_TYPES } from '@/shared/config/index.ts';
import type { Dataset } from '../../model/index.ts';
import { useDocumentBuilderStore } from '../../model/index.ts';

interface ExportJsonProps {
  isOpen: boolean;
  onClose: () => void;
  preselectedDatasets?: string[];
}

interface DatasetCheckboxItemProps {
  readonly dataset: Dataset;
  readonly isSelected: boolean;
  readonly onToggle: (datasetId: string) => void;
}

function DatasetCheckboxItem({
  dataset,
  isSelected,
  onToggle,
}: DatasetCheckboxItemProps): JSX.Element {
  const { t } = useTranslation(['omakase.editor']);

  const handleCheckedChange = (): void => {
    onToggle(dataset.id);
  };

  return (
    <div className="flex items-center gap-3 border-b p-3 last:border-b-0 hover:bg-accent">
      <Checkbox
        id={`dataset-${dataset.id}`}
        checked={isSelected}
        onCheckedChange={handleCheckedChange}
      />
      <Label htmlFor={`dataset-${dataset.id}`} className="min-w-0 flex-1 cursor-pointer">
        <div className="flex items-center gap-2">
          <FileText className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate font-medium">{dataset.name}</span>
        </div>
        <div className="text-muted-foreground text-sm">
          {typeof dataset.data.full_name === 'string' ? dataset.data.full_name : ''}
          {BULLET_SEPARATOR}
          {typeof dataset.data.professional_title === 'string'
            ? dataset.data.professional_title
            : ''}
        </div>
        <div className="text-muted-foreground/80 text-xs">
          {t('omakase.editor:export.created', {
            date: new Date(dataset.createdAt).toLocaleDateString(),
          })}
        </div>
      </Label>
      {isSelected ? <CheckCircle className="size-5 shrink-0 text-success" /> : null}
    </div>
  );
}

function downloadJson(dataset: Dataset): void {
  const jsonData = JSON.stringify(dataset.data, null, 2);
  const blob = new Blob([jsonData], { type: CONTENT_TYPES.JSON });
  const url = URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.href = url;
  link.download = `${dataset.name}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function exportDatasets(datasets: Dataset[]): void {
  if (datasets.length === 1 && datasets[0] !== undefined) {
    downloadJson(datasets[0]);
  } else {
    for (const [index, dataset] of datasets.entries()) {
      setTimeout(
        () => downloadJson(dataset),
        index * (config.ui.debounceDelay / BATCH_DOWNLOAD_STAGGER_DIVISOR),
      );
    }
  }
}

interface DatasetSelectionListProps {
  readonly availableDatasets: Dataset[];
  readonly selectedDatasets: Set<string>;
  readonly selectedCount: number;
  readonly onToggle: (datasetId: string) => void;
  readonly onSelectAll: () => void;
  readonly onSelectNone: () => void;
}

function DatasetSelectionList({
  availableDatasets,
  selectedDatasets,
  selectedCount,
  onToggle,
  onSelectAll,
  onSelectNone,
}: DatasetSelectionListProps): JSX.Element {
  const { t } = useTranslation(['omakase.editor', 'common']);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-muted-foreground text-sm">
          {t('omakase.editor:export.selectPrompt', { count: selectedCount })}
        </p>
        <div className="flex gap-2">
          <Button variant="link" size="sm" onClick={onSelectAll} className="h-auto p-0 text-sm">
            {t('common:actions.selectAll')}
          </Button>
          <span className="text-muted-foreground/50">{PIPE_SEPARATOR}</span>
          <Button variant="link" size="sm" onClick={onSelectNone} className="h-auto p-0 text-sm">
            {t('common:actions.deselectAll')}
          </Button>
        </div>
      </div>

      <div className="max-h-64 overflow-y-auto rounded-lg border">
        {availableDatasets.map((dataset) => (
          <DatasetCheckboxItem
            key={dataset.id}
            dataset={dataset}
            isSelected={selectedDatasets.has(dataset.id)}
            onToggle={onToggle}
          />
        ))}
      </div>

      {selectedCount > 1 ? (
        <div className="rounded-lg border bg-accent p-3">
          <p className="text-accent-foreground text-sm">
            {t('omakase.editor:export.multipleFilesNote')}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function useDatasetSelection(
  datasets: Dataset[] | undefined,
  preselectedDatasets: string[],
): {
  selectedDatasets: Set<string>;
  toggleDataset: (datasetId: string) => void;
  selectAll: () => void;
  selectNone: () => void;
  reset: () => void;
} {
  const [selectedDatasets, setSelectedDatasets] = useState<Set<string>>(
    new Set(preselectedDatasets),
  );

  const toggleDataset = (datasetId: string): void => {
    setSelectedDatasets((prev) => {
      const next = new Set(prev);
      if (next.has(datasetId)) {
        next.delete(datasetId);
      } else {
        next.add(datasetId);
      }
      return next;
    });
  };

  const selectAll = (): void => {
    setSelectedDatasets(new Set(Array.isArray(datasets) ? datasets.map((d) => d.id) : []));
  };

  const selectNone = (): void => {
    setSelectedDatasets(new Set());
  };

  const reset = (): void => {
    setSelectedDatasets(new Set(preselectedDatasets));
  };

  return { selectedDatasets, toggleDataset, selectAll, selectNone, reset };
}

export function ExportJSON({
  isOpen,
  onClose,
  preselectedDatasets = [],
}: Readonly<ExportJsonProps>): JSX.Element {
  const { t } = useTranslation(['omakase.editor', 'common']);
  const datasets = useDocumentBuilderStore((state) => state.datasets);
  const { selectedDatasets, toggleDataset, selectAll, selectNone, reset } = useDatasetSelection(
    datasets,
    preselectedDatasets,
  );

  const handleClose = (): void => {
    reset();
    onClose();
  };

  const handleExportSelected = (): void => {
    const selected = Array.isArray(datasets)
      ? datasets.filter((d) => selectedDatasets.has(d.id))
      : [];
    exportDatasets(selected);
    handleClose();
  };

  const selectedCount = selectedDatasets.size;
  const availableDatasets = Array.isArray(datasets) ? datasets.filter((d) => d.data) : [];

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="max-h-[90vh] max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('omakase.editor:export.title')}</DialogTitle>
          <DialogDescription>{t('omakase.editor:export.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {availableDatasets.length === 0 ? (
            <div className="py-8 text-center">
              <FileText className="mx-auto mb-4 size-12 text-muted-foreground" />
              <p className="text-muted-foreground">{t('omakase.editor:export.noDatasets')}</p>
            </div>
          ) : (
            <DatasetSelectionList
              availableDatasets={availableDatasets}
              selectedDatasets={selectedDatasets}
              selectedCount={selectedCount}
              onToggle={toggleDataset}
              onSelectAll={selectAll}
              onSelectNone={selectNone}
            />
          )}
        </div>

        <div className="flex justify-end gap-3 pt-4">
          <Button variant="outline" onClick={handleClose}>
            {t('common:actions.cancel')}
          </Button>
          <Button
            onClick={handleExportSelected}
            disabled={selectedCount === 0}
            className="flex items-center gap-2"
          >
            <Download className="size-4" />
            {selectedCount > 0
              ? `${t('common:actions.export')} (${selectedCount})`
              : t('common:actions.export')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
