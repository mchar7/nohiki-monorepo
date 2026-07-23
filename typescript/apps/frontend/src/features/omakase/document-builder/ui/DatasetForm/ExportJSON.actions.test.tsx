import type { RenderResult } from '@testing-library/react';
import { fireEvent, render, screen } from '@testing-library/react';
import type React from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import type { Dataset } from '../../model/index.ts';
import { useDocumentBuilderStore } from '../../model/index.ts';
import { ExportJSON } from './ExportJSON.tsx';

const EXPORT_RE = /export/iu;
const EXPORT_1_RE = /export \(1\)/iu;
const CANCEL_RE = /cancel/iu;

function renderWithProviders(ui: React.ReactElement): RenderResult {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);
}

const mockDatasets: Dataset[] = [
  {
    id: 'dataset-1',
    name: 'John Doe Resume',
    templateVersionId: 'version-1',
    data: { full_name: 'John Doe' },
    createdAt: new Date('2024-01-01').toISOString(),
    updatedAt: new Date('2024-01-01').toISOString(),
  },
  {
    id: 'dataset-2',
    name: 'Jane Smith Resume',
    templateVersionId: 'version-2',
    data: { full_name: 'Jane Smith' },
    createdAt: new Date('2024-01-01').toISOString(),
    updatedAt: new Date('2024-01-01').toISOString(),
  },
];

const defaultProps: React.ComponentProps<typeof ExportJSON> = {
  isOpen: true,
  onClose: vi.fn<() => void>(),
};

const getCheckboxByDatasetId = (datasetId: string): HTMLElement =>
  screen.getByRole('checkbox', {
    name: new RegExp(datasetId === 'dataset-1' ? 'John Doe Resume' : 'Jane Smith Resume', 'iu'),
  });

describe('ExportJSON - export actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDocumentBuilderStore.setState({ datasets: mockDatasets });
  });

  test('disables export button when no datasets selected', () => {
    renderWithProviders(<ExportJSON {...defaultProps} />);

    const exportButton = screen.getByRole('button', { name: EXPORT_RE });
    expect(exportButton).toBeDisabled();
  });

  test('enables export button when datasets are selected', () => {
    renderWithProviders(<ExportJSON {...defaultProps} />);

    fireEvent.click(getCheckboxByDatasetId('dataset-1'));

    const exportButton = screen.getByRole('button', { name: EXPORT_1_RE });
    expect(exportButton).not.toBeDisabled();
  });

  test('resets selection on close', () => {
    const onClose = vi.fn();
    renderWithProviders(<ExportJSON {...defaultProps} onClose={onClose} />);

    fireEvent.click(getCheckboxByDatasetId('dataset-1'));
    fireEvent.click(screen.getByRole('button', { name: CANCEL_RE }));

    expect(onClose).toHaveBeenCalled();
  });

  test('calls download function when export is clicked', () => {
    const createObjectUrlSpy = vi.spyOn(URL, 'createObjectURL');

    renderWithProviders(<ExportJSON {...defaultProps} />);

    fireEvent.click(getCheckboxByDatasetId('dataset-1'));
    fireEvent.click(screen.getByRole('button', { name: EXPORT_1_RE }));

    expect(createObjectUrlSpy).toHaveBeenCalled();
  });
});
