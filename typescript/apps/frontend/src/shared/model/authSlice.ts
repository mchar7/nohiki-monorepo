import type { StateCreator, StoreApi } from 'zustand';

export interface User {
  readonly id: string;
  readonly email: string;
  readonly displayName?: string;
  readonly firstName?: string;
  readonly lastName?: string;
  readonly isActive: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface Session {
  readonly userId: string;
  readonly roles: readonly string[];
  readonly permissions: readonly string[];
  readonly tenantId?: string | undefined;
}

interface AuthState {
  readonly user: User | null;
  readonly session: Session | null;
  readonly isAuthenticated: boolean;
  readonly isLoading: boolean;
  readonly error: string | null;
}

export interface AuthSlice extends AuthState {
  setUser: (user: User | null) => void;
  setSession: (session: Session | null) => void;
  setLoading: (isLoading: boolean) => void;
  setError: (error: string | null) => void;
  login: (user: User, session: Session) => void;
  logout: () => void;
  clearError: () => void;
}

export const createAuthSlice: StateCreator<AuthSlice, [], [], AuthSlice> = (
  set: StoreApi<AuthSlice>['setState'],
) => ({
  user: null,
  session: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,

  setUser: (user: User | null): void =>
    set({
      user,
      isAuthenticated: user !== null,
    }),

  setSession: (session: Session | null): void =>
    set({
      session,
      isAuthenticated: session !== null,
    }),

  setLoading: (isLoading: boolean): void => set({ isLoading }),

  setError: (error: string | null): void => set({ error, isLoading: false }),

  login: (user: User, session: Session): void =>
    set({
      user,
      session,
      isAuthenticated: true,
      isLoading: false,
      error: null,
    }),

  logout: (): void =>
    set({
      user: null,
      session: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
    }),

  clearError: (): void => set({ error: null }),
});
