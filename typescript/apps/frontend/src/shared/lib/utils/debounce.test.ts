import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { debounce } from './debounce.ts';

/** Standard debounce delay used across most tests */
const DEBOUNCE_DELAY_MS: number = 100;
/** One millisecond before delay fires - function should not have been called */
const DEBOUNCE_BEFORE_FIRE_MS: number = 99;
/** Final tick to trigger after DEBOUNCE_BEFORE_FIRE_MS */
const DEBOUNCE_TICK_MS: number = 1;
/** Half the standard delay - used for mid-debounce reset tests */
const DEBOUNCE_HALF_DELAY_MS: number = 50;
/** Longer delay for numeric-value debounce test */
const _DEBOUNCE_DELAY_NUMERIC_MS: number = 200;
/** Time to advance past cancel so no firing occurs */
const DEBOUNCE_PAST_CANCEL_MS: number = 200;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('debounce - execution timing', () => {
  test('delays function execution', () => {
    const fn = vi.fn();
    const debounced = debounce(fn, DEBOUNCE_DELAY_MS);

    debounced();
    expect(fn).not.toHaveBeenCalled();

    vi.advanceTimersByTime(DEBOUNCE_BEFORE_FIRE_MS);
    expect(fn).not.toHaveBeenCalled();

    vi.advanceTimersByTime(DEBOUNCE_TICK_MS);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  test('resets timer on subsequent calls', () => {
    const fn = vi.fn();
    const debounced = debounce(fn, DEBOUNCE_DELAY_MS);

    debounced();
    vi.advanceTimersByTime(DEBOUNCE_HALF_DELAY_MS);

    debounced();
    vi.advanceTimersByTime(DEBOUNCE_HALF_DELAY_MS);
    expect(fn).not.toHaveBeenCalled();

    vi.advanceTimersByTime(DEBOUNCE_HALF_DELAY_MS);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});

describe('debounce - argument handling', () => {
  test('passes arguments to debounced function', () => {
    const fn = vi.fn();
    const debounced = debounce(fn, DEBOUNCE_DELAY_MS);

    debounced('arg1', 'arg2');
    vi.advanceTimersByTime(DEBOUNCE_DELAY_MS);

    expect(fn).toHaveBeenCalledWith('arg1', 'arg2');
  });

  test('uses latest arguments when called multiple times', () => {
    const fn = vi.fn();
    const debounced = debounce(fn, DEBOUNCE_DELAY_MS);

    debounced('first');
    debounced('second');
    debounced('third');

    vi.advanceTimersByTime(DEBOUNCE_DELAY_MS);

    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith('third');
  });
});

describe('debounce - cancel', () => {
  test('cancels pending execution', () => {
    const fn = vi.fn();
    const debounced = debounce(fn, DEBOUNCE_DELAY_MS);

    debounced();
    debounced.cancel();

    vi.advanceTimersByTime(DEBOUNCE_PAST_CANCEL_MS);
    expect(fn).not.toHaveBeenCalled();
  });

  test('allows new calls after cancel', () => {
    const fn = vi.fn();
    const debounced = debounce(fn, DEBOUNCE_DELAY_MS);

    debounced();
    debounced.cancel();

    debounced();
    vi.advanceTimersByTime(DEBOUNCE_DELAY_MS);

    expect(fn).toHaveBeenCalledTimes(1);
  });
});
