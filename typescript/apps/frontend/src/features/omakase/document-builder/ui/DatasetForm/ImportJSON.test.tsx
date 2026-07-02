import type { RenderResult } from '@testing-library/react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type React from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { i18n } from '@/test/setup.ts';
import type { DatasetData } from '../../model/index.ts';
import { ImportJSON } from './ImportJSON.tsx';

const CANCEL_RE = /cancel/iu;
const BROWSE_RE = /browse/iu;
const IMPORT_RE = /import/iu;
const VALID_DATA_FOUND_RE = /valid data found/iu;
const PREVIEW_RE = /preview/iu;

const mockImportJsonData: ReturnType<typeof vi.fn> = vi.fn();
const mockClearValidation: ReturnType<typeof vi.fn> = vi.fn();

vi.mock('../../lib/useJsonImport.ts', () => ({
  useJsonImport: () => ({
    isValidating: false,
    importJsonData: mockImportJsonData,
    clearValidation: mockClearValidation,
  }),
}));

function renderWithProviders(ui: React.ReactElement): RenderResult {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);
}

const onClose = vi.fn<() => void>();
const onImport = vi.fn<(data: DatasetData) => void>();

describe('ImportJSON - rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders modal when open', () => {
    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} />);
    expect(screen.getByText('Import JSON Dataset')).toBeInTheDocument();
  });

  test('does not render when closed', () => {
    renderWithProviders(<ImportJSON isOpen={false} onClose={onClose} />);
    expect(screen.queryByText('Import JSON Dataset')).not.toBeInTheDocument();
  });

  test('has cancel button and file input', () => {
    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} />);
    expect(screen.getByRole('button', { name: CANCEL_RE })).toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeTruthy();
  });

  test('renders browse files button', () => {
    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} />);
    expect(screen.getByRole('button', { name: BROWSE_RE })).toBeInTheDocument();
  });

  test('renders import button disabled when no preview data', () => {
    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} />);
    const importBtn = screen.getByRole('button', { name: IMPORT_RE });
    expect(importBtn).toBeDisabled();
  });
});

describe('ImportJSON - successful validation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('shows preview after successful file selection', async () => {
    const parsedData = { name: 'John', email: 'john@example.com' };
    mockImportJsonData.mockReturnValueOnce({ success: true, data: parsedData });

    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} onImport={onImport} />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([JSON.stringify(parsedData)], 'data.json', { type: 'application/json' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(VALID_DATA_FOUND_RE)).toBeInTheDocument();
    });
  });

  test('displays field count in preview', async () => {
    const data = { a: 1, b: 2, c: 3 };
    mockImportJsonData.mockReturnValueOnce({ success: true, data });

    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([JSON.stringify(data)], 'data.json', { type: 'application/json' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(PREVIEW_RE)).toBeInTheDocument();
    });
  });
});

describe('ImportJSON - failed validation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('shows error after failed file validation', async () => {
    mockImportJsonData.mockReturnValueOnce({
      success: false,
      errors: ['Invalid JSON format'],
    });

    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['not json'], 'bad.json', { type: 'application/json' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('Invalid JSON format')).toBeInTheDocument();
    });
  });

  test('shows fallback error when no error messages provided', async () => {
    mockImportJsonData.mockReturnValueOnce({ success: false });

    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{}'], 'data.json', { type: 'application/json' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      // Fallback error text from i18n key import.invalidData
      expect(document.querySelector('.text-destructive')).toBeTruthy();
    });
  });

  test('does nothing when file input has no files', () => {
    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [] } });

    expect(mockImportJsonData).not.toHaveBeenCalled();
  });
});

describe('ImportJSON - import actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('enables import button after successful validation', async () => {
    mockImportJsonData.mockReturnValueOnce({
      success: true,
      data: { field: 'value' },
    });

    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} onImport={onImport} />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{"field":"value"}'], 'data.json', { type: 'application/json' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      const importBtn = screen.getByRole('button', { name: IMPORT_RE });
      expect(importBtn).not.toBeDisabled();
    });
  });

  test('calls onImport and closes on import button click', async () => {
    const user = userEvent.setup();
    const data = { name: 'Test' };
    mockImportJsonData.mockReturnValueOnce({ success: true, data });

    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} onImport={onImport} />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([JSON.stringify(data)], 'data.json', { type: 'application/json' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(VALID_DATA_FOUND_RE)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: IMPORT_RE }));

    expect(onImport).toHaveBeenCalledWith(data);
    expect(onClose).toHaveBeenCalled();
  });

  test('calls onClose and clears state on cancel', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ImportJSON isOpen={true} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: CANCEL_RE }));

    expect(mockClearValidation).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
