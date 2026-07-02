import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';

const mockNavigate: ReturnType<typeof vi.fn> = vi.fn();
const mockRefetch: ReturnType<typeof vi.fn> = vi.fn().mockResolvedValue({});

interface SearchParams {
  success?: string;
  error?: string;
  provider?: string;
  returnUrl?: string;
}

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useSearch: vi.fn(),
  };
});

vi.mock('@/shared/api/index.ts', () => ({
  useSession: () => ({
    data: null,
    isLoading: false,
    isError: false,
    error: null,
    refetch: mockRefetch,
  }),
}));

vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, options?: string | Record<string, unknown>) => {
        if (typeof options === 'string') {
          return options;
        }
        return key;
      },
    }),
  };
});

import { useSearch } from '@tanstack/react-router';
import { OAuthCallbackPage } from './oauth-callback-page.tsx';

const LOADING_REDIRECT_TIMEOUT_MS: number = 5000;

function setupMocks(searchParams: SearchParams = {}): void {
  vi.mocked(useSearch).mockReturnValue(searchParams);
}

describe('OAuthCallbackPage loading state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRefetch.mockResolvedValue({});
    mockNavigate.mockClear();
    mockNavigate.mockResolvedValue(undefined);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('displays loading spinner when no success or error in search params', () => {
    setupMocks({});
    render(<OAuthCallbackPage />);
    expect(document.querySelector('.animate-spin')).toBeTruthy();
  });

  test('shows processing text in loading state', () => {
    setupMocks({});
    render(<OAuthCallbackPage />);
    expect(document.querySelector('.animate-spin')).toBeInTheDocument();
  });

  test('redirects to auth page after timeout when stuck in loading', async () => {
    setupMocks({});
    render(<OAuthCallbackPage />);
    expect(mockNavigate).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(LOADING_REDIRECT_TIMEOUT_MS);
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/auth', replace: true });
  });
});

describe('OAuthCallbackPage success state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRefetch.mockResolvedValue({});
    mockNavigate.mockClear();
    mockNavigate.mockResolvedValue(undefined);
  });

  test('refreshes session and navigates home on success', async () => {
    setupMocks({ success: 'true' });
    render(<OAuthCallbackPage />);

    await waitFor(() => {
      expect(mockRefetch).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith({ to: '/', replace: true });
    });
  });

  test('navigates to a deep link only after the refreshed session resolves', async () => {
    let resolveRefresh: (() => void) | undefined;
    mockRefetch.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveRefresh = resolve;
        }),
    );
    const returnUrl = '/jobs/matches?minScore=75#results';
    setupMocks({ success: 'true', returnUrl });
    render(<OAuthCallbackPage />);

    await waitFor(() => expect(mockRefetch).toHaveBeenCalledOnce());
    expect(mockNavigate).not.toHaveBeenCalled();

    resolveRefresh?.();
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith({ to: returnUrl, replace: true });
    });
  });

  test('does not navigate after the callback unmounts while session refresh is pending', async () => {
    const refresh = Promise.withResolvers<void>();
    mockRefetch.mockReturnValue(refresh.promise);
    setupMocks({ success: 'true', returnUrl: '/jobs' });
    const { unmount } = render(<OAuthCallbackPage />);

    await waitFor(() => expect(mockRefetch).toHaveBeenCalledOnce());
    unmount();
    refresh.resolve();
    await refresh.promise;

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  test('stays on the success state when refreshing the session rejects', async () => {
    mockRefetch.mockRejectedValue(new Error('session unavailable'));
    setupMocks({ success: 'true' });
    render(<OAuthCallbackPage />);

    await waitFor(() => expect(mockRefetch).toHaveBeenCalledOnce());
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(screen.getByText('oauth.callback.success')).toBeInTheDocument();
  });

  test.each([
    'https://attacker.example/steal',
    '//attacker.example/steal',
    '/\\attacker.example/steal',
    '/jobs\nadmin',
    `/${'a'.repeat(2048)}`,
  ])('navigates home after OAuth instead of following unsafe returnUrl %s', async (returnUrl) => {
    setupMocks({ success: 'true', returnUrl });
    render(<OAuthCallbackPage />);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith({ to: '/', replace: true });
    });
    expect(mockNavigate).not.toHaveBeenCalledWith({ to: returnUrl, replace: true });
  });

  test('displays success card content', () => {
    setupMocks({ success: 'true' });
    render(<OAuthCallbackPage />);
    expect(document.querySelector('svg')).toBeInTheDocument();
  });
});

function setupErrorStateMocks(): void {
  vi.clearAllMocks();
  mockNavigate.mockResolvedValue(undefined);
  mockRefetch.mockResolvedValue({});
  mockNavigate.mockClear();
}

describe('OAuthCallbackPage error display', () => {
  beforeEach(() => {
    setupErrorStateMocks();
  });

  test('displays an accessible retry action when error param is present', () => {
    setupMocks({ error: 'access_denied', provider: 'github' });
    render(<OAuthCallbackPage />);
    expect(screen.getByRole('button', { name: 'oauth.callback.tryAgain' })).toBeInTheDocument();
  });

  test('navigates to auth root when retry button is clicked', async () => {
    const user = userEvent.setup();
    setupMocks({ error: 'access_denied' });
    render(<OAuthCallbackPage />);

    await user.click(screen.getByRole('button', { name: 'oauth.callback.tryAgain' }));
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/auth', replace: true });
  });

  test('contains a rejected retry navigation promise', async () => {
    mockNavigate.mockRejectedValue(new Error('router disposed'));
    const user = userEvent.setup();
    setupMocks({ error: 'access_denied' });
    render(<OAuthCallbackPage />);

    await user.click(screen.getByRole('button', { name: 'oauth.callback.tryAgain' }));

    expect(mockNavigate).toHaveBeenCalledWith({ to: '/auth', replace: true });
  });

  test('shows provider in error description when provider is present', () => {
    setupMocks({ error: 'access_denied', provider: 'github' });
    render(<OAuthCallbackPage />);
    expect(document.querySelector('button')).toBeTruthy();
  });
});

describe('OAuthCallbackPage error codes', () => {
  beforeEach(() => {
    setupErrorStateMocks();
  });

  test('handles state_mismatch error code', () => {
    setupMocks({ error: 'state_mismatch', provider: 'google' });
    render(<OAuthCallbackPage />);
    expect(document.querySelector('button')).toBeTruthy();
  });

  test('handles code_exchange_failed error code', () => {
    setupMocks({ error: 'code_exchange_failed' });
    render(<OAuthCallbackPage />);
    expect(document.querySelector('button')).toBeTruthy();
  });

  test('handles profile_fetch_failed error code', () => {
    setupMocks({ error: 'profile_fetch_failed' });
    render(<OAuthCallbackPage />);
    expect(document.querySelector('button')).toBeTruthy();
  });

  test('handles account_disabled error code', () => {
    setupMocks({ error: 'account_disabled' });
    render(<OAuthCallbackPage />);
    expect(document.querySelector('button')).toBeTruthy();
  });

  test('handles unknown error codes with generic message', () => {
    setupMocks({ error: 'unknown_error_type' });
    render(<OAuthCallbackPage />);
    expect(document.querySelector('button')).toBeTruthy();
  });
});
