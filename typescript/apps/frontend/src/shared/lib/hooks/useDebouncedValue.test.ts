import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { useDebouncedValue } from './useDebouncedValue.ts';

/** Standard debounce delay matching config.ui.debounceDelay (300ms) */
const DEBOUNCE_DEFAULT_MS: number = 300;
/** One millisecond before the default delay fires */
const DEBOUNCE_BEFORE_FIRE_MS: number = 299;
/** Single tick used after DEBOUNCE_BEFORE_FIRE_MS to trigger firing */
const DEBOUNCE_TICK_MS: number = 1;
/** Mid-debounce tick for rapid-change test */
const DEBOUNCE_MID_TICK_MS: number = 100;
/** Alternative delay for numeric-value test */
const DEBOUNCE_ALT_DELAY_MS: number = 200;
/** Numeric value used as debounced state in numeric-value test */
const TEST_DEBOUNCED_NUMBER: number = 42;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useDebouncedValue - initial and basic', () => {
  test('returns initial value immediately', () => {
    const { result } = renderHook(() => useDebouncedValue('hello', DEBOUNCE_DEFAULT_MS));

    expect(result.current).toBe('hello');
  });

  test('debounces updates by specified delay', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, DEBOUNCE_DEFAULT_MS),
      {
        initialProps: { value: 'initial' },
      },
    );

    rerender({ value: 'updated' });
    expect(result.current).toBe('initial');

    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_DEFAULT_MS);
    });

    expect(result.current).toBe('updated');
  });

  test('uses config.ui.debounceDelay as default (300ms)', () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value), {
      initialProps: { value: 'start' },
    });

    rerender({ value: 'changed' });
    expect(result.current).toBe('start');

    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_BEFORE_FIRE_MS);
    });
    expect(result.current).toBe('start');

    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_TICK_MS);
    });
    expect(result.current).toBe('changed');
  });
});

describe('useDebouncedValue - cancel and rapid changes', () => {
  test('cancels pending update on unmount', () => {
    const { result, rerender, unmount } = renderHook(
      ({ value }) => useDebouncedValue(value, DEBOUNCE_DEFAULT_MS),
      {
        initialProps: { value: 'initial' },
      },
    );

    rerender({ value: 'updated' });
    expect(result.current).toBe('initial');

    unmount();

    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_DEFAULT_MS);
    });
  });

  test('handles rapid successive value changes (only last value propagates)', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, DEBOUNCE_DEFAULT_MS),
      {
        initialProps: { value: 'a' },
      },
    );

    rerender({ value: 'b' });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_MID_TICK_MS);
    });

    rerender({ value: 'c' });
    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_MID_TICK_MS);
    });

    rerender({ value: 'd' });
    expect(result.current).toBe('a');

    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_DEFAULT_MS);
    });

    expect(result.current).toBe('d');
  });
});

describe('useDebouncedValue - edge cases', () => {
  test('updates immediately when delay is 0', () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 0), {
      initialProps: { value: 'initial' },
    });

    rerender({ value: 'updated' });

    act(() => {
      vi.advanceTimersByTime(0);
    });

    expect(result.current).toBe('updated');
  });

  test('works with null values', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue<string | null>(value, DEBOUNCE_DEFAULT_MS),
      { initialProps: { value: 'hello' as string | null } },
    );

    rerender({ value: null });
    expect(result.current).toBe('hello');

    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_DEFAULT_MS);
    });

    expect(result.current).toBeNull();
  });

  test('works with numeric values', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, DEBOUNCE_ALT_DELAY_MS),
      {
        initialProps: { value: 0 },
      },
    );

    rerender({ value: TEST_DEBOUNCED_NUMBER });
    expect(result.current).toBe(0);

    act(() => {
      vi.advanceTimersByTime(DEBOUNCE_ALT_DELAY_MS);
    });

    expect(result.current).toBe(TEST_DEBOUNCED_NUMBER);
  });
});
