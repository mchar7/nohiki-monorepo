import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import type { AttachmentResponse, DocumentStatusResponse } from '@/shared/api';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/setup.ts';
import { EmptyState } from './DocumentEmptyState.tsx';
import { AllTabContent, GeneratedTabContent, UploadedTabContent } from './DocumentTabContent.tsx';
import type { QueryResult } from './DocumentTabContentModel.ts';

// Mock child components to isolate tab logic

vi.mock('./UnifiedDocumentCard.tsx', () => ({
  UnifiedDocumentCard: ({ document: doc }: { document: { type: string } }) => (
    <div data-testid={`card-${doc.type}`} />
  ),
}));

vi.mock('./DocumentTableSkeleton.tsx', () => ({
  DocumentTableSkeleton: () => <div data-testid="skeleton" />,
}));

vi.mock('@/features/attachments/index.ts', () => ({
  DOCUMENT_CATEGORIES: ['resume', 'cover_letter', 'portfolio', 'other'],
  loadCategory: () => null,
  UploadDialog: () => <button type="button">Upload</button>,
}));

type MockAttachment = AttachmentResponse;

type MockDocument = DocumentStatusResponse;

function makeAttachmentQuery(
  items: MockAttachment[],
  overrides: Partial<QueryResult<MockAttachment>> = {},
): QueryResult<MockAttachment> {
  return {
    data: { items, total: items.length },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

function makeDocumentQuery(
  items: MockDocument[],
  overrides: Partial<QueryResult<MockDocument>> = {},
): QueryResult<MockDocument> {
  return {
    data: { items, total: items.length },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

const ATTACHMENT: MockAttachment = {
  id: 'a1',
  user_id: 'u1',
  filename: 'resume.pdf',
  content_type: 'application/pdf',
  file_size: 1024,
  download_url: null,
  created_at: '2025-01-01T00:00:00.000Z',
};

const DOCUMENT: MockDocument = {
  request_id: 'req-001',
  status: 'completed',
  download_url: null,
  error: null,
  output_format: 'pdf',
  created_at: '2025-01-01T00:00:00.000Z',
};

function wrap(ui: React.ReactElement): React.ReactElement {
  return <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>;
}

describe('EmptyState', () => {
  test('shows "No documents yet" for all tab', async () => {
    render(await wrapWithRouter(wrap(<EmptyState tab="all" />)));

    expect(screen.getByText('No documents yet')).toBeInTheDocument();
  });

  test('shows "No uploaded documents yet" for uploaded tab', async () => {
    render(await wrapWithRouter(wrap(<EmptyState tab="uploaded" />)));

    expect(screen.getByText('No uploaded documents yet')).toBeInTheDocument();
  });

  test('shows "No generated documents yet" for generated tab', async () => {
    render(await wrapWithRouter(wrap(<EmptyState tab="generated" />)));

    expect(screen.getByText('No generated documents yet')).toBeInTheDocument();
  });

  test('shows upload CTA on all tab but not on generated tab', async () => {
    const { unmount } = render(await wrapWithRouter(wrap(<EmptyState tab="all" />)));
    expect(screen.getByText('Upload')).toBeInTheDocument();
    unmount();

    render(await wrapWithRouter(wrap(<EmptyState tab="generated" />)));
    expect(screen.queryByText('Upload')).not.toBeInTheDocument();
  });
});

describe('UploadedTabContent', () => {
  test('shows skeleton when loading', () => {
    render(
      wrap(
        <UploadedTabContent
          query={makeAttachmentQuery([], { isLoading: true })}
          page={1}
          onPageChange={vi.fn()}
        />,
      ),
    );

    expect(screen.getByTestId('skeleton')).toBeInTheDocument();
  });

  test('shows empty state when no items', async () => {
    render(
      await wrapWithRouter(
        wrap(
          <UploadedTabContent query={makeAttachmentQuery([])} page={1} onPageChange={vi.fn()} />,
        ),
      ),
    );

    expect(screen.getByText('No uploaded documents yet')).toBeInTheDocument();
  });

  test('renders uploaded cards for items', () => {
    render(
      wrap(
        <UploadedTabContent
          query={makeAttachmentQuery([ATTACHMENT])}
          page={1}
          onPageChange={vi.fn()}
        />,
      ),
    );

    expect(screen.getByTestId('card-uploaded')).toBeInTheDocument();
  });
});

describe('GeneratedTabContent', () => {
  test('shows skeleton when loading', () => {
    render(
      wrap(
        <GeneratedTabContent
          query={makeDocumentQuery([], { isLoading: true })}
          page={1}
          onPageChange={vi.fn()}
        />,
      ),
    );

    expect(screen.getByTestId('skeleton')).toBeInTheDocument();
  });

  test('shows empty state when no items', async () => {
    render(
      await wrapWithRouter(
        wrap(<GeneratedTabContent query={makeDocumentQuery([])} page={1} onPageChange={vi.fn()} />),
      ),
    );

    expect(screen.getByText('No generated documents yet')).toBeInTheDocument();
  });

  test('renders generated cards for items', () => {
    render(
      wrap(
        <GeneratedTabContent
          query={makeDocumentQuery([DOCUMENT])}
          page={1}
          onPageChange={vi.fn()}
        />,
      ),
    );

    expect(screen.getByTestId('card-generated')).toBeInTheDocument();
  });
});

const ALL_TAB_DEFAULTS: {
  isLoading: boolean;
  docPage: number;
  attachPage: number;
  onDocPageChange: (page: number) => void;
  onAttachPageChange: (page: number) => void;
  onRetry: () => void;
} = {
  isLoading: false,
  docPage: 1,
  attachPage: 1,
  onDocPageChange: vi.fn<(page: number) => void>(),
  onAttachPageChange: vi.fn<(page: number) => void>(),
  onRetry: vi.fn<() => void>(),
};

describe('AllTabContent', () => {
  test('shows both uploaded and generated cards', () => {
    render(
      wrap(
        <AllTabContent
          {...ALL_TAB_DEFAULTS}
          documentsQuery={makeDocumentQuery([DOCUMENT])}
          attachmentsQuery={makeAttachmentQuery([ATTACHMENT])}
        />,
      ),
    );

    expect(screen.getByTestId('card-uploaded')).toBeInTheDocument();
    expect(screen.getByTestId('card-generated')).toBeInTheDocument();
  });

  test('shows empty state when both sources are empty', async () => {
    render(
      await wrapWithRouter(
        wrap(
          <AllTabContent
            {...ALL_TAB_DEFAULTS}
            documentsQuery={makeDocumentQuery([])}
            attachmentsQuery={makeAttachmentQuery([])}
          />,
        ),
      ),
    );

    expect(screen.getByText('No documents yet')).toBeInTheDocument();
  });

  test('shows skeleton when loading', () => {
    render(
      wrap(
        <AllTabContent
          {...ALL_TAB_DEFAULTS}
          isLoading={true}
          documentsQuery={makeDocumentQuery([])}
          attachmentsQuery={makeAttachmentQuery([])}
        />,
      ),
    );

    expect(screen.getByTestId('skeleton')).toBeInTheDocument();
  });
});
