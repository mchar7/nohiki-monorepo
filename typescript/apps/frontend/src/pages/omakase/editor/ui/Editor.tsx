import {
  type Dataset,
  type DatasetData,
  EditorHeader,
  EditorModals,
  ResponsiveEditor,
  useDocumentBuilderStore,
  useDocumentOperations,
  useEditorModals,
  useTemplateLoader,
} from '@features/omakase/document-builder/index.ts';
import { useNavigate, useParams } from '@tanstack/react-router';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { TemplateResponse } from '@/shared/api';
import { useConnectivitySafe } from '@/shared/lib/contexts/index.ts';
import {
  handleNavigationPromise,
  logComponentError,
  useDocumentTitle,
} from '@/shared/lib/index.ts';
import { ConnectionRequiredState } from '@/shared/ui/connection-required-state.tsx';
import { LoadingSpinner } from '@/shared/ui/loading-spinner.tsx';
import { PanelEmptyState } from '@/shared/ui/panel-empty-state.tsx';
import { PanelErrorState } from '@/shared/ui/panel-error-state.tsx';

function LoadingState(): JSX.Element {
  const { t } = useTranslation('omakase.editor');
  return (
    <LoadingSpinner
      size="lg"
      text={t('loading.templates')}
      description={t('loading.templatesDescription')}
      centered={true}
    />
  );
}

function ErrorState({ error }: { readonly error: string }): JSX.Element {
  const { t } = useTranslation('omakase.editor');

  const handleRetry = (): void => {
    globalThis.location.reload();
  };

  return (
    <div className="flex h-screen items-center justify-center p-6">
      <PanelErrorState
        title={t('errors.failedToLoadTemplates')}
        error={error}
        onRetry={handleRetry}
      />
    </div>
  );
}

function OfflineState({ onRetry }: { readonly onRetry: () => void }): JSX.Element {
  return (
    <div className="flex h-screen items-center justify-center p-6">
      <ConnectionRequiredState size="lg" onRetry={onRetry} />
    </div>
  );
}

interface DocumentEmptyStateProps {
  onCreateDataset: () => void;
  hasDatasets: boolean;
}

const DocumentEmptyState = ({
  onCreateDataset,
  hasDatasets,
}: DocumentEmptyStateProps): JSX.Element => (
  <PanelEmptyState variant="document" onAction={onCreateDataset} hasDatasets={hasDatasets} />
);

/** Selects editor-related store values and external hook results. */
function useEditorSelectors(): {
  datasetId: string | undefined;
  setCachedHtml: (id: string, htmlData: string) => void;
  clearCachedHtml: (id: string) => void;
  datasets: Dataset<DatasetData>[];
  currentTemplate: TemplateResponse | null;
  getDataset: (id: string) => Dataset<DatasetData> | undefined;
  setActiveDataset: (id: string) => void;
  createDataset: (params: {
    name: string;
    templateVersionId: string;
    data: Record<string, unknown>;
  }) => string;
  modals: ReturnType<typeof useEditorModals>;
  isDownloadingPdf: boolean;
  downloadPdf: (params: {
    template_version_id: string;
    data: Record<string, unknown>;
    filename: string;
  }) => Promise<void>;
  templatesLoading: boolean;
  templatesError: string | null;
  isConfirmedOffline: boolean;
  hasChecked: boolean;
  isChecking: boolean;
  forceCheck: () => Promise<boolean>;
  navigate: ReturnType<typeof useNavigate>;
} {
  const { datasetId } = useParams({ strict: false });
  const navigate = useNavigate();
  const { isOffline, hasChecked, isChecking, forceCheck } = useConnectivitySafe();

  const setCachedHtml = useDocumentBuilderStore((s) => s.setCachedHtml);
  const clearCachedHtml = useDocumentBuilderStore((s) => s.clearCachedHtml);
  const datasets = useDocumentBuilderStore((s) => s.datasets);
  const currentTemplate = useDocumentBuilderStore((s) => s.currentTemplate);
  const getDataset = useDocumentBuilderStore((s) => s.getDataset);
  const setActiveDataset = useDocumentBuilderStore((s) => s.setActiveDataset);
  const createDataset = useDocumentBuilderStore((s) => s.createDataset);

  const modals = useEditorModals();
  const { isDownloadingPdf, downloadPdf } = useDocumentOperations();
  const { isLoading: templatesLoading, error: templatesError } = useTemplateLoader();

  return {
    datasetId,
    setCachedHtml,
    clearCachedHtml,
    datasets,
    currentTemplate,
    getDataset,
    setActiveDataset,
    createDataset,
    modals,
    isDownloadingPdf,
    downloadPdf,
    templatesLoading,
    templatesError,
    isConfirmedOffline: hasChecked && isOffline,
    hasChecked,
    isChecking,
    forceCheck,
    navigate,
  };
}

/** Builds editor actions from store selectors: navigation, dataset creation, PDF download. */
function useEditorActions(sel: ReturnType<typeof useEditorSelectors>): {
  currentDataset: Dataset<DatasetData> | null;
  navigateToDataset: (id: string) => void;
  createNewDataset: () => void;
  handleDownloadPdf: () => Promise<void>;
  handleConfirmNavigation: () => void;
  handleCancelNavigation: () => void;
  renderEmptyState: () => JSX.Element;
} {
  const { t } = useTranslation('omakase.editor');

  const currentDataset = sel.datasetId ? sel.getDataset(sel.datasetId) || null : null;

  const navigateToDataset = (id: string): void => {
    sel.setActiveDataset(id);
    handleNavigationPromise(
      sel.navigate({ to: '/documents/editor/$datasetId', params: { datasetId: id } }),
    );
  };

  const createNewDataset = (): void => {
    if (!sel.currentTemplate) {
      return;
    }
    const newId = sel.createDataset({
      name: t('document.untitled'),
      templateVersionId: sel.currentTemplate.id,
      data: {},
    });
    navigateToDataset(newId);
  };

  const handleDownloadPdf = async (): Promise<void> => {
    if (!(currentDataset && sel.currentTemplate)) {
      return;
    }
    try {
      const filename = `${currentDataset.name.replaceAll(/[^a-z0-9]/giu, '_').toLowerCase()}.pdf`;
      await sel.downloadPdf({
        template_version_id: sel.currentTemplate.id,
        data: currentDataset.data,
        filename,
      });
    } catch (error) {
      logComponentError('Editor', error, { context: 'Failed to download PDF' });
    }
  };

  const handleConfirmNavigation = (): void => {
    const target = sel.modals.confirmNavigation();
    if (target) {
      navigateToDataset(target);
    }
  };

  return {
    currentDataset,
    navigateToDataset,
    createNewDataset,
    handleDownloadPdf,
    handleConfirmNavigation,
    handleCancelNavigation: () => sel.modals.cancelNavigation(),
    renderEmptyState: () => (
      <DocumentEmptyState
        onCreateDataset={createNewDataset}
        hasDatasets={sel.datasets.length > 0}
      />
    ),
  };
}

export function Editor(): JSX.Element {
  const sel = useEditorSelectors();
  const actions = useEditorActions(sel);
  const { t } = useTranslation('omakase.editor');
  useDocumentTitle(t('title'));

  if (sel.isConfirmedOffline) {
    return <OfflineState onRetry={sel.forceCheck} />;
  }

  if ((!sel.hasChecked && sel.isChecking) || sel.templatesLoading) {
    return <LoadingState />;
  }

  if (sel.templatesError) {
    return <ErrorState error={sel.templatesError} />;
  }

  return (
    <div className="flex h-screen flex-col">
      <EditorHeader
        currentDatasetName={actions.currentDataset?.name}
        formIsDirty={sel.modals.formIsDirty}
        onCreateDataset={actions.createNewDataset}
        onDownloadPdf={actions.handleDownloadPdf}
        onImport={sel.modals.openImportModal}
        onExport={sel.modals.openExportModal}
        isDownloading={sel.isDownloadingPdf}
      />

      <ResponsiveEditor
        currentDataset={actions.currentDataset ?? null}
        currentTemplate={sel.currentTemplate}
        onDataChange={sel.modals.handleDataChange}
        onHtmlGenerated={sel.setCachedHtml}
        onHtmlCleared={sel.clearCachedHtml}
        EmptyState={actions.renderEmptyState}
      />

      <EditorModals
        showImportModal={sel.modals.showImportModal}
        showExportModal={sel.modals.showExportModal}
        showUnsavedDialog={sel.modals.showUnsavedDialog}
        currentDatasetId={actions.currentDataset?.id}
        onImportModalChange={sel.modals.setShowImportModal}
        onExportModalChange={sel.modals.setShowExportModal}
        onUnsavedDialogChange={sel.modals.setShowUnsavedDialog}
        onConfirmNavigation={actions.handleConfirmNavigation}
        onCancelNavigation={actions.handleCancelNavigation}
      />
    </div>
  );
}
