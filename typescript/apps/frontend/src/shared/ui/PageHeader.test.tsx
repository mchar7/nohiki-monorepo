import type { RenderResult } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { axe } from 'vitest-axe';
import '@/test/axe-setup.ts';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { PageHeader } from './PageHeader.tsx';

const DESCRIPTION_RE = /description/iu;
const GO_BACK_RE = /go\s*back/iu;

const mockGoBack: ReturnType<typeof vi.fn> = vi.fn();
const mockCanGoBack: { value: boolean } = { value: false };

vi.mock('@/shared/lib/hooks/useNavigationHistory.ts', () => ({
  useNavigationHistory: () => ({
    canGoBack: mockCanGoBack.value,
    goBack: mockGoBack,
  }),
}));

async function renderPageHeader(props: Parameters<typeof PageHeader>[0]): Promise<RenderResult> {
  return render(
    await wrapWithRouter(
      <I18nextProvider i18n={i18n}>
        <PageHeader {...props} />
      </I18nextProvider>,
    ),
  );
}

describe('PageHeader', () => {
  test('renders title', async () => {
    await renderPageHeader({ title: 'Test Title' });
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Test Title');
  });

  test('renders description when provided', async () => {
    await renderPageHeader({ title: 'Test', description: 'Test description' });
    expect(screen.getByText('Test description')).toBeInTheDocument();
  });

  test('does not render description when not provided', async () => {
    await renderPageHeader({ title: 'Test' });
    expect(screen.queryByText(DESCRIPTION_RE)).not.toBeInTheDocument();
  });

  test('renders back button when backTo is provided', async () => {
    await renderPageHeader({ title: 'Test', backTo: '/home' });
    await expect(screen.getByRole('link')).toHaveAttribute('href', '/home');
  });

  test('does not render back button when backTo is not provided', async () => {
    await renderPageHeader({ title: 'Test' });
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  test('renders actions when provided', async () => {
    await renderPageHeader({
      title: 'Test',
      actions: <button type="button">Action Button</button>,
    });
    expect(screen.getByRole('button', { name: 'Action Button' })).toBeInTheDocument();
  });

  test('does not render actions container when actions not provided', async () => {
    const { container } = await renderPageHeader({ title: 'Test' });
    const actionsContainer = container.querySelector('.flex.items-center.gap-2');
    expect(actionsContainer).not.toBeInTheDocument();
  });

  test('renders with all props', async () => {
    await renderPageHeader({
      title: 'Full Test',
      description: 'Full description',
      backTo: '/back',
      actions: <button type="button">Save</button>,
    });

    expect(screen.getByRole('heading')).toHaveTextContent('Full Test');
    expect(screen.getByText('Full description')).toBeInTheDocument();
    await expect(screen.getByRole('link')).toHaveAttribute('href', '/back');
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
  });
});

describe('PageHeader with preferHistory', () => {
  test('renders button (not Link) when preferHistory and canGoBack', async () => {
    mockCanGoBack.value = true;
    await renderPageHeader({ title: 'Test', backTo: '/home', preferHistory: true });

    // Should be a button, not a link
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    const backButton = screen.getByRole('button', { name: GO_BACK_RE });
    expect(backButton).toBeInTheDocument();

    mockCanGoBack.value = false;
  });

  test('renders Link to backTo when preferHistory but !canGoBack', async () => {
    mockCanGoBack.value = false;
    await renderPageHeader({ title: 'Test', backTo: '/home', preferHistory: true });

    await expect(screen.getByRole('link')).toHaveAttribute('href', '/home');
  });

  test('renders no back button when preferHistory without backTo', async () => {
    mockCanGoBack.value = true;
    await renderPageHeader({ title: 'Test', preferHistory: true });

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    // Only the heading should exist, no back button
    expect(screen.queryByRole('button', { name: GO_BACK_RE })).not.toBeInTheDocument();

    mockCanGoBack.value = false;
  });
});

describe('PageHeader - accessibility', () => {
  test('has no accessibility violations', async () => {
    const { container } = await renderPageHeader({ title: 'Accessible Page' });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
