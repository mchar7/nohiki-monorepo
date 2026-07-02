import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, vi } from 'vitest';
import type { AttachmentResponse } from '@/shared/api';
import { AttachmentCard } from './AttachmentCard.tsx';

let mockIsMobile = false;

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useIsMobileLayout: () => mockIsMobile,
    formatRelativeTime: () => '2h ago',
  };
});

vi.mock('./LinkToProfileDialog.tsx', () => ({
  LinkToProfileDialog: () => null,
}));

const mockAttachment: AttachmentResponse = {
  id: '123',
  user_id: 'user-1',
  filename: 'resume.pdf',
  content_type: 'application/pdf',
  file_size: 1_048_576, // 1MB
  download_url: 'https://example.com/resume.pdf',
};

const UPLOADED_PATTERN = /Uploaded/u;

const mockOnDelete = vi.fn<(id: string) => void>();

describe('AttachmentCard rendering', () => {
  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
  });

  test('renders file name and size', () => {
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    expect(screen.getByText('resume.pdf')).toBeInTheDocument();
    expect(screen.getByText('1 MB')).toBeInTheDocument();
  });

  test('renders dropdown menu actions on desktop', async () => {
    mockIsMobile = false;
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    expect(screen.getByText('Download')).toBeInTheDocument();
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  test('renders bottom sheet actions on mobile', async () => {
    mockIsMobile = true;
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    expect(screen.getByText('Actions')).toBeInTheDocument();
    expect(screen.getByText('Download')).toBeInTheDocument();
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });
});

describe('AttachmentCard actions', () => {
  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
  });

  test('triggers download callback when download is clicked', async () => {
    const originalOpen = window.open;
    window.open = vi.fn();
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    const downloadBtn = screen.getByText('Download');
    await userEvent.click(downloadBtn);
    expect(window.open).toHaveBeenCalledWith(
      'https://example.com/resume.pdf',
      '_blank',
      'noopener,noreferrer',
    );
    window.open = originalOpen;
  });

  test.each([
    'javascript:alert(1)',
    'data:text/html,pwned',
    '//evil.example/file.pdf',
    'not a url',
  ])('disables download for unsafe URL %s', async (downloadUrl) => {
    render(
      <AttachmentCard
        attachment={{ ...mockAttachment, download_url: downloadUrl }}
        onDelete={mockOnDelete}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'More options' }));
    expect(screen.getByText('Download').closest('[role="menuitem"]')).toHaveAttribute(
      'data-disabled',
    );
    expect(screen.getByText('Preview').closest('[role="menuitem"]')).toHaveAttribute(
      'data-disabled',
    );
  });

  test('triggers onDelete with attachment id when delete is clicked', async () => {
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    const deleteBtn = screen.getByText('Delete');
    await userEvent.click(deleteBtn);
    expect(mockOnDelete).toHaveBeenCalledWith('123');
  });

  test('delete action has destructive styling', async () => {
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    // In Radix UI dropdowns, items have role="menuitem"
    const deleteBtn = screen.getByText('Delete').closest('[role="menuitem"]');
    expect(deleteBtn?.className).toContain('text-destructive');
  });
});

describe('AttachmentCard upload date', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  test('renders upload date when created_at is provided', () => {
    const attachmentWithDate: AttachmentResponse = {
      ...mockAttachment,
      created_at: '2025-03-29T10:00:00Z',
    };
    render(<AttachmentCard attachment={attachmentWithDate} onDelete={mockOnDelete} />);
    expect(screen.getByText('Uploaded 2h ago')).toBeInTheDocument();
  });

  test('does not render upload date when created_at is absent', () => {
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    expect(screen.queryByText(UPLOADED_PATTERN)).not.toBeInTheDocument();
  });
});

describe('AttachmentCard Preview action', () => {
  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
  });

  test('shows Preview action for PDF attachments', async () => {
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    expect(screen.getByText('Preview')).toBeInTheDocument();
  });

  test('does not show Preview action for non-PDF attachments', async () => {
    const docxAttachment: AttachmentResponse = {
      ...mockAttachment,
      filename: 'letter.docx',
      content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    };
    render(<AttachmentCard attachment={docxAttachment} onDelete={mockOnDelete} />);
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    expect(screen.queryByText('Preview')).not.toBeInTheDocument();
  });

  test('does not show Preview action for image attachments', async () => {
    const imageAttachment: AttachmentResponse = {
      ...mockAttachment,
      filename: 'photo.png',
      content_type: 'image/png',
    };
    render(<AttachmentCard attachment={imageAttachment} onDelete={mockOnDelete} />);
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    expect(screen.queryByText('Preview')).not.toBeInTheDocument();
  });
});

describe('AttachmentCard profile linking display', () => {
  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
  });

  test('shows linked profile badge when linkedProfile is provided', () => {
    render(
      <AttachmentCard
        attachment={mockAttachment}
        onDelete={mockOnDelete}
        linkedProfile={{ id: 'pref-1', name: 'Frontend Dev' }}
      />,
    );
    expect(screen.getByText('Linked to Frontend Dev')).toBeInTheDocument();
  });

  test('does not show linked profile badge when linkedProfile is not provided', () => {
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    expect(screen.queryByText('Linked to')).not.toBeInTheDocument();
  });
});

describe('AttachmentCard profile linking actions', () => {
  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
  });

  test('shows Link to Profile action when not linked', async () => {
    render(<AttachmentCard attachment={mockAttachment} onDelete={mockOnDelete} />);
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    expect(screen.getByText('Link to Profile')).toBeInTheDocument();
    expect(screen.queryByText('Unlink from Profile')).not.toBeInTheDocument();
  });

  test('shows Unlink from Profile action when linked', async () => {
    render(
      <AttachmentCard
        attachment={mockAttachment}
        onDelete={mockOnDelete}
        linkedProfile={{ id: 'pref-1', name: 'Frontend Dev' }}
      />,
    );
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    expect(screen.getByText('Unlink from Profile')).toBeInTheDocument();
    expect(screen.queryByText('Link to Profile')).not.toBeInTheDocument();
  });

  test('calls onUnlink when Unlink from Profile is clicked', async () => {
    const mockOnUnlink = vi.fn<(profileId: string, attachmentId: string) => void>();
    render(
      <AttachmentCard
        attachment={mockAttachment}
        onDelete={mockOnDelete}
        linkedProfile={{ id: 'pref-1', name: 'Frontend Dev' }}
        onUnlink={mockOnUnlink}
      />,
    );
    const trigger = screen.getByRole('button', { name: 'More options' });
    await userEvent.click(trigger);
    await userEvent.click(screen.getByText('Unlink from Profile'));
    expect(mockOnUnlink).toHaveBeenCalledWith('pref-1', '123');
  });
});
