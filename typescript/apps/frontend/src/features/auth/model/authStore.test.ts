import { describe, expect } from 'vitest';
import { createAuthSlice } from './authStore.ts';
import type { Session, User } from './types.ts';

const createMockUser = (overrides: Partial<User> = {}): User => ({
  id: '1',
  email: 'test@example.com',
  displayName: 'Test User',
  isActive: true,
  createdAt: '2024-01-01T00:00:00Z',
  updatedAt: '2024-01-01T00:00:00Z',
  ...overrides,
});

const createMockSession = (overrides: Partial<Session> = {}): Session => ({
  userId: '1',
  roles: ['user'],
  permissions: ['read'],
  ...overrides,
});

function createMockSlice(): {
  getState: () => ReturnType<typeof createAuthSlice>;
  set: (
    partial:
      | Partial<ReturnType<typeof createAuthSlice>>
      | ((s: ReturnType<typeof createAuthSlice>) => Partial<ReturnType<typeof createAuthSlice>>),
  ) => void;
} {
  let state: ReturnType<typeof createAuthSlice>;
  const set = (
    partial: Partial<typeof state> | ((s: typeof state) => Partial<typeof state>),
  ): void => {
    if (typeof partial === 'function') {
      state = { ...state, ...partial(state) };
    } else {
      state = { ...state, ...partial };
    }
  };
  state = createAuthSlice(set, () => state, {} as never);
  return { getState: () => state, set };
}

describe('authStore initial state', () => {
  test('starts with null user', () => {
    const { getState } = createMockSlice();
    expect(getState().user).toBeNull();
  });

  test('starts with null session', () => {
    const { getState } = createMockSlice();
    expect(getState().session).toBeNull();
  });

  test('starts not authenticated', () => {
    const { getState } = createMockSlice();
    expect(getState().isAuthenticated).toBe(false);
  });

  test('starts in loading state', () => {
    const { getState } = createMockSlice();
    expect(getState().isLoading).toBe(true);
  });

  test('starts with no error', () => {
    const { getState } = createMockSlice();
    expect(getState().error).toBeNull();
  });
});

describe('authStore setUser', () => {
  test('sets user and marks as authenticated', () => {
    const { getState } = createMockSlice();
    const user = createMockUser();

    getState().setUser(user);

    expect(getState().user).toEqual(user);
    expect(getState().isAuthenticated).toBe(true);
  });

  test('clears user and marks as not authenticated', () => {
    const { getState } = createMockSlice();
    const user = createMockUser();

    getState().setUser(user);
    getState().setUser(null);

    expect(getState().user).toBeNull();
    expect(getState().isAuthenticated).toBe(false);
  });
});

describe('authStore setSession', () => {
  test('sets session and marks as authenticated', () => {
    const { getState } = createMockSlice();
    const session = createMockSession();

    getState().setSession(session);

    expect(getState().session).toEqual(session);
    expect(getState().isAuthenticated).toBe(true);
  });

  test('clears session and marks as not authenticated', () => {
    const { getState } = createMockSlice();
    const session = createMockSession();

    getState().setSession(session);
    getState().setSession(null);

    expect(getState().session).toBeNull();
    expect(getState().isAuthenticated).toBe(false);
  });
});

describe('authStore setLoading and setError', () => {
  test('sets loading state', () => {
    const { getState } = createMockSlice();

    getState().setLoading(false);
    expect(getState().isLoading).toBe(false);

    getState().setLoading(true);
    expect(getState().isLoading).toBe(true);
  });

  test('sets error and clears loading', () => {
    const { getState } = createMockSlice();

    getState().setError('Authentication failed');

    expect(getState().error).toBe('Authentication failed');
    expect(getState().isLoading).toBe(false);
  });

  test('clears error', () => {
    const { getState } = createMockSlice();

    getState().setError('Some error');
    getState().setError(null);

    expect(getState().error).toBeNull();
  });
});

describe('authStore login and logout', () => {
  test('sets user, session, and auth state on login', () => {
    const { getState } = createMockSlice();
    const user = createMockUser();
    const session = createMockSession();

    getState().login(user, session);

    expect(getState().user).toEqual(user);
    expect(getState().session).toEqual(session);
    expect(getState().isAuthenticated).toBe(true);
    expect(getState().isLoading).toBe(false);
    expect(getState().error).toBeNull();
  });

  test('clears any previous error on login', () => {
    const { getState } = createMockSlice();
    const user = createMockUser();
    const session = createMockSession();

    getState().setError('Previous error');
    getState().login(user, session);

    expect(getState().error).toBeNull();
  });

  test('clears all auth state on logout', () => {
    const { getState } = createMockSlice();
    const user = createMockUser();
    const session = createMockSession();

    getState().login(user, session);
    getState().logout();

    expect(getState().user).toBeNull();
    expect(getState().session).toBeNull();
    expect(getState().isAuthenticated).toBe(false);
    expect(getState().isLoading).toBe(false);
    expect(getState().error).toBeNull();
  });
});

describe('authStore clearError', () => {
  test('clears error without affecting other state', () => {
    const { getState } = createMockSlice();
    const user = createMockUser();
    const session = createMockSession();

    getState().login(user, session);
    getState().setError('Some error');
    getState().clearError();

    expect(getState().error).toBeNull();
    expect(getState().user).toEqual(user);
    expect(getState().isAuthenticated).toBe(true);
  });
});
