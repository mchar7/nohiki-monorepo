import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';

import type * as SharedApi from '@/shared/api/index.ts';
import { nonNull, wrapWithRouter } from '@/shared/test-utils';
import { i18n } from '@/test/i18n-setup.ts';
import { AuthPage } from './auth-page.tsx';

const SIGN_IN_RE = /sign in/iu;
const SIGN_UP_RE = /sign up/iu;
const EMAIL_RE = /email/iu;
const EXACT_PASSWORD_LABEL_RE = /^password$/iu;

vi.mock('@/shared/api/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof SharedApi>();
  return {
    ...actual,
    oauthApi: {
      ...actual.oauthApi,
      getProviders: vi.fn().mockResolvedValue({ providers: [] }),
    },
    useLogin: () => ({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    }),
    useRegister: () => ({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    }),
  };
});

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

describe('AuthPage tab switching', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('defaults to login mode', async () => {
    await renderWithProviders(<AuthPage />);

    const signInTab = screen.getByRole('tab', { name: SIGN_IN_RE });
    await expect(signInTab).toHaveAttribute('data-state', 'active');
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  test('can switch to register mode', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage />);

    const signUpTab = screen.getByRole('tab', { name: SIGN_UP_RE });
    await user.click(signUpTab);

    await expect(signUpTab).toHaveAttribute('data-state', 'active');
  });

  test('can switch back to login mode', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage defaultMode="register" />);

    const signInTab = screen.getByRole('tab', { name: SIGN_IN_RE });
    await user.click(signInTab);

    await expect(signInTab).toHaveAttribute('data-state', 'active');
  });

  test('respects defaultMode prop', async () => {
    await renderWithProviders(<AuthPage defaultMode="register" />);

    const signUpTab = screen.getByRole('tab', { name: SIGN_UP_RE });
    await expect(signUpTab).toHaveAttribute('data-state', 'active');
  });
});

describe('AuthPage keyboard navigation', () => {
  test('switches tabs with arrow keys and exposes the selected tab state', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage />);

    const signInTab = screen.getByRole('tab', { name: SIGN_IN_RE });
    const signUpTab = screen.getByRole('tab', { name: SIGN_UP_RE });
    signInTab.focus();

    await user.keyboard('{ArrowRight}');
    expect(signUpTab).toHaveFocus();
    expect(signUpTab).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{ArrowLeft}');
    expect(signInTab).toHaveFocus();
    expect(signInTab).toHaveAttribute('aria-selected', 'true');
  });
});

describe('AuthPage data persistence between tabs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('preserves email when switching from login to register', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage />);

    const emailInput = screen.getByLabelText(EMAIL_RE);
    await user.type(emailInput, 'test@example.com');

    const signUpTab = screen.getByRole('tab', { name: SIGN_UP_RE });
    await user.click(signUpTab);

    const [registerEmailInput] = screen.getAllByLabelText(EMAIL_RE);
    await expect(registerEmailInput).toHaveValue('test@example.com');
  });

  test('preserves password when switching from login to register', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage />);

    const passwordInput = screen.getByLabelText(EXACT_PASSWORD_LABEL_RE);
    await user.type(passwordInput, 'TestPassword123');

    const signUpTab = screen.getByRole('tab', { name: SIGN_UP_RE });
    await user.click(signUpTab);

    const [registerPasswordInput] = screen.getAllByLabelText(EXACT_PASSWORD_LABEL_RE);
    await expect(registerPasswordInput).toHaveValue('TestPassword123');
  });

  test('preserves email when switching from register to login', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage defaultMode="register" />);

    const emailInput = nonNull(screen.getAllByLabelText(EMAIL_RE)[0]);
    await user.type(emailInput, 'register@example.com');

    const signInTab = screen.getByRole('tab', { name: SIGN_IN_RE });
    await user.click(signInTab);

    const loginEmailInput = screen.getByLabelText(EMAIL_RE);
    await expect(loginEmailInput).toHaveValue('register@example.com');
  });
});
