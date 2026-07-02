import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';

import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/setup.ts';
import { AuthPage } from './auth-page.tsx';

const SIGN_IN_RE = /sign in/iu;
const SIGN_UP_RE = /sign up/iu;
const TERMS_OF_SERVICE_RE = /terms of service/iu;
const PRIVACY_POLICY_RE = /privacy policy/iu;

vi.mock('../api', () => ({
  useLogin: () => ({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  }),
  useRegister: () => ({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  }),
}));

vi.mock('./oauth-button', () => ({
  OAuthButton: ({ provider }: { provider: string }) => (
    <button type="button" data-testid={`oauth-${provider}`}>
      {`${provider} OAuth`}
    </button>
  ),
}));

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

async function renderWithProviders(
  ui: React.ReactElement,
  { route = '/auth/login' }: { route?: string } = {},
): Promise<ReturnType<typeof render>> {
  const queryClient = createTestQueryClient();
  return render(
    await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>
      </QueryClientProvider>,
      route,
    ),
  );
}

describe('AuthPage rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders login and register tabs', async () => {
    await renderWithProviders(<AuthPage />);

    expect(screen.getByRole('tab', { name: SIGN_IN_RE })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: SIGN_UP_RE })).toBeInTheDocument();
  });

  test('renders Nohiki branding', async () => {
    await renderWithProviders(<AuthPage />);

    expect(screen.getByText('Nohiki')).toBeInTheDocument();
  });

  test('renders OAuth buttons', async () => {
    await renderWithProviders(<AuthPage />);

    expect(await screen.findByTestId('oauth-google')).toBeInTheDocument();
    expect(await screen.findByTestId('oauth-github')).toBeInTheDocument();
  });

  test('renders terms of service and privacy policy links', async () => {
    await renderWithProviders(<AuthPage />);

    const termsLink = screen.getByRole('link', { name: TERMS_OF_SERVICE_RE });
    const privacyLink = screen.getByRole('link', { name: PRIVACY_POLICY_RE });

    await expect(termsLink).toHaveAttribute('href', 'https://www.nohiki.com/terms');
    await expect(privacyLink).toHaveAttribute('href', 'https://www.nohiki.com/privacy');
    await expect(termsLink).toHaveAttribute('target', '_blank');
    await expect(privacyLink).toHaveAttribute('target', '_blank');
  });
});
