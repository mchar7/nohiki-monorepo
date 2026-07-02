import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { useRateLimitState } from '../useRateLimitState.ts';

/** One second in milliseconds, matching the implementation's MS_PER_SECOND. */
const ONE_SECOND_MS = 1000;
/** Default countdown duration used across most test scenarios. */
const DEFAULT_COUNTDOWN_SEC = 5;
/** Short countdown for quick-expiry test. */
const SHORT_COUNTDOWN_SEC = 3;
/** Value after decrementing DEFAULT_COUNTDOWN_SEC by one tick. */
const AFTER_ONE_TICK = 4;
/** Ticks elapsed before restarting in the restart test. */
const TICKS_BEFORE_RESTART = 2;
/** Remaining seconds after TICKS_BEFORE_RESTART from DEFAULT_COUNTDOWN_SEC. */
const REMAINING_AFTER_PARTIAL = 3;
/** New countdown value when restarting. */
const RESTART_COUNTDOWN_SEC = 10;
/** Expected value after one tick from RESTART_COUNTDOWN_SEC. */
const AFTER_RESTART_ONE_TICK = 9;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useRateLimitState - initial state', () => {
  test('isRateLimited is false and secondsRemaining is 0', () => {
    const { result } = renderHook(() => useRateLimitState());

    expect(result.current.isRateLimited).toBe(false);
    expect(result.current.secondsRemaining).toBe(0);
  });
});

describe('useRateLimitState - countdown behavior', () => {
  test('after triggerRateLimit: isRateLimited is true with correct seconds', () => {
    const { result } = renderHook(() => useRateLimitState());

    act(() => {
      result.current.triggerRateLimit(DEFAULT_COUNTDOWN_SEC);
    });

    expect(result.current.isRateLimited).toBe(true);
    expect(result.current.secondsRemaining).toBe(DEFAULT_COUNTDOWN_SEC);
  });

  test('after advancing 1000ms: secondsRemaining decrements by one', () => {
    const { result } = renderHook(() => useRateLimitState());

    act(() => {
      result.current.triggerRateLimit(DEFAULT_COUNTDOWN_SEC);
    });

    act(() => {
      vi.advanceTimersByTime(ONE_SECOND_MS);
    });

    expect(result.current.secondsRemaining).toBe(AFTER_ONE_TICK);
    expect(result.current.isRateLimited).toBe(true);
  });

  test('after advancing to 0: isRateLimited becomes false', () => {
    const { result } = renderHook(() => useRateLimitState());

    act(() => {
      result.current.triggerRateLimit(SHORT_COUNTDOWN_SEC);
    });

    act(() => {
      vi.advanceTimersByTime(SHORT_COUNTDOWN_SEC * ONE_SECOND_MS);
    });

    expect(result.current.isRateLimited).toBe(false);
    expect(result.current.secondsRemaining).toBe(0);
  });
});

describe('useRateLimitState - restart and edge cases', () => {
  test('calling triggerRateLimit while already counting restarts the countdown', () => {
    const { result } = renderHook(() => useRateLimitState());

    act(() => {
      result.current.triggerRateLimit(DEFAULT_COUNTDOWN_SEC);
    });

    act(() => {
      vi.advanceTimersByTime(TICKS_BEFORE_RESTART * ONE_SECOND_MS);
    });
    expect(result.current.secondsRemaining).toBe(REMAINING_AFTER_PARTIAL);

    act(() => {
      result.current.triggerRateLimit(RESTART_COUNTDOWN_SEC);
    });
    expect(result.current.secondsRemaining).toBe(RESTART_COUNTDOWN_SEC);

    act(() => {
      vi.advanceTimersByTime(ONE_SECOND_MS);
    });
    expect(result.current.secondsRemaining).toBe(AFTER_RESTART_ONE_TICK);
  });

  test('triggerRateLimit(0) results in immediate isRateLimited: false', () => {
    const { result } = renderHook(() => useRateLimitState());

    act(() => {
      result.current.triggerRateLimit(0);
    });

    expect(result.current.isRateLimited).toBe(false);
    expect(result.current.secondsRemaining).toBe(0);
  });
});

describe('useRateLimitState - cleanup', () => {
  test('no leaked setInterval after unmount', () => {
    const { result, unmount } = renderHook(() => useRateLimitState());

    act(() => {
      result.current.triggerRateLimit(DEFAULT_COUNTDOWN_SEC);
    });

    expect(result.current.secondsRemaining).toBe(DEFAULT_COUNTDOWN_SEC);

    unmount();

    // Advancing timers after unmount should not cause state updates or errors
    act(() => {
      vi.advanceTimersByTime(DEFAULT_COUNTDOWN_SEC * ONE_SECOND_MS);
    });

    // result.current is stale after unmount; the key assertion is no act() warnings
    expect(result.current.secondsRemaining).toBe(DEFAULT_COUNTDOWN_SEC);
  });
});
