import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';

const mockClearUserScopedPersistence = vi.hoisted(() => vi.fn());
const mockPublishAuthTransition = vi.hoisted(() => vi.fn());
const mockResetUserSessionResources = vi.hoisted(() => vi.fn());
const mockCancelScheduledRefresh = vi.hoisted(() => vi.fn());

vi.mock('../lib/session-reset.ts', () => ({
  resetUserSessionResources: mockResetUserSessionResources,
}));
vi.mock('./tokenRefresh.ts', () => ({ cancelScheduledRefresh: mockCancelScheduledRefresh }));

vi.mock('@/shared/lib/persistence/index.ts', () => ({
  clearUserScopedPersistence: mockClearUserScopedPersistence,
}));
vi.mock('./auth-sync.ts', () => ({ publishAuthTransition: mockPublishAuthTransition }));

import { useAppStore } from '@/shared/model/index.ts';
import { useLogin, useLogout, useRefreshToken, useRegister, useSession } from './auth-hooks.ts';

vi.mock('./auth-client', () => ({
  authApi: {
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
    getSession: vi.fn(),
  },
}));

import { authApi } from './auth-client.ts';

const mockAuthApi: ReturnType<typeof vi.mocked<typeof authApi>> = vi.mocked(authApi);

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function createWrapper(
  queryClient = createTestQueryClient(),
): ({ children }: { children: ReactNode }) => JSX.Element {
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe('useSession', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('fetches session data', async () => {
    const sessionData = { user_id: 'user-123', roles: ['user'], permissions: [] };
    mockAuthApi.getSession.mockResolvedValue(sessionData);

    const { result } = renderHook(() => useSession(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(result.current.data).toEqual(sessionData);
    expect(mockAuthApi.getSession).toHaveBeenCalled();
  });

  test('handles session fetch error', async () => {
    mockAuthApi.getSession.mockRejectedValue(new Error('Unauthorized'));

    const { result } = renderHook(() => useSession(), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.isError).toBe(true);
    });
  });
});

describe('useLogin', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls login API with credentials', async () => {
    const loginResponse = { user_id: 'user-123', email: 'test@example.com' };
    const sessionData = { user_id: 'user-123', roles: [], permissions: [] };
    mockAuthApi.login.mockResolvedValue(loginResponse);
    mockAuthApi.getSession.mockResolvedValue(sessionData);

    const { result } = renderHook(() => useLogin(), { wrapper: createWrapper() });

    await result.current.mutateAsync({ email: 'test@example.com', password: 'password123' });

    expect(mockAuthApi.login).toHaveBeenCalledWith({
      email: 'test@example.com',
      password: 'password123',
    });
  });

  test('fetches session after successful login', async () => {
    const loginResponse = { user_id: 'user-123', email: 'test@example.com' };
    const sessionData = { user_id: 'user-123', roles: [], permissions: [] };
    mockAuthApi.login.mockResolvedValue(loginResponse);
    mockAuthApi.getSession.mockResolvedValue(sessionData);

    const { result } = renderHook(() => useLogin(), { wrapper: createWrapper() });

    await result.current.mutateAsync({ email: 'test@example.com', password: 'password123' });

    expect(mockAuthApi.getSession).toHaveBeenCalled();
  });

  test('handles login error', async () => {
    mockAuthApi.login.mockRejectedValue(new Error('Invalid credentials'));

    const { result } = renderHook(() => useLogin(), { wrapper: createWrapper() });

    await expect(
      result.current.mutateAsync({ email: 'test@example.com', password: 'wrong' }),
    ).rejects.toThrow('Invalid credentials');
  });
});

describe('useRegister', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls register API with user data', async () => {
    const registerResponse = { id: 'user-123', email: 'test@example.com', message: 'success' };
    mockAuthApi.register.mockResolvedValue(registerResponse);

    const { result } = renderHook(() => useRegister(), { wrapper: createWrapper() });
    await result.current.mutateAsync({
      email: 'test@example.com',
      password: 'password123',
      display_name: 'John Doe',
    });

    expect(mockAuthApi.register).toHaveBeenCalledWith({
      email: 'test@example.com',
      password: 'password123',
      display_name: 'John Doe',
    });
  });

  test('handles registration error', async () => {
    mockAuthApi.register.mockRejectedValue(new Error('Email already exists'));

    const { result } = renderHook(() => useRegister(), { wrapper: createWrapper() });

    await expect(
      result.current.mutateAsync({
        email: 'test@example.com',
        password: 'password123',
        display_name: 'John Doe',
      }),
    ).rejects.toThrow('Email already exists');
  });
});

const originalLocation = globalThis.location;

describe('useLogout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    vi.stubGlobal('location', { href: '' });
    mockClearUserScopedPersistence.mockImplementation(() => {
      localStorage.removeItem('nohiki-document-builder-store');
      localStorage.removeItem('dataset:private');
    });
  });

  afterEach(() => {
    vi.stubGlobal('location', originalLocation);
    localStorage.clear();
    sessionStorage.clear();
  });

  test('removes user persistence on logout while preserving sign-in preferences', async () => {
    mockAuthApi.logout.mockResolvedValue(undefined);
    localStorage.setItem('nohiki-document-builder-store', '{"datasets":[{"private":true}]}');
    localStorage.setItem('nohiki:theme', 'dark');
    localStorage.setItem('i18nextLng', 'de');
    localStorage.setItem('nohiki_remembered_email', 'user@example.com');

    const { result } = renderHook(() => useLogout(), { wrapper: createWrapper() });
    await result.current.mutateAsync();

    expect(mockClearUserScopedPersistence).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('nohiki-document-builder-store')).toBeNull();
    expect(localStorage.getItem('nohiki:theme')).toBe('dark');
    expect(localStorage.getItem('i18nextLng')).toBe('de');
    expect(localStorage.getItem('nohiki_remembered_email')).toBe('user@example.com');
    expect(globalThis.location.href).toBe('/auth');
  });

  test('resets auth, pending, profile, and document state before failed cleanup can redirect', async () => {
    const cleanup = Promise.withResolvers<void>();
    mockClearUserScopedPersistence.mockReturnValue(cleanup.promise);
    mockAuthApi.logout.mockResolvedValue(undefined);
    useAppStore.getState().setSession({ userId: 'user-123', roles: [], permissions: [] });
    useAppStore.getState().addPendingCommand('request-1', 'generate');
    useAppStore.getState().setSelectedProfileId('profile-1');

    const { result } = renderHook(() => useLogout(), { wrapper: createWrapper() });
    const transition = result.current.mutateAsync();

    await waitFor(() => expect(mockClearUserScopedPersistence).toHaveBeenCalledTimes(1));
    expect(useAppStore.getState().session).toBeNull();
    expect(useAppStore.getState().pendingCommands.size).toBe(0);
    expect(useAppStore.getState().selectedProfileId).toBeNull();
    expect(mockResetUserSessionResources).toHaveBeenCalledTimes(1);
    expect(mockCancelScheduledRefresh).toHaveBeenCalledTimes(1);
    expect(globalThis.location.href).toBe('');

    cleanup.reject(new Error('IndexedDB unavailable'));
    await transition;
    expect(globalThis.location.href).toBe('/auth');
  });

  test('continues the successful logout transition when browser cleanup rejects', async () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(['account', 'private'], { email: 'user@example.com' });
    mockAuthApi.logout.mockResolvedValue(undefined);
    mockClearUserScopedPersistence.mockRejectedValue(new Error('IndexedDB unavailable'));

    const { result } = renderHook(() => useLogout(), { wrapper: createWrapper(queryClient) });
    await result.current.mutateAsync();

    expect(queryClient.getQueryData(['account', 'private'])).toBeUndefined();
    expect(mockPublishAuthTransition).toHaveBeenCalledWith(null);
    expect(globalThis.location.href).toBe('/auth');
  });

  test('does not redirect or broadcast logout when the server rejects logout', async () => {
    mockAuthApi.logout.mockRejectedValue(new Error('Logout failed'));
    localStorage.setItem('dataset:private', '{"email":"user@example.com"}');

    const { result } = renderHook(() => useLogout(), { wrapper: createWrapper() });
    await expect(result.current.mutateAsync()).rejects.toThrow('Logout failed');

    expect(mockClearUserScopedPersistence).not.toHaveBeenCalled();
    expect(mockPublishAuthTransition).not.toHaveBeenCalled();
    expect(globalThis.sessionStorage.getItem('nohiki_logout_warning')).toBeNull();
    expect(globalThis.location.href).toBe('');
    expect(localStorage.getItem('dataset:private')).not.toBeNull();
  });
});

describe('useRefreshToken', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls refresh API', async () => {
    mockAuthApi.refresh.mockResolvedValue(undefined);

    const { result } = renderHook(() => useRefreshToken(), { wrapper: createWrapper() });

    await result.current.mutateAsync();

    expect(mockAuthApi.refresh).toHaveBeenCalled();
  });

  test('handles refresh error', async () => {
    mockAuthApi.refresh.mockRejectedValue(new Error('Token expired'));

    const { result } = renderHook(() => useRefreshToken(), { wrapper: createWrapper() });

    await expect(result.current.mutateAsync()).rejects.toThrow('Token expired');
  });
});
