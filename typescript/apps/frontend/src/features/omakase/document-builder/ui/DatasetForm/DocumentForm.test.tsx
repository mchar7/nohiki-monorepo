import type { RenderResult } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import type React from 'react';
import type { Control, UseFormHandleSubmit, UseFormRegister } from 'react-hook-form';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { i18n } from '@/test/setup.ts';
import { DocumentForm } from './DocumentForm.tsx';

function renderWithProviders(ui: React.ReactElement): RenderResult {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);
}

// Mock the useDocumentForm hook
const mockRegister = vi.fn() as unknown as UseFormRegister<Record<string, unknown>>;
const mockHandleSubmit = vi.fn((fn: () => void) => (e: Event): void => {
  e?.preventDefault?.();
  fn?.();
}) as unknown as UseFormHandleSubmit<Record<string, unknown>>;
const mockOnSubmit = vi.fn<(data: Record<string, unknown>) => void>();

vi.mock('../../lib/useDocumentForm', () => ({
  useDocumentForm: vi.fn(),
}));

import { useDocumentForm } from '../../lib/useDocumentForm.ts';

const mockUseDocumentForm: ReturnType<typeof vi.mocked<typeof useDocumentForm>> =
  vi.mocked(useDocumentForm);

const baseHookReturn: ReturnType<typeof useDocumentForm> = {
  dataset: {
    id: 'test-dataset',
    name: 'Test Dataset',
    templateVersionId: 'version-1',
    data: { name: 'John Doe' },
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-01T00:00:00Z',
  },
  template: {
    id: 'version-1',
    namespace: 'default',
    name: 'Test Template',
    version: '1.0.0',
    template_content: '<html>{{ name }}</html>',
    content_schema: null,
    description: 'A test template',
    access_scope: 'PUBLIC',
    owner_id: null,
    is_active: true,
  },
  resolvedSchema: {
    type: 'object',
    properties: {
      name: { type: 'string', title: 'Name' },
    },
  },
  isValid: true,
  validationErrors: [],
  isLoadingSchema: false,
  form: {
    register: mockRegister,
    handleSubmit: mockHandleSubmit,
    control: {} as Control<Record<string, unknown>>,
    errors: {},
    onSubmit: mockOnSubmit,
  },
};

describe('DocumentForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseDocumentForm.mockReturnValue(baseHookReturn as ReturnType<typeof useDocumentForm>);
  });

  test('renders loading state when dataset not found', () => {
    mockUseDocumentForm.mockReturnValue({
      ...baseHookReturn,
      dataset: undefined,
    } as ReturnType<typeof useDocumentForm>);

    renderWithProviders(<DocumentForm datasetId="nonexistent" />);

    expect(screen.getByText('Failed to load document')).toBeInTheDocument();
  });

  test('renders error state when template not found', () => {
    mockUseDocumentForm.mockReturnValue({
      ...baseHookReturn,
      template: null,
    } as ReturnType<typeof useDocumentForm>);

    renderWithProviders(<DocumentForm datasetId="test-dataset" />);

    expect(screen.getByText('Failed to load document')).toBeInTheDocument();
  });

  test('renders error state when schema is invalid', () => {
    mockUseDocumentForm.mockReturnValue({
      ...baseHookReturn,
      isValid: false,
      validationErrors: ['Schema error 1', 'Schema error 2'],
    } as ReturnType<typeof useDocumentForm>);

    renderWithProviders(<DocumentForm datasetId="test-dataset" />);

    expect(screen.getByText('Invalid Template Schema')).toBeInTheDocument();
  });

  test('renders error state when resolved schema is null', () => {
    mockUseDocumentForm.mockReturnValue({
      ...baseHookReturn,
      resolvedSchema: null,
    } as ReturnType<typeof useDocumentForm>);

    renderWithProviders(<DocumentForm datasetId="test-dataset" />);

    expect(screen.getByText('Schema Processing Error')).toBeInTheDocument();
  });

  test('renders form when all data is valid', () => {
    renderWithProviders(<DocumentForm datasetId="test-dataset" />);

    // Form should be present (use querySelector since form has no accessible name)
    expect(document.querySelector('form')).toBeTruthy();
  });
});
