import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { Licenses } from './Licenses.tsx';

const LICENSE_TEXT = 'Example package\n\nMIT License\n\nCopyright Example';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Licenses download', () => {
  test('offers the license text as a download link with the expected filename', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(LICENSE_TEXT),
      }),
    );

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      await wrapWithRouter(
        <QueryClientProvider client={queryClient}>
          <I18nextProvider i18n={i18n}>
            <Licenses />
          </I18nextProvider>
        </QueryClientProvider>,
      ),
    );

    const downloadLink = await screen.findByRole('link', {
      name: 'Download Full License File',
    });
    expect(downloadLink).toHaveAttribute('href', '/third-party-licenses.txt');
    expect(downloadLink).toHaveAttribute('download', 'third-party-licenses.txt');
  });
});
