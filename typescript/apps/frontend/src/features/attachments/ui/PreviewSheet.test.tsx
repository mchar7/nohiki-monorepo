import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, vi } from 'vitest';
import type { AttachmentResponse } from '@/shared/api';
import { PreviewSheet } from './PreviewSheet.tsx';

const pdfAttachment: AttachmentResponse = {
  id: 'att-1',
  user_id: 'user-1',
  filename: 'resume.pdf',
  content_type: 'application/pdf',
  file_size: 2_097_152,
  download_url: 'https://s3.example.com/resume.pdf?token=abc',
};

const docxAttachment: AttachmentResponse = {
  id: 'att-2',
  user_id: 'user-1',
  filename: 'cover-letter.docx',
  content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  file_size: 524_288,
  download_url: 'https://s3.example.com/cover.docx?token=xyz',
};

const pdfNoUrl: AttachmentResponse = {
  ...pdfAttachment,
  download_url: null,
};

const mockOnOpenChange = vi.fn<(open: boolean) => void>();

const FILE_SIZE_PATTERN = /2 MB/u;

describe('PreviewSheet PDF rendering', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  test('renders filename and file size in the header', () => {
    render(<PreviewSheet open={true} onOpenChange={mockOnOpenChange} attachment={pdfAttachment} />);
    expect(screen.getByText('resume.pdf')).toBeInTheDocument();
    expect(screen.getByText(FILE_SIZE_PATTERN)).toBeInTheDocument();
  });

  test('renders a PDF object for PDF attachments with a download URL', () => {
    render(<PreviewSheet open={true} onOpenChange={mockOnOpenChange} attachment={pdfAttachment} />);
    const pdfObject = document.querySelector('object[type="application/pdf"]');
    expect(pdfObject).toBeInTheDocument();
    expect(pdfObject?.getAttribute('data')).toBe('https://s3.example.com/resume.pdf?token=abc');
  });

  test.each([
    'javascript:alert(1)',
    'data:application/pdf,pwned',
    '//evil.example/file.pdf',
    'not a url',
  ])('shows unavailable state and does not embed unsafe URL %s', (downloadUrl) => {
    render(
      <PreviewSheet
        open={true}
        onOpenChange={mockOnOpenChange}
        attachment={{ ...pdfAttachment, download_url: downloadUrl }}
      />,
    );
    expect(
      screen.getByText('The preview link has expired. Close and reopen to refresh.'),
    ).toBeInTheDocument();
    expect(document.querySelector('object[data]')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download file' })).toBeDisabled();
  });
  test('shows expired error when PDF has no download URL', () => {
    render(<PreviewSheet open={true} onOpenChange={mockOnOpenChange} attachment={pdfNoUrl} />);
    expect(
      screen.getByText('The preview link has expired. Close and reopen to refresh.'),
    ).toBeInTheDocument();
    expect(document.querySelector('iframe')).not.toBeInTheDocument();
  });
});

describe('PreviewSheet non-PDF content', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  test('renders fallback for non-PDF content types', () => {
    render(
      <PreviewSheet open={true} onOpenChange={mockOnOpenChange} attachment={docxAttachment} />,
    );
    expect(screen.getByText('Preview is not available for this file type.')).toBeInTheDocument();
    expect(document.querySelector('iframe')).not.toBeInTheDocument();
  });

  test('renders download button in fallback for non-PDF', () => {
    render(
      <PreviewSheet open={true} onOpenChange={mockOnOpenChange} attachment={docxAttachment} />,
    );
    const downloadButtons = screen.getAllByText('Download');
    expect(downloadButtons.length).toBeGreaterThanOrEqual(1);
  });

  test('does not render content when closed', () => {
    render(
      <PreviewSheet open={false} onOpenChange={mockOnOpenChange} attachment={pdfAttachment} />,
    );
    expect(screen.queryByText('resume.pdf')).not.toBeInTheDocument();
  });
});

describe('PreviewSheet download actions', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  test('renders header download button', () => {
    render(<PreviewSheet open={true} onOpenChange={mockOnOpenChange} attachment={pdfAttachment} />);
    const downloadBtn = screen.getByRole('button', { name: 'Download file' });
    expect(downloadBtn).toBeInTheDocument();
  });

  test('opens download URL when header download button is clicked', async () => {
    const originalOpen = window.open;
    window.open = vi.fn();
    render(<PreviewSheet open={true} onOpenChange={mockOnOpenChange} attachment={pdfAttachment} />);
    const downloadBtn = screen.getByRole('button', { name: 'Download file' });
    await userEvent.click(downloadBtn);
    expect(window.open).toHaveBeenCalledWith(
      'https://s3.example.com/resume.pdf?token=abc',
      '_blank',
      'noopener,noreferrer',
    );
    window.open = originalOpen;
  });

  test('disables header download button when no URL', () => {
    render(<PreviewSheet open={true} onOpenChange={mockOnOpenChange} attachment={pdfNoUrl} />);
    const downloadBtn = screen.getByRole('button', { name: 'Download file' });
    expect(downloadBtn).toBeDisabled();
  });
});
