import {
  type UseMutationResult,
  type UseQueryResult,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { resetDocumentEventStream } from '@/entities/document/index.ts';
import { resetDocumentBuilderStore } from '@/features/omakase/document-builder/model/store.ts';
import { clearUserScopedPersistence } from '@/shared/lib/persistence/index.ts';
import { logger } from '@/shared/lib/utils/logger.ts';
import { useAppStore } from '@/shared/model/index.ts';
import { authApi } from './auth-client.ts';
import { publishAuthTransition } from './auth-sync.ts';
import { CACHE_CONFIG } from './config.ts';
import { queryKeys } from './queryClient.ts';
import { cancelScheduledRefresh } from './tokenRefresh.ts';
import type { CreateUserRequest, LoginRequest, SessionResponse } from './types.ts';

/**
 * Hook to get current session from JWT claims.
 *
 * Uses long stale time since session data rarely changes during a session.
 * Retries are disabled - if session check fails, user is not authenticated.
 */
export function useSession(): UseQueryResult<SessionResponse | undefined> {
  return useQuery({
    queryKey: queryKeys.session,
    queryFn: authApi.getSession,
    staleTime: CACHE_CONFIG.SESSION.staleTime,
    gcTime: CACHE_CONFIG.SESSION.gcTime,
    retry: false,
  });
}

/**
 * Hook for user login.
 *
 * On success, invalidates session query to fetch fresh session data.
 * Cookies are set by the backend (HttpOnly).
 */
export function useLogin(): UseMutationResult<
  Awaited<ReturnType<typeof authApi.login>>,
  Error,
  LoginRequest
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (credentials: LoginRequest) => authApi.login(credentials),
    onSuccess: async (): Promise<void> => {
      const session = await queryClient.fetchQuery({
        queryKey: queryKeys.session,
        queryFn: authApi.getSession,
        staleTime: 0,
      });
      publishAuthTransition(session?.user_id ?? null);
    },
  });
}

/**
 * Hook for user registration.
 *
 * On success, fetches fresh session since user is auto-logged-in.
 */
export function useRegister(): UseMutationResult<
  Awaited<ReturnType<typeof authApi.register>>,
  Error,
  CreateUserRequest
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateUserRequest) => authApi.register(data),
    onSuccess: async (): Promise<void> => {
      // Clear any stale/error session data first
      queryClient.removeQueries({ queryKey: queryKeys.session });
      // Fetch fresh session and wait for it to be available
      const session = await authApi.getSession();
      queryClient.setQueryData(queryKeys.session, session);
      publishAuthTransition(session?.user_id ?? null);
    },
  });
}

/**
 * Hook for user logout.
 *
 * On success:
 * - Clears session from cache immediately (optimistic)
 * - Clears all query cache (security: no stale data after logout)
 */
export function useLogout(): UseMutationResult<
  Awaited<ReturnType<typeof authApi.logout>>,
  Error,
  void
> {
  const queryClient = useQueryClient();

  const finishLogout = async (): Promise<void> => {
    const appStore = useAppStore.getState();
    appStore.logout();
    appStore.clearPendingCommands();
    appStore.setSelectedProfileId(null);
    resetDocumentBuilderStore();
    resetDocumentEventStream();
    cancelScheduledRefresh();
    queryClient.setQueryData<SessionResponse | null>(queryKeys.session, null);
    queryClient.clear();

    try {
      await clearUserScopedPersistence();
    } catch (error) {
      logger.error('Failed to clear user-scoped persistence after logout', error);
    }
    publishAuthTransition(null);
    globalThis.location.href = '/auth';
  };

  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: finishLogout,
  });
}

/**
 * Hook for token refresh.
 *
 * Should be called proactively before token expiry.
 * On success, invalidates session to get fresh claims.
 */
export function useRefreshToken(): UseMutationResult<
  Awaited<ReturnType<typeof authApi.refresh>>,
  Error,
  void
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: authApi.refresh,
    onSuccess: async (): Promise<void> => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.session });
    },
  });
}
