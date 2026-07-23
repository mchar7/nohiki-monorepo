import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { SessionResponse } from '@/shared/api';
import { useAppStore } from '@/shared/model/index.ts';
import { makeQueryEmpty, makeQueryError, makeQuerySuccess } from '@/shared/test-utils';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { AuthProvider } from './AuthProvider.tsx';
import { useAuthRefetch } from './useAuthRefetch.ts';

const SESSION_CHECK_INTERVAL_MS: number = 60_000;

vi.mock('@/shared/api/index.ts', () => ({
  useSession: vi.fn(() => ({
    data: null,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  })),
  scheduleTokenRefresh: vi.fn(),
  cancelScheduledRefresh: vi.fn(),
  refreshToken: vi.fn().mockResolvedValue(true),
}));

import { cancelScheduledRefresh, refreshToken, useSession } from '@/shared/api/index.ts';

const mockUseSession: ReturnType<typeof vi.mocked<typeof useSession>> = vi.mocked(useSession);
const mockCancelScheduledRefresh: ReturnType<typeof vi.mocked<typeof cancelScheduledRefresh>> =
  vi.mocked(cancelScheduledRefresh);
const mockRefreshToken: ReturnType<typeof vi.mocked<typeof refreshToken>> = vi.mocked(refreshToken);

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

const DEFAULT_AUTH_TEST_PATH = '/dashboard';

async function renderAuthTest(
  children: ReactNode,
  path: string = DEFAULT_AUTH_TEST_PATH,
): Promise<ReturnType<typeof render>> {
  const queryClient = createTestQueryClient();
  const jsx = await wrapWithRouter(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>,
    path,
  );
  return render(jsx);
}

describe('AuthProvider 401 errors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls logout and cancels refresh on 401 error', async () => {
    const authError = Object.assign(new Error('Unauthorized'), { status: 401 });

    mockUseSession.mockReturnValue(
      makeQueryError<SessionResponse | undefined, Error & { status?: number }>(authError),
    );

    await renderAuthTest(<div>Content</div>, '/dashboard');

    await waitFor(() => {
      expect(useAppStore.getState().isAuthenticated).toBe(false);
      expect(useAppStore.getState().user).toBeNull();
      expect(useAppStore.getState().session).toBeNull();
    });
    expect(mockCancelScheduledRefresh).toHaveBeenCalled();
  });
});

describe('AuthProvider non-401 errors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('sets error message for non-401 errors', async () => {
    const genericError = new Error('Server error');

    mockUseSession.mockReturnValue(makeQueryError<SessionResponse | undefined>(genericError));

    await renderAuthTest(<div>Content</div>);

    await waitFor(() => {
      expect(useAppStore.getState().error).toBe('Server error');
    });
  });

  test('sets generic error message for non-Error errors', async () => {
    // AuthProvider's error handler accepts unknown errors and falls back to a
    // generic message when the error is not an Error instance. Use a string
    // here (matching the runtime contract) and widen TError to match.
    mockUseSession.mockReturnValue(
      makeQueryError<SessionResponse | undefined, unknown>('string error') as ReturnType<
        typeof useSession
      >,
    );

    await renderAuthTest(<div>Content</div>);

    await waitFor(() => {
      expect(useAppStore.getState().error).toBe('Session check failed');
    });
  });
});

describe('AuthProvider session interval failed refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockUseSession.mockReturnValue(
      makeQuerySuccess<SessionResponse | undefined>({
        user_id: 'user-123',
        roles: [],
        permissions: [],
      }),
    );
  });

  test('calls handleAuthFailure when token refresh fails', async () => {
    mockRefreshToken.mockResolvedValue(false);

    const queryClient = createTestQueryClient();
    const jsx = await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <div>Content</div>
        </AuthProvider>
      </QueryClientProvider>,
    );

    vi.useFakeTimers();
    render(jsx);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SESSION_CHECK_INTERVAL_MS);
    });

    expect(useAppStore.getState().isAuthenticated).toBe(false);
    expect(mockCancelScheduledRefresh).toHaveBeenCalled();

    vi.useRealTimers();
  });

  test('treats a rejected token refresh as an auth failure', async () => {
    mockRefreshToken.mockRejectedValue(new Error('refresh unavailable'));

    const queryClient = createTestQueryClient();
    const jsx = await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <div>Content</div>
        </AuthProvider>
      </QueryClientProvider>,
    );

    vi.useFakeTimers();
    render(jsx);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SESSION_CHECK_INTERVAL_MS);
    });

    expect(useAppStore.getState().isAuthenticated).toBe(false);
    expect(mockCancelScheduledRefresh).toHaveBeenCalled();
    vi.useRealTimers();
  });
});

describe('AuthProvider session interval successful refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockUseSession.mockReturnValue(
      makeQuerySuccess<SessionResponse | undefined>({
        user_id: 'user-123',
        roles: [],
        permissions: [],
      }),
    );
  });

  test('does not call handleAuthFailure when token refresh succeeds', async () => {
    mockRefreshToken.mockResolvedValue(true);

    const queryClient = createTestQueryClient();
    const jsx = await wrapWithRouter(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <div>Content</div>
        </AuthProvider>
      </QueryClientProvider>,
    );

    vi.useFakeTimers();
    render(jsx);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SESSION_CHECK_INTERVAL_MS);
    });

    expect(useAppStore.getState().isAuthenticated).toBe(true);

    vi.useRealTimers();
  });
});

describe('AuthProvider cleanup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('cancels scheduled refresh on unmount', async () => {
    mockUseSession.mockReturnValue(
      makeQuerySuccess<SessionResponse | undefined>({
        user_id: 'user-123',
        roles: [],
        permissions: [],
      }),
    );

    const { unmount } = await renderAuthTest(<div>Content</div>);

    unmount();

    expect(mockCancelScheduledRefresh).toHaveBeenCalled();
  });
});

describe('useAuthRefetch', () => {
  test('returns refetch function from useSession', () => {
    const mockRefetch = vi.fn();
    mockUseSession.mockReturnValue(makeQueryEmpty<SessionResponse>({ refetch: mockRefetch }));

    function TestComponent(): React.JSX.Element {
      const refetch = useAuthRefetch();
      return (
        <button
          type="button"
          onClick={(): void => {
            refetch();
          }}
        >
          Refetch
        </button>
      );
    }

    const queryClient = createTestQueryClient();
    const { getByRole } = render(
      <QueryClientProvider client={queryClient}>
        <TestComponent />
      </QueryClientProvider>,
    );

    getByRole('button').click();
    expect(mockRefetch).toHaveBeenCalled();
  });
});
