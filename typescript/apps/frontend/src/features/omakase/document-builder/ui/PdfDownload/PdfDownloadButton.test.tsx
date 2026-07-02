import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { JSX } from 'react';
import { I18nextProvider } from 'react-i18next';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import type { TemplateResponse } from '@/shared/api';
import { i18n } from '@/test/setup.ts';
import type { Dataset } from '../../model/index.ts';
import { PdfDownloadButton } from './PdfDownloadButton.tsx';

const mockMutateAsync: ReturnType<typeof vi.fn> = vi.hoisted(() => vi.fn());
const mockUseDownloadDocument: ReturnType<typeof vi.fn> = vi.hoisted(() =>
  vi.fn(() => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
    isError: false,
    error: null,
  })),
);

vi.mock('../../api/index.ts', () => ({
  useDownloadDocument: mockUseDownloadDocument,
}));

vi.mock('../../lib/filename.ts', () => ({
  generatePdfFilename: vi.fn(() => 'test-dataset-test-template.pdf'),
}));

const mockDataset: Dataset = {
  id: 'test-dataset',
  name: 'Test Dataset',
  templateVersionId: 'version-1',
  data: {
    name: 'John Doe',
    title: 'Software Engineer',
  },
  createdAt: '2024-01-01T00:00:00Z',
  updatedAt: '2024-01-01T00:00:00Z',
};

const mockTemplate: TemplateResponse = {
  id: 'version-1',
  namespace: 'default',
  name: 'test_template',
  display_name: 'Test Template',
  version: '1.0.0',
  template_content: '<html>{{name}}</html>',
  content_schema: null,
  description: 'A test template',
  access_scope: 'PUBLIC',
  owner_id: null,
  is_active: true,
};

function TestWrapper({ children }: { children: React.ReactNode }): JSX.Element {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return (
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
    </QueryClientProvider>
  );
}

describe('PdfDownloadButton - rendering', () => {
  beforeEach(() => {
    mockMutateAsync.mockReset();
    mockUseDownloadDocument.mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: false,
      isError: false,
      error: null,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  test('renders download button initially', () => {
    render(
      <TestWrapper>
        <PdfDownloadButton dataset={mockDataset} template={mockTemplate} />
      </TestWrapper>,
    );

    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument();
  });

  test('renders custom children when provided', () => {
    render(
      <TestWrapper>
        <PdfDownloadButton dataset={mockDataset} template={mockTemplate}>
          Custom Download Text
        </PdfDownloadButton>
      </TestWrapper>,
    );

    expect(screen.getByRole('button', { name: 'Custom Download Text' })).toBeInTheDocument();
  });

  test('applies custom className', () => {
    render(
      <TestWrapper>
        <PdfDownloadButton dataset={mockDataset} template={mockTemplate} className="custom-class" />
      </TestWrapper>,
    );

    const button = screen.getByRole('button', { name: 'Download' });
    expect(button).toHaveClass('custom-class');
  });
});

describe('PdfDownloadButton - click behavior', () => {
  beforeEach(() => {
    mockMutateAsync.mockReset();
    mockUseDownloadDocument.mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: false,
      isError: false,
      error: null,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  test('calls PDF generation when clicked', async () => {
    mockMutateAsync.mockResolvedValue(undefined);

    render(
      <TestWrapper>
        <PdfDownloadButton dataset={mockDataset} template={mockTemplate} />
      </TestWrapper>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Download' }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        template_version_id: mockTemplate.id,
        data: mockDataset.data,
        output_format: 'pdf',
        filename: 'test-dataset-test-template.pdf',
      });
    });
  });
});

describe('PdfDownloadButton - states', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  test('shows loading state during PDF generation', () => {
    mockUseDownloadDocument.mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: true,
      isError: false,
      error: null,
    });

    render(
      <TestWrapper>
        <PdfDownloadButton dataset={mockDataset} template={mockTemplate} />
      </TestWrapper>,
    );

    expect(screen.getByText('Downloading...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  test('shows error message when generation fails', () => {
    mockUseDownloadDocument.mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: false,
      isError: true,
      error: { message: 'Generation failed' },
    });

    render(
      <TestWrapper>
        <PdfDownloadButton dataset={mockDataset} template={mockTemplate} />
      </TestWrapper>,
    );

    expect(screen.getByText('Generation failed')).toBeInTheDocument();
  });
});
