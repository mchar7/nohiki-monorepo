import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { useFormAutoSave } from './useFormAutoSave.ts';

const AUTO_SAVE_DEBOUNCE_SHORT_MS: number = 500;

vi.mock('@/shared/config', () => ({
  config: { form: { autoSaveDelay: 1000 } },
}));

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useFormAutoSave - custom isEqual: first save skips comparator', () => {
  test('does not invoke isEqual on the very first save because there is no previous snapshot', () => {
    const onSave = vi.fn();
    const isEqual = vi
      .fn<(a: { name: string }, b: { name: string }) => boolean>()
      .mockReturnValue(true);

    renderHook(() =>
      useFormAutoSave({
        data: { name: 'first' },
        isDirty: true,
        onSave,
        isEqual,
        debounceMs: AUTO_SAVE_DEBOUNCE_SHORT_MS,
      }),
    );

    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    expect(onSave).toHaveBeenCalledTimes(1);
    // Short-circuit: lastSaved is undefined, so isEqual is never reached
    expect(isEqual).not.toHaveBeenCalled();
  });
});

describe('useFormAutoSave - custom isEqual: subsequent save suppression', () => {
  test('invokes isEqual on subsequent debounces and skips the save when it returns true', () => {
    const onSave = vi.fn();
    const isEqual = vi
      .fn<(a: { name: string }, b: { name: string }) => boolean>()
      .mockReturnValue(true);

    const { rerender } = renderHook(
      ({ data }) =>
        useFormAutoSave({
          data,
          isDirty: true,
          onSave,
          isEqual,
          debounceMs: AUTO_SAVE_DEBOUNCE_SHORT_MS,
        }),
      { initialProps: { data: { name: 'first' } } },
    );

    // First save fires without calling isEqual (no previous snapshot)
    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    expect(onSave).toHaveBeenCalledTimes(1);

    // Change data to trigger a new debounce; isEqual returns true so no second save
    rerender({ data: { name: 'second' } });
    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    expect(isEqual).toHaveBeenCalled();
    expect(onSave).toHaveBeenCalledTimes(1);
  });
});

describe('useFormAutoSave - custom isEqual: save when comparator returns false', () => {
  test('saves on subsequent renders when custom isEqual always returns false', () => {
    const onSave = vi.fn();
    const isEqual = vi
      .fn<(a: { name: string }, b: { name: string }) => boolean>()
      .mockReturnValue(false);

    const { rerender } = renderHook(
      ({ data }) =>
        useFormAutoSave({
          data,
          isDirty: true,
          onSave,
          isEqual,
          debounceMs: AUTO_SAVE_DEBOUNCE_SHORT_MS,
        }),
      { initialProps: { data: { name: 'first' } } },
    );

    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    expect(onSave).toHaveBeenCalledTimes(1);

    // isEqual returns false, so data is treated as changed and a second save fires
    rerender({ data: { name: 'second' } });
    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    expect(onSave).toHaveBeenCalledTimes(2);
  });
});
