import { QueryClient } from '@tanstack/react-query';
import { HTTP_STATUS, QUERY_CONFIG } from '@/shared/config/constants.ts';
import { refreshToken } from './tokenRefresh.ts';

/**
 * Determine whether a failed query should be retried.
 *
 * On 401 (first attempt): trigger token refresh as side effect, return true.
 * The retryDelay gives the refresh request time to complete before retry.
 * On 4xx (non-401): do not retry (client errors are deterministic).
 * On 5xx or network errors: retry with exponential backoff.
 */
function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= QUERY_CONFIG.MAX_RETRIES) {
    return false;
  }

  const status = extractStatus(error);
  if (status === undefined) {
    return true;
  }

  if (status === HTTP_STATUS.UNAUTHORIZED && failureCount === 0) {
    refreshToken().catch(() => {
      // Token refresh failure on 401 is non-fatal; the retry will handle auth failure
    });
    return true;
  }

  return status < HTTP_STATUS.BAD_REQUEST || status >= HTTP_STATUS.INTERNAL_SERVER_ERROR;
}

function extractStatus(error: unknown): number | undefined {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const s = (error as { status: unknown }).status;
    return typeof s === 'number' ? s : undefined;
  }
}

function calculateRetryDelay(attemptIndex: number): number {
  const delay = QUERY_CONFIG.RETRY_DELAY_BASE_MS * 2 ** attemptIndex;
  return Math.min(delay, QUERY_CONFIG.RETRY_DELAY_MAX_MS);
}

export const queryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: QUERY_CONFIG.STALE_TIME_MS,
      gcTime: QUERY_CONFIG.GC_TIME_MS,
      retry: shouldRetryQuery,
      retryDelay: calculateRetryDelay,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
});

export { queryKeys } from './queryKeys.ts';
