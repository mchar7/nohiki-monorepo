import type { MockInstance } from 'vitest';

const MS_PER_SECOND_TEST: number = 1000;
const SECONDS_PER_MINUTE_TEST: number = 60;
const MS_PER_MINUTE_TEST: number = SECONDS_PER_MINUTE_TEST * MS_PER_SECOND_TEST;
/** Scheduled refresh fires at ACCESS_TOKEN_LIFETIME_MS - REFRESH_BUFFER_MS = 10min - 1min = 9min */
const SCHEDULED_REFRESH_DELAY_MINUTES: number = 9;
const SCHEDULED_REFRESH_DELAY_MS: number = SCHEDULED_REFRESH_DELAY_MINUTES * MS_PER_MINUTE_TEST;

import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import {
  cancelScheduledRefresh,
  isRefreshInProgress,
  refreshToken,
  scheduleTokenRefresh,
  setTokenRefreshQueryClient,
} from './tokenRefresh.ts';

const { mockPost }: { mockPost: MockInstance } = vi.hoisted(() => ({
  mockPost: vi.fn().mockResolvedValue({ data: undefined, error: undefined }),
}));

vi.mock('@/shared/api/client', () => ({
  fetchClient: { GET: vi.fn(), POST: mockPost, DELETE: vi.fn(), PATCH: vi.fn(), PUT: vi.fn() },
  $api: { useQuery: vi.fn(), useMutation: vi.fn() },
  createDevClient: vi.fn(),
}));

vi.mock('./queryKeys', () => ({
  queryKeys: {
    session: ['session'],
  },
}));

const mockRefresh: MockInstance = mockPost;

const mockQueryClient: {
  invalidateQueries: MockInstance;
  setQueryData: MockInstance;
  clear: MockInstance;
} = {
  invalidateQueries: vi.fn().mockResolvedValue(undefined),
  setQueryData: vi.fn(),
  clear: vi.fn(),
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  cancelScheduledRefresh();
  setTokenRefreshQueryClient(mockQueryClient as never);
});

afterEach(() => {
  vi.useRealTimers();
  cancelScheduledRefresh();
});

describe('tokenRefresh - isRefreshInProgress', () => {
  test('returns false when no refresh is in progress', () => {
    expect(isRefreshInProgress()).toBe(false);
  });
});

describe('tokenRefresh - scheduleTokenRefresh', () => {
  test('schedules refresh before token expiry', () => {
    scheduleTokenRefresh();
    expect(isRefreshInProgress()).toBe(false);
  });

  test('cancels previous scheduled refresh', () => {
    scheduleTokenRefresh();
    scheduleTokenRefresh();
    expect(isRefreshInProgress()).toBe(false);
  });
});

describe('tokenRefresh - cancelScheduledRefresh', () => {
  test('cancels scheduled refresh', () => {
    scheduleTokenRefresh();
    cancelScheduledRefresh();
    expect(isRefreshInProgress()).toBe(false);
  });

  test('handles being called when no refresh is scheduled', () => {
    expect(() => cancelScheduledRefresh()).not.toThrow();
  });
});

describe('tokenRefresh - refreshToken', () => {
  test('returns true on successful refresh', async () => {
    mockRefresh.mockResolvedValueOnce({ data: undefined, error: undefined });
    const result = await refreshToken();
    expect(result).toBe(true);
    expect(mockRefresh).toHaveBeenCalled();
    expect(mockQueryClient.invalidateQueries).toHaveBeenCalled();
  });

  test('returns false on failed refresh', async () => {
    mockRefresh.mockRejectedValueOnce(new Error('Failed'));
    const result = await refreshToken();
    expect(result).toBe(false);
    expect(mockQueryClient.setQueryData).toHaveBeenCalled();
    expect(mockQueryClient.clear).toHaveBeenCalled();
  });

  test('serializes refreshes from separate tab module instances with Web Locks', async () => {
    const firstRefresh = Promise.withResolvers<{ data: undefined; error: undefined }>();
    let activeRefreshes = 0;
    let maximumActiveRefreshes = 0;
    mockRefresh
      .mockImplementationOnce(async () => {
        activeRefreshes += 1;
        maximumActiveRefreshes = Math.max(maximumActiveRefreshes, activeRefreshes);
        const response = await firstRefresh.promise;
        activeRefreshes -= 1;
        return response;
      })
      .mockImplementationOnce(() => {
        activeRefreshes += 1;
        maximumActiveRefreshes = Math.max(maximumActiveRefreshes, activeRefreshes);
        activeRefreshes -= 1;
        return Promise.resolve({ data: undefined, error: undefined });
      });

    let lockTail = Promise.resolve<unknown>(undefined);
    const request = vi.fn((_name: string, callback: () => Promise<boolean>) => {
      const result = lockTail.then(callback);
      lockTail = result;
      return result;
    });
    vi.stubGlobal('navigator', { ...navigator, locks: { request } });

    const tabOneRefresh = refreshToken();
    // Separate module state represents a second browser tab; static import cannot create that boundary.
    vi.resetModules();
    const tabTwo = await import('./tokenRefresh.ts');
    tabTwo.setTokenRefreshQueryClient(mockQueryClient as never);
    const tabTwoRefresh = tabTwo.refreshToken();

    await vi.waitFor(() => expect(mockRefresh).toHaveBeenCalledTimes(1));
    firstRefresh.resolve({ data: undefined, error: undefined });
    await expect(Promise.all([tabOneRefresh, tabTwoRefresh])).resolves.toEqual([true, true]);
    expect(request).toHaveBeenCalledTimes(2);
    expect(maximumActiveRefreshes).toBe(1);
  });

  test('reuses the in-tab promise when Web Locks are unavailable', async () => {
    vi.stubGlobal('navigator', { ...navigator, locks: undefined });
    const refresh = Promise.withResolvers<{ data: undefined; error: undefined }>();
    mockRefresh.mockReturnValue(refresh.promise);
    const promise1 = refreshToken();
    const promise2 = refreshToken();
    expect(isRefreshInProgress()).toBe(true);
    refresh.resolve({ data: undefined, error: undefined });
    await expect(Promise.all([promise1, promise2])).resolves.toEqual([true, true]);
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });
});

describe('tokenRefresh - integration', () => {
  test('triggers refresh after scheduled delay', async () => {
    mockRefresh.mockResolvedValue({ data: undefined, error: undefined });
    scheduleTokenRefresh();
    expect(mockRefresh).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(SCHEDULED_REFRESH_DELAY_MS);
    expect(mockRefresh).toHaveBeenCalled();
  });
});
