/**
 * AuthProvider
 *
 * Provides authentication context and handles:
 * - Session initialization on app load
 * - Automatic token refresh scheduling
 * - 401 response handling with redirect to login
 * - Auth state synchronization with Zustand store
 */

import { useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type ReactNode, useCallback, useEffect, useRef } from 'react';
import { resetDocumentEventStream } from '@/entities/document/index.ts';
import { resetDocumentBuilderStore } from '@/features/omakase/document-builder/model/store.ts';
import { subscribeToAuthTransitions } from '@/shared/api/auth-sync.ts';
import {
  cancelScheduledRefresh,
  refreshToken,
  scheduleTokenRefresh,
  useSession,
} from '@/shared/api/index.ts';
import { clearUserScopedPersistence } from '@/shared/lib/persistence/index.ts';
import { handleNavigationPromise } from '@/shared/lib/utils/navigation.ts';
import type { AppStore } from '@/shared/model/index.ts';
import { useAppStore } from '@/shared/model/index.ts';

const SECONDS_PER_MINUTE: number = 60;
const MS_PER_SECOND: number = 1000;
const SESSION_CHECK_INTERVAL_MS: number = SECONDS_PER_MINUTE * MS_PER_SECOND;
const USER_SCOPED_QUERY_ROOTS: Record<string, true> = {
  session: true,
  account: true,
  profiles: true,
  listings: true,
  correlations: true,
  templates: true,
  schemas: true,
  documents: true,
  attachments: true,
};
const USER_SCOPED_API_PATH_PREFIXES: readonly string[] = [
  '/api/v1/account',
  '/api/v1/profiles',
  '/api/v1/listings',
  '/api/v1/correlations',
  '/api/v1/templates',
  '/api/v1/template-families',
  '/api/v1/schemas',
  '/api/v1/documents',
  '/api/v1/attachments',
];
const HTTP_UNAUTHORIZED = 401;

interface AuthProviderProps {
  readonly children: ReactNode;
}

function AuthProvider({ children }: AuthProviderProps): JSX.Element {
  useSessionSync();
  return <>{children}</>;
}

function useSessionSync(): void {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const sessionCheckRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const locationRef = useRef(location);
  locationRef.current = location;

  const setSession = useAppStore((s) => s.setSession);
  const setLoading = useAppStore((s) => s.setLoading);
  const setError = useAppStore((s) => s.setError);
  const storeLogout = useAppStore((s) => s.logout);
  const { data: session, isLoading, isError, error } = useSession();

  // Stable ref for cross-hook effect deps.
  const handleAuthFailure = useCallback((): void => {
    storeLogout();
    cancelScheduledRefresh();
    const returnUrl = locationRef.current.pathname + locationRef.current.searchStr;
    handleNavigationPromise(navigate({ to: '/auth', search: { returnUrl }, replace: true }));
  }, [storeLogout, navigate]);

  useEffect(() => {
    setLoading(isLoading);
  }, [isLoading, setLoading]);

  useSessionState(session, isLoading, setSession);
  useSessionErrorHandler(isError, error, handleAuthFailure, setError);
  useSessionInterval(session, sessionCheckRef, handleAuthFailure);

  useEffect(
    () =>
      subscribeToAuthTransitions((userId): void => {
        if (userId !== null && userId === session?.user_id) return;

        const userScopedQuery = (query: { queryKey: readonly unknown[] }): boolean => {
          const [root, path] = query.queryKey;
          if (typeof root === 'string' && root in USER_SCOPED_QUERY_ROOTS) return true;
          if (typeof path !== 'string') return false;
          return USER_SCOPED_API_PATH_PREFIXES.some(
            (prefix) => path === prefix || path.startsWith(`${prefix}/`),
          );
        };
        storeLogout();
        useAppStore.getState().clearPendingCommands();
        useAppStore.getState().setSelectedProfileId(null);
        resetDocumentBuilderStore();
        resetDocumentEventStream();
        cancelScheduledRefresh();
        void queryClient
          .cancelQueries({ predicate: userScopedQuery })
          .catch(() => undefined)
          .then(() => {
            queryClient.removeQueries({ predicate: userScopedQuery });
            return clearUserScopedPersistence();
          })
          .catch(() => undefined)
          .finally(() => {
            globalThis.location.href = '/auth';
          });
      }),
    [queryClient, session?.user_id, storeLogout],
  );

  useEffect(
    () => (): void => {
      cancelScheduledRefresh();
      if (sessionCheckRef.current) {
        clearInterval(sessionCheckRef.current);
      }
    },
    [],
  );
}

function useSessionState(
  session: ReturnType<typeof useSession>['data'],
  isLoading: boolean,
  setSession: AppStore['setSession'],
): void {
  useEffect(() => {
    if (session) {
      setSession({
        userId: session.user_id,
        roles: session.roles ?? [],
        permissions: session.permissions ?? [],
        tenantId: session.tenant_id ?? undefined,
      });
      scheduleTokenRefresh();
    } else if (!(isLoading || session)) {
      setSession(null);
    }
  }, [session, isLoading, setSession]);
}

function useSessionErrorHandler(
  isError: boolean,
  error: Error | null,
  handleAuthFailure: () => void,
  setError: AppStore['setError'],
): void {
  useEffect(() => {
    if (isError) {
      const isAuthError =
        error instanceof Error &&
        'status' in error &&
        (error as { status: number }).status === HTTP_UNAUTHORIZED;

      if (isAuthError) {
        handleAuthFailure();
      } else {
        setError(error instanceof Error ? error.message : 'Session check failed');
      }
    }
  }, [isError, error, handleAuthFailure, setError]);
}

function useSessionInterval(
  session: ReturnType<typeof useSession>['data'],
  sessionCheckRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>,
  handleAuthFailure: () => void,
): void {
  useEffect(() => {
    if (session) {
      sessionCheckRef.current = setInterval((): void => {
        void refreshToken()
          .then((refreshed) => {
            if (!refreshed) {
              handleAuthFailure();
            }
          })
          .catch(handleAuthFailure);
      }, SESSION_CHECK_INTERVAL_MS);
    }

    return (): void => {
      if (sessionCheckRef.current) {
        clearInterval(sessionCheckRef.current);
        sessionCheckRef.current = null;
      }
    };
  }, [session, handleAuthFailure, sessionCheckRef]);
}

export { AuthProvider };
