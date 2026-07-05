/**
 * Token Refresh Management
 *
 * Implements automatic token refresh before expiry and provides
 * a singleton refresh function for TanStack Query retry integration.
 *
 * Design decisions:
 * - Uses a singleton refresh promise to prevent concurrent refresh requests
 * - Proactive refresh 60 seconds before expiry (timer-based)
 * - Reactive refresh via TanStack Query custom retry on 401
 * - Uses late-bound queryClient reference to avoid import cycle
 */
import type { QueryClient } from '@tanstack/react-query';
import { fetchClient } from './client.ts';
import { queryKeys } from './queryKeys.ts';

let queryClientRef: QueryClient | null = null;

/**
 * Set the QueryClient reference for token refresh operations.
 * Must be called during app initialization before any refresh attempts.
 */
function setTokenRefreshQueryClient(client: QueryClient): void {
  queryClientRef = client;
}

let refreshPromise: Promise<boolean> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;

const MS_PER_SECOND: number = 1000;
const SECONDS_PER_MINUTE: number = 60;
const MS_PER_MINUTE: number = SECONDS_PER_MINUTE * MS_PER_SECOND;
const REFRESH_BUFFER_MS: number = MS_PER_MINUTE;
const ACCESS_TOKEN_LIFETIME_MS: number = 10 * MS_PER_MINUTE;
const TOKEN_REFRESH_LOCK: string = 'nohiki-token-refresh';

async function performTokenRefresh(): Promise<boolean> {
  if (!queryClientRef) {
    return false;
  }

  try {
    const { error } = await fetchClient.POST('/api/v1/auth/refresh');
    if (error) {
      throw error;
    }
    await queryClientRef.invalidateQueries({ queryKey: queryKeys.session });
    return true;
  } catch {
    queryClientRef.setQueryData(queryKeys.session, null);
    queryClientRef.clear();
    return false;
  }
}

/**
 * Attempt a token refresh, deduplicating concurrent calls.
 *
 * Returns true if refresh succeeded, false otherwise.
 * Multiple callers receive the same promise (singleton pattern).
 */
function refreshToken(): Promise<boolean> {
  if (refreshPromise !== null) {
    return refreshPromise;
  }

  const locks = typeof navigator === 'undefined' ? undefined : navigator.locks;
  const pendingRefresh = (
    locks
      ? locks.request(TOKEN_REFRESH_LOCK, performTokenRefresh).then((result) => result)
      : performTokenRefresh()
  ).finally(() => {
    refreshPromise = null;
  });
  refreshPromise = pendingRefresh;

  return pendingRefresh;
}

/**
 * Schedule a proactive token refresh before expiry.
 *
 * Reschedules itself on success for continuous refresh.
 */
function scheduleTokenRefresh(): void {
  cancelScheduledRefresh();

  const refreshIn = ACCESS_TOKEN_LIFETIME_MS - REFRESH_BUFFER_MS;

  refreshTimer = setTimeout(() => {
    refreshToken()
      .then((success) => {
        if (success) {
          scheduleTokenRefresh();
        }
      })
      .catch(() => {
        // Proactive refresh failure is non-fatal; the next API call will trigger reactive refresh
      });
  }, refreshIn);
}

function cancelScheduledRefresh(): void {
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
}

function isRefreshInProgress(): boolean {
  return refreshPromise !== null;
}

export {
  cancelScheduledRefresh,
  isRefreshInProgress,
  refreshToken,
  scheduleTokenRefresh,
  setTokenRefreshQueryClient,
};
