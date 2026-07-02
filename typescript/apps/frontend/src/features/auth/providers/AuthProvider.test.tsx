import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useLocation } from '@tanstack/react-router';
import { act, render, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { SessionResponse } from '@/shared/api';
import { useAppStore } from '@/shared/model/index.ts';
import { makeQueryEmpty, makeQueryLoading } from '@/shared/test-utils';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { AuthProvider } from './AuthProvider.tsx';

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

import { useSession } from '@/shared/api/index.ts';

const mockUseSession: ReturnType<typeof vi.mocked<typeof useSession>> = vi.mocked(useSession);

function LocationDisplay(): JSX.Element {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

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
      <AuthProvider>
        {children}
        <LocationDisplay />
      </AuthProvider>
    </QueryClientProvider>,
    path,
  );
  const result = render(jsx);
  await act(async () => {
    /* wait for effects */
  });
  return result;
}

describe('AuthProvider rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockUseSession.mockReturnValue(makeQueryEmpty<SessionResponse>());
  });

  test('renders children', async () => {
    const { getByText } = await renderAuthTest(<div>Test Content</div>);
    expect(getByText('Test Content')).toBeInTheDocument();
  });
});

describe('AuthProvider loading state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('sets loading to true when session is loading', async () => {
    mockUseSession.mockReturnValue(makeQueryLoading<SessionResponse | undefined>());

    await renderAuthTest(<div>Content</div>);

    await waitFor(() => {
      expect(useAppStore.getState().isLoading).toBe(true);
    });
  });

  test('sets loading to false when session finishes loading', async () => {
    useAppStore.setState({ isLoading: true });

    mockUseSession.mockReturnValue(makeQueryEmpty<SessionResponse>());

    await renderAuthTest(<div>Content</div>);

    await waitFor(() => {
      expect(useAppStore.getState().isLoading).toBe(false);
    });
  });
});
