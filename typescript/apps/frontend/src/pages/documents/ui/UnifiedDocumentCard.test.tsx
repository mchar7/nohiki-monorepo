import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import { UnifiedDocumentCard } from './UnifiedDocumentCard.tsx';
import type { UnifiedDocument } from './UnifiedDocumentCard.types.ts';

// Mock dependencies that need providers or external state

vi.mock('@/features/attachments/index.ts', () => ({
  getFileCategory: () => 'pdf',
  useDeleteAttachment: () => ({ mutate: vi.fn() }),
  UploadDialog: () => <button type="button">Upload</button>,
}));

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    useCopyToClipboard: () => [vi.fn(), false],
  };
});

const UPLOADED_DOC: UnifiedDocument = {
  type: 'uploaded',
  data: {
    id: 'upload-123',
    user_id: 'user-1',
    filename: 'resume.pdf',
    content_type: 'application/pdf',
    file_size: 102_400,
    download_url: 'https://example.com/resume.pdf',
  },
};

const GENERATED_COMPLETED: UnifiedDocument = {
  type: 'generated',
  data: {
    request_id: 'abcdef1234567890',
    status: 'completed',
    download_url: 'https://example.com/doc.pdf',
    error: null,
    template_name: 'Modern Resume',
    output_format: 'pdf',
    created_at: '2025-01-15T10:30:00Z',
  },
};

const GENERATED_PROCESSING: UnifiedDocument = {
  type: 'generated',
  data: {
    request_id: 'proc1234567890ab',
    status: 'processing',
    download_url: null,
    error: null,
    template_name: 'Cover Letter Classic',
    output_format: 'html',
    created_at: '2025-01-15T10:30:00Z',
  },
};

const GENERATED_FAILED: UnifiedDocument = {
  type: 'generated',
  data: {
    request_id: 'fail1234567890ab',
    status: 'failed',
    download_url: null,
    error: 'Template rendering failed',
    output_format: 'pdf',
  },
};

const DOWNLOAD_PATTERN = /download/iu;
const CREATED_PATTERN = /Created/u;

function renderCard(doc: UnifiedDocument): ReturnType<typeof render> {
  return render(
    <I18nextProvider i18n={i18n}>
      <UnifiedDocumentCard document={doc} />
    </I18nextProvider>,
  );
}

describe('UnifiedDocumentCard - uploaded', () => {
  test('renders filename and type badge', () => {
    renderCard(UPLOADED_DOC);
    expect(screen.getByText('resume.pdf')).toBeInTheDocument();
    expect(screen.getByText('Uploaded')).toBeInTheDocument();
  });

  test('renders file size', () => {
    renderCard(UPLOADED_DOC);
    expect(screen.getByText('100 KB')).toBeInTheDocument();
  });

  test('does not render generated-only elements', () => {
    renderCard(UPLOADED_DOC);
    expect(screen.queryByText('Generated')).not.toBeInTheDocument();
  });
});

describe('UnifiedDocumentCard - completed', () => {
  test('renders template name instead of truncated ID', () => {
    renderCard(GENERATED_COMPLETED);
    expect(screen.getByText('Modern Resume')).toBeInTheDocument();
    expect(screen.getByText('Generated')).toBeInTheDocument();
  });

  test('falls back to truncated request ID when template_name is absent', () => {
    const doc: UnifiedDocument = {
      type: 'generated',
      data: {
        request_id: 'abcdef1234567890',
        status: 'completed',
        download_url: 'https://example.com/doc.pdf',
        error: null,
        output_format: 'pdf',
      },
    };
    renderCard(doc);
    expect(screen.getByText('abcdef12\u2026')).toBeInTheDocument();
  });

  test('renders output format badge', () => {
    renderCard(GENERATED_COMPLETED);
    expect(screen.getByText('PDF')).toBeInTheDocument();
  });

  test('renders completed status badge', () => {
    renderCard(GENERATED_COMPLETED);
    expect(screen.getByText('Completed')).toBeInTheDocument();
  });

  test('renders creation date', () => {
    renderCard(GENERATED_COMPLETED);
    expect(screen.getByText(CREATED_PATTERN)).toBeInTheDocument();
  });

  test('renders download link when completed with URL', () => {
    renderCard(GENERATED_COMPLETED);
    const downloadLink = screen.getByRole('link', { name: DOWNLOAD_PATTERN });
    expect(downloadLink).toHaveAttribute('href', 'https://example.com/doc.pdf');
  });

  test.each([
    'javascript:alert(1)',
    'data:text/html,pwned',
    '//evil.example/doc.pdf',
    'not a url',
  ])('does not expose unsafe completed URL %s as a link', (downloadUrl) => {
    renderCard({
      type: 'generated',
      data: { ...GENERATED_COMPLETED.data, download_url: downloadUrl },
    });
    expect(screen.queryByRole('link', { name: DOWNLOAD_PATTERN })).not.toBeInTheDocument();
  });
  test.each([
    'javascript:alert(1)',
    'data:text/html,pwned',
    '//evil.example/doc.pdf',
    'not a url',
  ])('does not expose uploaded unsafe URL %s as a download control', (downloadUrl) => {
    renderCard({
      type: 'uploaded',
      data: { ...UPLOADED_DOC.data, download_url: downloadUrl },
    });
    expect(screen.queryByRole('button', { name: DOWNLOAD_PATTERN })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: DOWNLOAD_PATTERN })).not.toBeInTheDocument();
  });
});

describe('UnifiedDocumentCard - processing', () => {
  test('renders processing status badge', () => {
    renderCard(GENERATED_PROCESSING);
    expect(screen.getByText('Processing')).toBeInTheDocument();
  });

  test('renders template name for processing doc', () => {
    renderCard(GENERATED_PROCESSING);
    expect(screen.getByText('Cover Letter Classic')).toBeInTheDocument();
  });

  test('renders output format badge for processing doc', () => {
    renderCard(GENERATED_PROCESSING);
    expect(screen.getByText('HTML')).toBeInTheDocument();
  });

  test('renders generating indicator', () => {
    renderCard(GENERATED_PROCESSING);
    expect(screen.getByText('Generating document...')).toBeInTheDocument();
  });
});

describe('UnifiedDocumentCard - failed', () => {
  test('renders failed status badge', () => {
    renderCard(GENERATED_FAILED);
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });

  test('renders error message', () => {
    renderCard(GENERATED_FAILED);
    expect(screen.getByText('Template rendering failed')).toBeInTheDocument();
  });

  test('does not render creation date when created_at is absent', () => {
    renderCard(GENERATED_FAILED);
    expect(screen.queryByText(CREATED_PATTERN)).not.toBeInTheDocument();
  });
});
