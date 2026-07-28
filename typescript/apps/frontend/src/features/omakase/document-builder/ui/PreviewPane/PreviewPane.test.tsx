import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import type { JSX } from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import { PreviewPane } from './PreviewPane.tsx';

const GENERATE_RE = /generate/iu;

// Mock the usePreviewPane hook
const mockGeneratePreview: ReturnType<typeof vi.fn> = vi.fn();
const mockDownloadPdf: ReturnType<typeof vi.fn> = vi.fn();
const mockClearError: ReturnType<typeof vi.fn> = vi.fn();
const mockHandleJsChoice: ReturnType<typeof vi.fn> = vi.fn();

vi.mock('../../lib/usePreviewPane.ts', () => ({
  usePreviewPane: () => ({
    isGenerating: false,
    hasPreview: false,
    htmlUrl: null,
    imageUrl: null,
    renderMethod: 'html' as const,
    error: null,
    clearError: mockClearError,
    generatePreview: mockGeneratePreview,
    downloadPdf: mockDownloadPdf,
    jsWarning: {
      showWarning: false,
      templateName: null,
      templateVersion: null,
      reason: null,
      handleJsChoice: mockHandleJsChoice,
    },
  }),
}));

// Mock useResizeObserver
vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useResizeObserver: () => [{ current: null }, { width: 800, height: 600 }],
  };
});

// jsdom doesn't provide ResizeObserver
globalThis.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

const queryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false },
    mutations: { retry: false },
  },
});

const TestWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => (
  <QueryClientProvider client={queryClient}>
    <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
  </QueryClientProvider>
);

describe('PreviewPane', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders with initial state', () => {
    render(
      <TestWrapper>
        <PreviewPane />
      </TestWrapper>,
    );

    // Component should render header elements
    expect(screen.getByText('Preview')).toBeInTheDocument();
    // Multiple generate buttons exist (header + empty state), check at least one
    expect(screen.getAllByRole('button', { name: GENERATE_RE }).length).toBeGreaterThan(0);
  });

  test('renders with showHeader=false', () => {
    render(
      <TestWrapper>
        <PreviewPane showHeader={false} />
      </TestWrapper>,
    );

    // Header should not be present
    expect(screen.queryByText('Preview')).not.toBeInTheDocument();
  });

  test('renders custom className', () => {
    const { container } = render(
      <TestWrapper>
        <PreviewPane className="custom-class" />
      </TestWrapper>,
    );

    expect(container.firstChild).toHaveClass('custom-class');
  });

  test('passes template and data props', () => {
    render(
      <TestWrapper>
        <PreviewPane template="<h1>Test</h1>" data={{ title: 'Hello' }} />
      </TestWrapper>,
    );

    // Component should render without errors
    expect(screen.getByText('Preview')).toBeInTheDocument();
  });
});
