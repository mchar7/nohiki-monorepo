import { useState } from 'react';

interface EditorModalsState {
  readonly showImportModal: boolean;
  readonly showExportModal: boolean;
  readonly showUnsavedDialog: boolean;
  readonly pendingNavigation: string | null;
  readonly formIsDirty: boolean;
}

interface EditorModalsActions {
  readonly openImportModal: () => void;
  readonly closeImportModal: () => void;
  readonly setShowImportModal: (open: boolean) => void;
  readonly openExportModal: () => void;
  readonly closeExportModal: () => void;
  readonly setShowExportModal: (open: boolean) => void;
  readonly setShowUnsavedDialog: (open: boolean) => void;
  readonly setFormIsDirty: (isDirty: boolean) => void;
  readonly requestNavigation: (datasetId: string) => void;
  readonly confirmNavigation: () => string | null;
  readonly cancelNavigation: () => void;
  readonly handleDataChange: (isDirty: boolean) => void;
}

type EditorModalsResult = EditorModalsState & EditorModalsActions;

/**
 * Manages modal/dialog state for the Editor page.
 *
 * Encapsulates import modal, export modal, unsaved changes dialog,
 * and pending navigation state into a single cohesive hook.
 */
export function useEditorModals(): EditorModalsResult {
  const [showImportModal, setShowImportModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showUnsavedDialog, setShowUnsavedDialog] = useState(false);
  const [pendingNavigation, setPendingNavigation] = useState<string | null>(null);
  const [formIsDirty, setFormIsDirty] = useState(false);

  const openImportModal = () => setShowImportModal(true);
  const closeImportModal = () => setShowImportModal(false);
  const openExportModal = () => setShowExportModal(true);
  const closeExportModal = () => setShowExportModal(false);

  const requestNavigation = (datasetId: string) => {
    setPendingNavigation(datasetId);
    setShowUnsavedDialog(true);
  };

  const confirmNavigation = (): string | null => {
    const target = pendingNavigation;
    setPendingNavigation(null);
    setShowUnsavedDialog(false);
    return target;
  };

  const cancelNavigation = () => {
    setPendingNavigation(null);
    setShowUnsavedDialog(false);
  };

  const handleDataChange = (isDirty: boolean) => {
    setFormIsDirty(isDirty);
  };

  return {
    showImportModal,
    showExportModal,
    showUnsavedDialog,
    pendingNavigation,
    formIsDirty,
    openImportModal,
    closeImportModal,
    setShowImportModal,
    openExportModal,
    closeExportModal,
    setShowExportModal,
    setShowUnsavedDialog,
    setFormIsDirty,
    requestNavigation,
    confirmNavigation,
    cancelNavigation,
    handleDataChange,
  };
}
