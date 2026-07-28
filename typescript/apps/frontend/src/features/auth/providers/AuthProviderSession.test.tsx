import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { SessionResponse } from '@/shared/api';
import { useAppStore } from '@/shared/model/index.ts';
import { makeQueryEmpty, makeQuerySuccess } from '@/shared/test-utils';
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
  resetUserSessionResources: vi.fn(),
  subscribeToAuthTransitions: vi.fn(() => vi.fn()),
}));

import { scheduleTokenRefresh, useSession } from '@/shared/api/index.ts';

const mockUseSession: ReturnType<typeof vi.mocked<typeof useSession>> = vi.mocked(useSession);
const mockScheduleTokenRefresh: ReturnType<typeof vi.mocked<typeof scheduleTokenRefresh>> =
  vi.mocked(scheduleTokenRefresh);

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

describe('AuthProvider session data', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockUseSession.mockReturnValue(makeQueryEmpty<SessionResponse>());
  });

  test('sets session when session data is available', async () => {
    mockUseSession.mockReturnValue(
      makeQuerySuccess<SessionResponse | undefined>({
        user_id: 'user-123',
        roles: ['user', 'admin'],
        permissions: ['read', 'write'],
        tenant_id: 'tenant-456',
      }),
    );

    await renderAuthTest(<div>Content</div>);

    await waitFor(() => {
      expect(useAppStore.getState().session).toEqual({
        userId: 'user-123',
        roles: ['user', 'admin'],
        permissions: ['read', 'write'],
        tenantId: 'tenant-456',
      });
    });
  });

  test('sets session with empty arrays when roles/permissions are null', async () => {
    mockUseSession.mockReturnValue(
      makeQuerySuccess<SessionResponse | undefined>({
        user_id: 'user-123',
        roles: [],
        permissions: [],
        tenant_id: null,
      }),
    );

    await renderAuthTest(<div>Content</div>);

    await waitFor(() => {
      expect(useAppStore.getState().session).toEqual({
        userId: 'user-123',
        roles: [],
        permissions: [],
        tenantId: undefined,
      });
    });
  });
});

describe('AuthProvider session null and refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockUseSession.mockReturnValue(makeQueryEmpty<SessionResponse>());
  });

  test('sets session to null when no session and not loading', async () => {
    await renderAuthTest(<div>Content</div>);

    await waitFor(() => {
      expect(useAppStore.getState().session).toBeNull();
    });
  });

  test('schedules token refresh when session is available', async () => {
    mockUseSession.mockReturnValue(
      makeQuerySuccess<SessionResponse | undefined>({
        user_id: 'user-123',
        roles: [],
        permissions: [],
      }),
    );

    await renderAuthTest(<div>Content</div>);

    expect(mockScheduleTokenRefresh).toHaveBeenCalled();
  });
});
