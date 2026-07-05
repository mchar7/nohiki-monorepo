import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, vi } from 'vitest';

const mockUseDocumentSSE = vi.fn<(...args: unknown[]) => Record<string, unknown>>();

vi.mock('@/features/document-generation/api/useDocumentSSE.ts', () => ({
  useDocumentSSE: (...args: unknown[]) => mockUseDocumentSSE(...args),
}));

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>();
  return {
    ...actual,
    Link: ({
      children,
      to,
      ...props
    }: {
      children: React.ReactNode;
      to: string;
      [key: string]: unknown;
    }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  };
});

import { GenerationProgress } from './GenerationProgress.tsx';

function sseResult(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    status: 'connecting',
    downloadUrl: null,
    error: null,
    progress: 0,
    disconnect: vi.fn(),
    isConnected: false,
    ...overrides,
  };
}

describe('GenerationProgress progress states', () => {
  const onRetry = vi.fn<() => void>();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('passes requestId to useDocumentSSE', () => {
    mockUseDocumentSSE.mockReturnValue(sseResult());
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    expect(mockUseDocumentSSE).toHaveBeenCalledWith('req-123');
  });

  test('renders progress indicator while connecting', () => {
    mockUseDocumentSSE.mockReturnValue(sseResult({ status: 'connecting' }));
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    expect(screen.getByText('Generating your document')).toBeInTheDocument();
    expect(screen.getByText('0% complete')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Document generation progress' })).toBeVisible();
  });

  test('renders progress indicator while idle', () => {
    mockUseDocumentSSE.mockReturnValue(sseResult({ status: 'idle' }));
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    expect(screen.getByText('Generating your document')).toBeInTheDocument();
  });

  test('shows progress percentage when connected', () => {
    mockUseDocumentSSE.mockReturnValue(
      sseResult({ status: 'connected', progress: 42, isConnected: true }),
    );
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    expect(screen.getByText('42% complete')).toBeInTheDocument();
  });
});

describe('GenerationProgress completion', () => {
  const onRetry = vi.fn<() => void>();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders success state on completion with download URL', () => {
    mockUseDocumentSSE.mockReturnValue(
      sseResult({ status: 'completed', downloadUrl: '/api/v1/documents/download/abc.pdf' }),
    );
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    expect(screen.getByText('Document ready')).toBeInTheDocument();
    expect(screen.getByText('Download PDF')).toBeInTheDocument();
    expect(screen.getByText('View in Documents')).toBeInTheDocument();
    const downloadLink = screen.getByText('Download PDF').closest('a');
    expect(downloadLink).toHaveAttribute('href', '/api/v1/documents/download/abc.pdf');
    expect(downloadLink).toHaveAttribute('download');
  });

  test('renders success state without download button when no URL', () => {
    mockUseDocumentSSE.mockReturnValue(sseResult({ status: 'completed', downloadUrl: null }));
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    expect(screen.getByText('Document ready')).toBeInTheDocument();
    expect(screen.queryByText('Download PDF')).not.toBeInTheDocument();
    expect(screen.getByText('View in Documents')).toBeInTheDocument();
  });

  test('renders "View in Documents" link pointing to /documents', () => {
    mockUseDocumentSSE.mockReturnValue(sseResult({ status: 'completed' }));
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    const viewLink = screen.getByText('View in Documents').closest('a');
    expect(viewLink).toHaveAttribute('href', '/documents');
  });
});

describe('GenerationProgress error handling', () => {
  const onRetry = vi.fn<() => void>();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders error state with error message', () => {
    mockUseDocumentSSE.mockReturnValue(
      sseResult({ status: 'failed', error: 'Template rendering crashed' }),
    );
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    expect(screen.getByText('Generation failed')).toBeInTheDocument();
    expect(screen.getByText('Template rendering crashed')).toBeInTheDocument();
    expect(screen.getByText('Try Again')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry document generation' })).toBeVisible();
  });

  test('renders fallback error message when error is null', () => {
    mockUseDocumentSSE.mockReturnValue(sseResult({ status: 'failed', error: null }));
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    expect(screen.getByText('An unexpected error occurred. Please try again.')).toBeInTheDocument();
  });

  test('calls onRetry when "Try Again" is clicked', async () => {
    const user = userEvent.setup();
    mockUseDocumentSSE.mockReturnValue(sseResult({ status: 'failed', error: 'Some error' }));
    render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    await user.click(screen.getByText('Try Again'));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  test('has live region for screen reader announcements during progress', () => {
    mockUseDocumentSSE.mockReturnValue(sseResult({ status: 'connected', isConnected: true }));
    const { container } = render(<GenerationProgress requestId="req-123" onRetry={onRetry} />);
    const liveRegion = container.querySelector('[aria-live="polite"]');
    expect(liveRegion).toBeInTheDocument();
  });
});
