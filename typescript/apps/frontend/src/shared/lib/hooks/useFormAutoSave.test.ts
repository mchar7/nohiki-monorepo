import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { useFormAutoSave } from './useFormAutoSave.ts';

const AUTO_SAVE_DEBOUNCE_SHORT_MS: number = 500;
const AUTO_SAVE_DEBOUNCE_STANDARD_MS: number = 1000;
const AUTO_SAVE_DEBOUNCE_LONG_MS: number = 5000;
const AUTOSAVE_TICK_BEFORE_DEBOUNCE_MS: number = 200;
const VERIFY_NO_SAVE_ADVANCE_MS: number = 2000;

vi.mock('@/shared/config', () => ({
  config: {
    form: {
      autoSaveDelay: 1000,
    },
  },
}));

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useFormAutoSave - skip conditions', () => {
  test('does not save when not dirty', () => {
    const onSave = vi.fn();
    const data = { name: 'test' };

    renderHook(() =>
      useFormAutoSave({
        data,
        isDirty: false,
        onSave,
      }),
    );

    vi.advanceTimersByTime(VERIFY_NO_SAVE_ADVANCE_MS);
    expect(onSave).not.toHaveBeenCalled();
  });

  test('does not save when disabled', () => {
    const onSave = vi.fn();
    const data = { name: 'test' };

    renderHook(() =>
      useFormAutoSave({
        data,
        isDirty: true,
        onSave,
        enabled: false,
      }),
    );

    vi.advanceTimersByTime(VERIFY_NO_SAVE_ADVANCE_MS);
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe('useFormAutoSave - basic debounce', () => {
  test('saves after debounce when dirty', () => {
    const onSave = vi.fn();
    const data = { name: 'test' };

    renderHook(() =>
      useFormAutoSave({
        data,
        isDirty: true,
        onSave,
        debounceMs: AUTO_SAVE_DEBOUNCE_SHORT_MS,
      }),
    );

    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    expect(onSave).toHaveBeenCalledWith(data);
  });

  test('debounces multiple changes', () => {
    const onSave = vi.fn();

    const { rerender } = renderHook(
      ({ data }) =>
        useFormAutoSave({
          data,
          isDirty: true,
          onSave,
          debounceMs: AUTO_SAVE_DEBOUNCE_SHORT_MS,
        }),
      { initialProps: { data: { name: 'test1' } } },
    );

    vi.advanceTimersByTime(AUTOSAVE_TICK_BEFORE_DEBOUNCE_MS);
    rerender({ data: { name: 'test2' } });

    vi.advanceTimersByTime(AUTOSAVE_TICK_BEFORE_DEBOUNCE_MS);
    rerender({ data: { name: 'test3' } });

    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({ name: 'test3' });
  });
});

describe('useFormAutoSave - callback stability', () => {
  test('does not reset debounce when onSave reference changes', () => {
    const onSave1 = vi.fn();
    const onSave2 = vi.fn();
    const data = { name: 'test' };

    const { rerender } = renderHook(
      ({ onSave }) =>
        useFormAutoSave({
          data,
          isDirty: true,
          onSave,
          debounceMs: AUTO_SAVE_DEBOUNCE_SHORT_MS,
        }),
      { initialProps: { onSave: onSave1 } },
    );

    // Advance partway through the debounce window
    vi.advanceTimersByTime(AUTOSAVE_TICK_BEFORE_DEBOUNCE_MS);

    // Rerender with a new callback reference (simulates unstable closure)
    rerender({ onSave: onSave2 });

    // Finish the original debounce window; it should still fire
    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS - AUTOSAVE_TICK_BEFORE_DEBOUNCE_MS);

    // The latest callback should have been called, not the original
    expect(onSave1).not.toHaveBeenCalled();
    expect(onSave2).toHaveBeenCalledTimes(1);
    expect(onSave2).toHaveBeenCalledWith(data);
  });

  test('saveNow uses the latest onSave reference', () => {
    const onSave1 = vi.fn();
    const onSave2 = vi.fn();
    const data = { name: 'test' };

    const { result, rerender } = renderHook(
      ({ onSave }) =>
        useFormAutoSave({
          data,
          isDirty: true,
          onSave,
          debounceMs: AUTO_SAVE_DEBOUNCE_LONG_MS,
        }),
      { initialProps: { onSave: onSave1 } },
    );

    rerender({ onSave: onSave2 });

    act(() => {
      result.current.saveNow();
    });

    expect(onSave1).not.toHaveBeenCalled();
    expect(onSave2).toHaveBeenCalledWith(data);
  });
});

describe('useFormAutoSave - unchanged data', () => {
  test('does not save if data has not changed', () => {
    const onSave = vi.fn();
    const data = { name: 'test' };

    const { rerender } = renderHook(
      ({ isDirty }) =>
        useFormAutoSave({
          data,
          isDirty,
          onSave,
          debounceMs: AUTO_SAVE_DEBOUNCE_SHORT_MS,
        }),
      { initialProps: { isDirty: true } },
    );

    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    expect(onSave).toHaveBeenCalledTimes(1);

    rerender({ isDirty: true });
    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    expect(onSave).toHaveBeenCalledTimes(1);
  });
});

describe('useFormAutoSave - saveNow and cleanup', () => {
  test('saveNow triggers immediate save', () => {
    const onSave = vi.fn();
    const data = { name: 'test' };

    const { result } = renderHook(() =>
      useFormAutoSave({
        data,
        isDirty: true,
        onSave,
        debounceMs: AUTO_SAVE_DEBOUNCE_LONG_MS,
      }),
    );

    act(() => {
      result.current.saveNow();
    });

    expect(onSave).toHaveBeenCalledWith(data);
  });

  test('clears timeout on unmount', () => {
    const onSave = vi.fn();
    const data = { name: 'test' };

    const { unmount } = renderHook(() =>
      useFormAutoSave({
        data,
        isDirty: true,
        onSave,
        debounceMs: AUTO_SAVE_DEBOUNCE_STANDARD_MS,
      }),
    );

    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_SHORT_MS);
    unmount();
    vi.advanceTimersByTime(AUTO_SAVE_DEBOUNCE_STANDARD_MS);

    expect(onSave).not.toHaveBeenCalled();
  });
});
