import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';

import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import authEn from '../../../../public/locales/en/auth.json';
import authFr from '../../../../public/locales/fr-CA/auth.json';
import { AuthPage, createAuthSchema } from './auth-page.tsx';

const SIGN_IN_RE = /sign in/iu;
const SIGN_UP_RE = /sign up/iu;
const TERMS_OF_SERVICE_RE = /terms of service/iu;
const PRIVACY_POLICY_RE = /privacy policy/iu;
const EMAIL_RE = /email/iu;
const EXACT_PASSWORD_LABEL_RE = /^password$/iu;
const FULL_NAME_OR_NAME_RE = /full name|name/iu;
const CONFIRM_PASSWORD_RE = /confirm password/iu;

const mockRegister = vi.hoisted(() => vi.fn().mockResolvedValue({}));

vi.mock('../api', () => ({
  useLogin: () => ({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  }),
  useRegister: () => ({
    mutateAsync: mockRegister,
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

describe('AuthPage login form', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders email and password fields', async () => {
    await renderWithProviders(<AuthPage />);

    expect(screen.getByLabelText(EMAIL_RE)).toBeInTheDocument();
    expect(screen.getByLabelText(EXACT_PASSWORD_LABEL_RE)).toBeInTheDocument();
  });

  test('renders submit button', async () => {
    await renderWithProviders(<AuthPage />);

    expect(screen.getByRole('button', { name: SIGN_IN_RE })).toBeInTheDocument();
  });

  test('allows typing in email field', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage />);

    const emailInput = screen.getByLabelText(EMAIL_RE);
    await user.type(emailInput, 'test@example.com');

    await expect(emailInput).toHaveValue('test@example.com');
  });

  test('allows typing in password field', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage />);

    const passwordInput = screen.getByLabelText(EXACT_PASSWORD_LABEL_RE);
    await user.type(passwordInput, 'password123');

    await expect(passwordInput).toHaveValue('password123');
  });
});

describe('AuthPage register form', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders all register fields', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage />);

    const signUpTab = screen.getByRole('tab', { name: SIGN_UP_RE });
    await user.click(signUpTab);

    expect(screen.getByLabelText(FULL_NAME_OR_NAME_RE)).toBeInTheDocument();
    expect(screen.getAllByLabelText(EMAIL_RE)[0]).toBeInTheDocument();
    expect(screen.getAllByLabelText(EXACT_PASSWORD_LABEL_RE)[0]).toBeInTheDocument();
    expect(screen.getByLabelText(CONFIRM_PASSWORD_RE)).toBeInTheDocument();
  });

  test('allows typing in confirm password field', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage defaultMode="register" />);

    const confirmPasswordInput = screen.getByLabelText(CONFIRM_PASSWORD_RE);
    await user.type(confirmPasswordInput, 'Password123!');

    await expect(confirmPasswordInput).toHaveValue('Password123!');
  });

  test.each(['', '   ', '\u00a0\u2003'])('blocks blank display name %j', (displayName) => {
    const schema = createAuthSchema(i18n.getFixedT('en', ['auth', 'common']), 'register');
    const result = schema.safeParse({
      displayName,
      email: 'international@example.com',
      password: 'Password123!',
      confirmPassword: 'Password123!',
    });

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toBe('Display name is required');
  });

  test.each([
    'Line\nBreak',
    'Tabbed\tName',
    'Null\0Name',
  ])('blocks display name containing controls %j', (displayName) => {
    const schema = createAuthSchema(i18n.getFixedT('en', ['auth', 'common']), 'register');
    const result = schema.safeParse({
      displayName,
      email: 'international@example.com',
      password: 'Password123!',
      confirmPassword: 'Password123!',
    });

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toMatch(/control characters/iu);
  });

  test('keeps display-name validation localized in every supported locale', () => {
    expect(authEn.validation.displayName.required).toBe('Display name is required');
    expect(authFr.validation.displayName.required).toBe("Le nom d'affichage est requis");
    expect(authEn.validation.displayName.controlCharacters).toMatch(/control characters/iu);
    expect(authFr.validation.displayName.controlCharacters).toMatch(/caractères de contrôle/iu);
  });

  test('normalizes an international display name without token splitting', () => {
    const schema = createAuthSchema(i18n.getFixedT('en', ['auth', 'common']), 'register');
    const result = schema.parse({
      displayName: '  李\u3000小龍  O’Connor-Søndergaard  ',
      email: 'international@example.com',
      password: 'Password123!',
      confirmPassword: 'Password123!',
    });

    expect(result).toEqual({
      displayName: '李 小龍 O’Connor-Søndergaard',
      email: 'international@example.com',
      password: 'Password123!',
      confirmPassword: 'Password123!',
    });
  });
});

describe('AuthPage accessibility', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('has accessible form labels', async () => {
    await renderWithProviders(<AuthPage />);

    const emailInput = screen.getByLabelText(EMAIL_RE);
    const passwordInput = screen.getByLabelText(EXACT_PASSWORD_LABEL_RE);

    await expect(emailInput).toHaveAccessibleName();
    await expect(passwordInput).toHaveAccessibleName();
  });

  test('uses proper tab navigation structure', async () => {
    await renderWithProviders(<AuthPage />);

    const tablist = screen.getByRole('tablist');
    expect(tablist).toBeInTheDocument();

    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(2);
  });

  test('owns the active auth form from a labelled tabpanel', async () => {
    await renderWithProviders(<AuthPage />);

    const activeTab = screen.getByRole('tab', { name: SIGN_IN_RE });
    const panel = screen.getByRole('tabpanel', { name: SIGN_IN_RE });

    expect(activeTab).toHaveAttribute('aria-selected', 'true');
    expect(activeTab).toHaveAttribute('aria-controls', panel.id);
    expect(panel).toHaveAttribute('aria-labelledby', activeTab.id);
    expect(panel).toContainElement(screen.getByLabelText(EMAIL_RE));
  });

  test('links open in new tab with proper rel attributes', async () => {
    await renderWithProviders(<AuthPage />);

    const termsLink = screen.getByRole('link', { name: TERMS_OF_SERVICE_RE });
    const privacyLink = screen.getByRole('link', { name: PRIVACY_POLICY_RE });

    await expect(termsLink).toHaveAttribute('rel', 'noopener noreferrer');
    await expect(privacyLink).toHaveAttribute('rel', 'noopener noreferrer');
  });

  test('keeps email authentication as the primary submit action', async () => {
    await renderWithProviders(<AuthPage />);

    const submit = screen.getByRole('button', { name: SIGN_IN_RE });
    expect(submit).toHaveAttribute('type', 'submit');
    expect(submit).not.toHaveAttribute('data-variant', 'outline');
    expect(
      screen.getAllByRole('button').filter((button) => button.getAttribute('type') === 'submit'),
    ).toEqual([submit]);
  });

  test('keeps legal links in the keyboard focus order after the form', async () => {
    const user = userEvent.setup();
    await renderWithProviders(<AuthPage />);

    const termsLink = screen.getByRole('link', { name: TERMS_OF_SERVICE_RE });
    const privacyLink = screen.getByRole('link', { name: PRIVACY_POLICY_RE });
    termsLink.focus();
    await user.tab();

    expect(privacyLink).toHaveFocus();
    expect(termsLink).toHaveAccessibleName();
    expect(privacyLink).toHaveAccessibleName();
  });
});
