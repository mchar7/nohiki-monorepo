import { type RenderResult, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { i18n } from '@/test/setup.ts';
import { OAuthButtons } from './oauth-buttons.tsx';

vi.mock('@/shared/api/index.ts', () => ({
  oauthApi: {
    getProviders: vi.fn().mockResolvedValue({ providers: [] }),
    getAuthorizeUrl: vi.fn((provider: string) => `https://auth.example.com/${provider}`),
  },
}));

import { oauthApi } from '@/shared/api/index.ts';

const mockGetProviders: ReturnType<typeof vi.mocked<typeof oauthApi.getProviders>> = vi.mocked(
  oauthApi.getProviders,
);

function renderOAuthButtons(returnUrl?: string): RenderResult {
  return render(
    <I18nextProvider i18n={i18n}>
      <OAuthButtons returnUrl={returnUrl} />
    </I18nextProvider>,
  );
}

function createPendingPromise<T>(): Promise<T> {
  return new Promise<T>(() => {
    /* intentionally never resolves */
  });
}

describe('OAuthButtons loading', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('shows skeleton loading state initially', () => {
    mockGetProviders.mockImplementation(createPendingPromise);
    renderOAuthButtons();

    expect(screen.queryByTestId('oauth-google')).not.toBeInTheDocument();
    expect(screen.queryByTestId('oauth-github')).not.toBeInTheDocument();
  });
});

describe('OAuthButtons enabled providers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders Google and GitHub buttons when providers are enabled', async () => {
    mockGetProviders.mockResolvedValue({
      providers: [
        { id: 'google', name: 'Google', enabled: true },
        { id: 'github', name: 'GitHub', enabled: true },
      ],
    });

    renderOAuthButtons();

    await waitFor(() => {
      expect(screen.getByTestId('oauth-google')).toBeInTheDocument();
      expect(screen.getByTestId('oauth-github')).toBeInTheDocument();
    });
  });

  test('enables only available providers', async () => {
    mockGetProviders.mockResolvedValue({
      providers: [
        { id: 'google', name: 'Google', enabled: true },
        { id: 'github', name: 'GitHub', enabled: false },
      ],
    });

    renderOAuthButtons();

    await waitFor(() => {
      expect(screen.getByTestId('oauth-google')).not.toBeDisabled();
      expect(screen.getByTestId('oauth-github')).toBeDisabled();
    });
  });
});

describe('OAuthButtons disabled states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders unavailable providers as native disabled buttons', async () => {
    mockGetProviders.mockResolvedValue({
      providers: [
        { id: 'google', name: 'Google', enabled: false },
        { id: 'github', name: 'GitHub', enabled: false },
      ],
    });

    renderOAuthButtons();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /continue with google/iu })).toBeDisabled();
      expect(screen.getByRole('button', { name: /continue with github/iu })).toBeDisabled();
    });
  });

  test('handles empty providers list', async () => {
    mockGetProviders.mockResolvedValue({ providers: [] });
    renderOAuthButtons();

    await waitFor(() => {
      expect(screen.getByTestId('oauth-google')).toBeDisabled();
      expect(screen.getByTestId('oauth-github')).toBeDisabled();
    });
  });

  test('handles undefined providers', async () => {
    mockGetProviders.mockResolvedValue({ providers: [] });
    renderOAuthButtons();

    await waitFor(() => {
      expect(screen.getByTestId('oauth-google')).toBeDisabled();
      expect(screen.getByTestId('oauth-github')).toBeDisabled();
    });
  });

  test('disables buttons on API error', async () => {
    mockGetProviders.mockRejectedValue(new Error('API Error'));
    renderOAuthButtons();

    await waitFor(() => {
      expect(screen.getByTestId('oauth-google')).toBeDisabled();
      expect(screen.getByTestId('oauth-github')).toBeDisabled();
    });
  });
});

describe('OAuthButtons unavailable provider presentation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('keeps unavailable copy hidden initially and reveals one tooltip on hover', async () => {
    const user = userEvent.setup();
    mockGetProviders.mockResolvedValue({
      providers: [
        { id: 'google', name: 'Google', enabled: false },
        { id: 'github', name: 'GitHub', enabled: false },
      ],
    });

    renderOAuthButtons();

    const googleButton = await screen.findByRole('button', { name: /continue with google/iu });
    expect(screen.queryByText(/currently unavailable/iu)).not.toBeInTheDocument();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(googleButton.parentElement).toHaveClass('cursor-not-allowed');

    await user.hover(googleButton.parentElement as HTMLElement);

    const tooltip = await screen.findByRole('tooltip');
    expect(tooltip).toHaveTextContent(/^This provider is currently unavailable\.?$/u);
  });

  test('keeps enabled providers as operable buttons using the existing authorize URL mock', async () => {
    const user = userEvent.setup();
    const savedLocation = globalThis.location;
    vi.stubGlobal('location', { href: '' });
    mockGetProviders.mockResolvedValue({
      providers: [
        { id: 'google', name: 'Google', enabled: true },
        { id: 'github', name: 'GitHub', enabled: false },
      ],
    });

    renderOAuthButtons();
    const googleButton = await screen.findByRole('button', { name: /continue with google/iu });
    await user.click(googleButton);

    expect(globalThis.location.href).toBe('https://auth.example.com/google');
    expect(screen.getByRole('button', { name: /continue with github/iu })).toBeDisabled();
    vi.stubGlobal('location', savedLocation);
  });
});

describe('OAuthButtons accessibility', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('buttons have type button to prevent form submission', async () => {
    mockGetProviders.mockResolvedValue({
      providers: [
        { id: 'google', name: 'Google', enabled: true },
        { id: 'github', name: 'GitHub', enabled: true },
      ],
    });

    renderOAuthButtons();

    await waitFor(() => {
      expect(screen.getByTestId('oauth-google')).toHaveAttribute('type', 'button');
      expect(screen.getByTestId('oauth-github')).toHaveAttribute('type', 'button');
    });
  });

  test('buttons have accessible labels', async () => {
    mockGetProviders.mockResolvedValue({
      providers: [
        { id: 'google', name: 'Google', enabled: true },
        { id: 'github', name: 'GitHub', enabled: true },
      ],
    });

    renderOAuthButtons();

    await waitFor(() => {
      expect(screen.getByTestId('oauth-google')).toHaveAttribute('aria-label');
      expect(screen.getByTestId('oauth-github')).toHaveAttribute('aria-label');
    });
  });
});

describe('OAuthButtons redirect safety', () => {
  const originalLocation = globalThis.location;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('location', { href: '' });
    mockGetProviders.mockResolvedValue({
      providers: [{ id: 'google', name: 'Google', enabled: true }],
    });
  });

  afterEach(() => {
    vi.stubGlobal('location', originalLocation);
  });

  test('delegates the complete deep link to the shared authorize URL builder', async () => {
    const user = userEvent.setup();
    const returnUrl = '/jobs/matches?minScore=75&remote=true#results';
    renderOAuthButtons(returnUrl);

    await user.click(await screen.findByTestId('oauth-google'));

    expect(oauthApi.getAuthorizeUrl).toHaveBeenCalledWith('google', returnUrl);
  });

  test.each([
    'https://attacker.example/steal',
    '//attacker.example/steal',
    '/\\attacker.example/steal',
    '/jobs\nadmin',
    `/${'a'.repeat(2048)}`,
  ])('does not append unsafe returnUrl %s to an authorize request', async (returnUrl) => {
    const user = userEvent.setup();
    renderOAuthButtons(returnUrl);
    const googleButton = await screen.findByTestId('oauth-google');

    await user.click(googleButton);

    expect(globalThis.location.href).toBe('https://auth.example.com/google');
  });
});
