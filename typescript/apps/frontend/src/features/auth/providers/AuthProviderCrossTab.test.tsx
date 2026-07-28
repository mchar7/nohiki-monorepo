import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { SessionResponse } from '@/shared/api';
import { useAppStore } from '@/shared/model/index.ts';
import { makeQuerySuccess } from '@/shared/test-utils';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { AuthProvider } from './AuthProvider.tsx';

const mocks = vi.hoisted(() => ({
  clearPersistence: vi.fn<() => Promise<void>>(),
  resetResources: vi.fn(),
  subscribe: vi.fn(),
}));

vi.mock('@/shared/lib/persistence/index.ts', () => ({
  clearUserScopedPersistence: mocks.clearPersistence,
}));
vi.mock('@/shared/api/index.ts', () => ({
  useSession: vi.fn(),
  scheduleTokenRefresh: vi.fn(),
  cancelScheduledRefresh: vi.fn(),
  refreshToken: vi.fn().mockResolvedValue(true),
  resetUserSessionResources: mocks.resetResources,
  subscribeToAuthTransitions: mocks.subscribe,
}));

import { useSession } from '@/shared/api/index.ts';

const mockUseSession = vi.mocked(useSession);
let remoteTransition: ((userId: string | null) => void) | undefined;

function wrapper(queryClient: QueryClient, children: ReactNode): ReactNode {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

async function renderProvider(queryClient: QueryClient): Promise<void> {
  const jsx = await wrapWithRouter(
    wrapper(queryClient, <AuthProvider>content</AuthProvider>),
    '/dashboard',
  );
  render(jsx);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.clearPersistence.mockResolvedValue(undefined);
  mocks.subscribe.mockImplementation((handler: (userId: string | null) => void) => {
    remoteTransition = handler;
    return vi.fn();
  });
  mockUseSession.mockReturnValue(
    makeQuerySuccess<SessionResponse | undefined>({
      user_id: 'current-user',
      roles: [],
      permissions: [],
    }),
  );
  useAppStore.setState({
    session: { userId: 'current-user', roles: [], permissions: [] },
    selectedProfileId: 'private-profile',
  });
  vi.stubGlobal('location', { href: '' });
});

describe('AuthProvider remote auth transitions', () => {
  test.each<[string, string | null]>([
    ['logout', null],
    ['account switch', 'other-user'],
  ])('clears private memory and persistence once on remote %s while preserving public cache', async (_label, userId) => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['profiles'], [{ id: 'private-profile' }]);
    queryClient.setQueryData(['skills', 'public'], [{ id: 'typescript' }]);
    const cancelQueries = vi.spyOn(queryClient, 'cancelQueries');

    await renderProvider(queryClient);
    await act(async () => remoteTransition?.(userId));

    await waitFor(() => expect(globalThis.location.href).toBe('/auth'));
    expect(cancelQueries).toHaveBeenCalledTimes(1);
    expect(mocks.clearPersistence).toHaveBeenCalledTimes(1);
    expect(mocks.resetResources).toHaveBeenCalledTimes(1);
    expect(useAppStore.getState().session).toBeNull();
    expect(useAppStore.getState().selectedProfileId).toBeNull();
    expect(queryClient.getQueryData(['profiles'])).toBeUndefined();
    expect(queryClient.getQueryData(['skills', 'public'])).toEqual([{ id: 'typescript' }]);
  });

  test('clears user-scoped openapi-react-query keys whose first segment is the HTTP method', async () => {
    const queryClient = new QueryClient();
    const privateKey = ['get', '/api/v1/profiles', { params: { query: { page: 1 } } }] as const;
    const publicKey = [
      'get',
      '/api/v1/skills',
      { params: { query: { search: 'typescript' } } },
    ] as const;
    queryClient.setQueryData(privateKey, [{ id: 'private-profile' }]);
    queryClient.setQueryData(publicKey, [{ id: 'typescript' }]);

    await renderProvider(queryClient);
    await act(async () => remoteTransition?.('other-user'));

    await waitFor(() => expect(globalThis.location.href).toBe('/auth'));
    expect(queryClient.getQueryData(privateKey)).toBeUndefined();
    expect(queryClient.getQueryData(publicKey)).toEqual([{ id: 'typescript' }]);
  });

  test('waits for in-flight private queries before clearing state and redirecting', async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['profiles'], [{ id: 'private-profile' }]);
    const cancellation = Promise.withResolvers<void>();
    vi.spyOn(queryClient, 'cancelQueries').mockReturnValue(cancellation.promise);

    await renderProvider(queryClient);
    act(() => remoteTransition?.(null));

    expect(queryClient.getQueryData(['profiles'])).toEqual([{ id: 'private-profile' }]);
    expect(mocks.clearPersistence).not.toHaveBeenCalled();
    expect(globalThis.location.href).toBe('');

    cancellation.resolve();
    await waitFor(() => expect(globalThis.location.href).toBe('/auth'));

    expect(queryClient.getQueryData(['profiles'])).toBeUndefined();
    expect(mocks.clearPersistence).toHaveBeenCalledOnce();
    expect(useAppStore.getState().session).toBeNull();
  });

  test('continues fail-closed cleanup when cancelling private queries rejects', async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['profiles'], [{ id: 'private-profile' }]);
    vi.spyOn(queryClient, 'cancelQueries').mockRejectedValue(new Error('cancel failed'));

    await renderProvider(queryClient);
    act(() => remoteTransition?.(null));

    await waitFor(() => expect(globalThis.location.href).toBe('/auth'));
    expect(queryClient.getQueryData(['profiles'])).toBeUndefined();
    expect(mocks.clearPersistence).toHaveBeenCalledOnce();
    expect(useAppStore.getState().session).toBeNull();
  });

  test('ignores a remote transition for the already active identity', async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['profiles'], [{ id: 'private-profile' }]);

    await renderProvider(queryClient);
    await act(async () => remoteTransition?.('current-user'));

    expect(mocks.clearPersistence).not.toHaveBeenCalled();
    expect(mocks.resetResources).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(['profiles'])).toEqual([{ id: 'private-profile' }]);
    expect(globalThis.location.href).toBe('');
  });
});
