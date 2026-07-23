const GENERATE_LINK_NAME = /generate your first document/iu;

import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { EmptyState } from './DocumentTableParts.tsx';

vi.mock('@/features/attachments/index.ts', () => ({
  UploadDialog: () => (
    <button type="button" data-testid="upload-dialog-trigger">
      Or upload an existing document
    </button>
  ),
}));

describe('EmptyState', () => {
  test('renders primary CTA linking to /documents/generate', async () => {
    render(
      await wrapWithRouter(
        <I18nextProvider i18n={i18n}>
          <EmptyState />
        </I18nextProvider>,
      ),
    );

    const primaryLink = screen.getByRole('link', { name: GENERATE_LINK_NAME });
    expect(primaryLink).toBeInTheDocument();
    expect(primaryLink).toHaveAttribute('href', '/documents/generate');
  });

  test('renders secondary upload CTA', async () => {
    render(
      await wrapWithRouter(
        <I18nextProvider i18n={i18n}>
          <EmptyState />
        </I18nextProvider>,
      ),
    );

    expect(screen.getByTestId('upload-dialog-trigger')).toBeInTheDocument();
  });

  test('contains no references to Omakase', async () => {
    const { container } = render(
      await wrapWithRouter(
        <I18nextProvider i18n={i18n}>
          <EmptyState />
        </I18nextProvider>,
      ),
    );

    expect(container.textContent?.toLowerCase()).not.toContain('omakase');
  });
});
