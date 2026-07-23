import type { RenderResult } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import { PreviewRenderer } from './PreviewRenderer.tsx';

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useResizeObserver: vi.fn(() => [vi.fn(), { width: 800, height: 600 }]),
  };
});

// jsdom doesn't provide ResizeObserver
globalThis.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

function renderWithProviders(ui: React.ReactElement): RenderResult {
  return render(<I18nextProvider i18n={i18n}>{ui}</I18nextProvider>);
}

describe('PreviewRenderer - content rendering', () => {
  test('renders HTML iframe when htmlUrl is provided', () => {
    const htmlUrl = 'blob:http://localhost/test-html';

    renderWithProviders(<PreviewRenderer htmlUrl={htmlUrl} imageUrl={null} />);

    const iframe = screen.getByTitle('Document Preview');
    expect(iframe).toBeInTheDocument();
    expect(iframe).toHaveAttribute('src', htmlUrl);
    expect(iframe).toHaveAttribute('sandbox', 'allow-same-origin');
    expect(iframe.getAttribute('sandbox')?.split(/\s+/u)).not.toContain('allow-scripts');
  });

  test('renders image when imageUrl is provided', () => {
    const imageUrl = 'blob:http://localhost/test-image';

    renderWithProviders(<PreviewRenderer htmlUrl={null} imageUrl={imageUrl} />);

    const image = screen.getByRole('img');
    expect(image).toBeInTheDocument();
    expect(image).toHaveAttribute('src', imageUrl);
    expect(image).toHaveAttribute('alt', 'Document preview');
    expect(image).toHaveClass('object-contain', 'max-h-full', 'max-w-full');
  });

  test('prioritizes HTML over image when both are provided', () => {
    const htmlUrl = 'blob:http://localhost/test-html';
    const imageUrl = 'blob:http://localhost/test-image';

    renderWithProviders(<PreviewRenderer htmlUrl={htmlUrl} imageUrl={imageUrl} />);

    expect(screen.getByTitle('Document Preview')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  test('returns null when neither URL is provided', () => {
    const { container } = renderWithProviders(<PreviewRenderer htmlUrl={null} imageUrl={null} />);

    expect(container.firstChild).toBeNull();
  });
});

describe('PreviewRenderer - layout modes', () => {
  test('applies fullscreen classes correctly', () => {
    const htmlUrl = 'blob:http://localhost/test-html';

    renderWithProviders(
      <PreviewRenderer htmlUrl={htmlUrl} imageUrl={null} isFullscreen={true} isInDialog={false} />,
    );

    const container = screen.getByTitle('Document Preview').parentElement;
    expect(container).toHaveClass('fixed', 'inset-0', 'z-50', 'bg-white');
  });

  test('applies dialog classes correctly', () => {
    const htmlUrl = 'blob:http://localhost/test-html';

    renderWithProviders(<PreviewRenderer htmlUrl={htmlUrl} imageUrl={null} isInDialog={true} />);

    const container = screen.getByTitle('Document Preview').parentElement;
    expect(container).toHaveClass('bg-white');
    expect(container).not.toHaveClass('fixed', 'inset-0', 'z-50');
  });
});
