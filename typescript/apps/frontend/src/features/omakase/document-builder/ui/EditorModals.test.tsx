import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useSwipeToDismiss } from '@/shared/lib/index.ts';
import { EditorModals } from './EditorModals.tsx';

// Mock the hook to verify integration
vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useSwipeToDismiss: vi.fn(),
  };
});

// Mock internal forms to focus on EditorModals's behavior
vi.mock('./DatasetForm/ImportJSON.tsx', () => ({
  ImportJSON: vi.fn(({ onClose }) => (
    <button type="button" onClick={onClose} data-testid="import-json-close">
      Close Import
    </button>
  )),
}));

vi.mock('./DatasetForm/ExportJSON.tsx', () => ({
  ExportJSON: vi.fn(({ onClose }) => (
    <button type="button" onClick={onClose} data-testid="export-json-close">
      Close Export
    </button>
  )),
}));

describe('EditorModals', () => {
  const defaultProps = {
    showImportModal: false,
    showExportModal: false,
    showUnsavedDialog: false,
    onImportModalChange: vi.fn(),
    onExportModalChange: vi.fn(),
    onUnsavedDialogChange: vi.fn(),
    onConfirmNavigation: vi.fn(),
    onCancelNavigation: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders import modal when showImportModal is true', () => {
    render(<EditorModals {...defaultProps} showImportModal={true} />);
    // Translated string for modals.import.title is "Import JSON Dataset"
    expect(screen.getByText('Import JSON Dataset')).toBeInTheDocument();
    expect(screen.getByText('Import a JSON file containing document data')).toBeInTheDocument();
  });

  test('renders export modal when showExportModal is true', () => {
    render(<EditorModals {...defaultProps} showExportModal={true} />);
    // Translated string for modals.export.title is "Export JSON Datasets"
    expect(screen.getByText('Export JSON Datasets')).toBeInTheDocument();
    expect(screen.getByText('Select datasets to export as JSON files')).toBeInTheDocument();
  });

  test('renders unsaved changes dialog when showUnsavedDialog is true', () => {
    render(<EditorModals {...defaultProps} showUnsavedDialog={true} />);
    expect(screen.getByText('Unsaved Changes')).toBeInTheDocument();
    expect(screen.getByText(/You have unsaved changes/iu)).toBeInTheDocument();
  });
  test('calls useSwipeToDismiss for both modals', () => {
    render(<EditorModals {...defaultProps} showImportModal={true} showExportModal={true} />);
    expect(useSwipeToDismiss).toHaveBeenCalledTimes(2);

    // Verifying parameters for both calls
    expect(useSwipeToDismiss).toHaveBeenCalledWith(
      expect.objectContaining({
        direction: 'right',
        enabled: true,
      }),
    );
  });

  test('triggers onImportModalChange(false) when import modal close is called', () => {
    render(<EditorModals {...defaultProps} showImportModal={true} />);
    const closeButton = screen.getByTestId('import-json-close');
    fireEvent.click(closeButton);
    expect(defaultProps.onImportModalChange).toHaveBeenCalledWith(false);
  });

  test('triggers onExportModalChange(false) when export modal close is called', () => {
    render(<EditorModals {...defaultProps} showExportModal={true} />);
    const closeButton = screen.getByTestId('export-json-close');
    fireEvent.click(closeButton);
    expect(defaultProps.onExportModalChange).toHaveBeenCalledWith(false);
  });
});
