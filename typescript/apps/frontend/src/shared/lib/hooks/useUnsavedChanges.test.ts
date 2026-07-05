import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';

vi.mock('@tanstack/react-router', () => ({
  useBlocker: vi.fn(),
}));

import { useBlocker } from '@tanstack/react-router';
import { useUnsavedChanges } from './useUnsavedChanges.ts';

const mockUseBlocker = vi.mocked(useBlocker);
type UseBlockerOptions = {
  shouldBlockFn?: () => boolean;
  withResolver?: boolean;
  enableBeforeUnload?: boolean;
};

/** Default idle blocker state, returned when navigation is not blocked. */
const IDLE_STATE = { status: 'idle', proceed: undefined, reset: undefined } as const;

/** Blocked state, returned by useBlocker when navigation is intercepted. */
const BLOCKED_STATE = {
  status: 'blocked',
  proceed: vi.fn(),
  reset: vi.fn(),
} as const;

describe('useUnsavedChanges: useBlocker options', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseBlocker.mockReturnValue(IDLE_STATE as never);
  });

  test('passes shouldBlockFn returning false when isDirty is false', () => {
    renderHook(() => useUnsavedChanges(false));

    expect(mockUseBlocker).toHaveBeenCalledOnce();
    const [options] = nonNull(mockUseBlocker.mock.calls[0]) as unknown as [UseBlockerOptions];
    expect(options.shouldBlockFn?.()).toBe(false);
  });

  test('passes shouldBlockFn returning true when isDirty is true', () => {
    renderHook(() => useUnsavedChanges(true));

    expect(mockUseBlocker).toHaveBeenCalledOnce();
    const [options] = nonNull(mockUseBlocker.mock.calls[0]) as unknown as [UseBlockerOptions];
    expect(options.shouldBlockFn?.()).toBe(true);
  });

  test('passes withResolver: true to enable explicit proceed/reset control', () => {
    renderHook(() => useUnsavedChanges(true));

    const [options] = nonNull(mockUseBlocker.mock.calls[0]) as unknown as [UseBlockerOptions];
    expect(options.withResolver).toBe(true);
  });

  test('passes enableBeforeUnload: true when isDirty is true', () => {
    renderHook(() => useUnsavedChanges(true));

    const [options] = nonNull(mockUseBlocker.mock.calls[0]) as unknown as [UseBlockerOptions];
    expect(options.enableBeforeUnload).toBe(true);
  });

  test('passes enableBeforeUnload: false when isDirty is false', () => {
    renderHook(() => useUnsavedChanges(false));

    const [options] = nonNull(mockUseBlocker.mock.calls[0]) as unknown as [UseBlockerOptions];
    expect(options.enableBeforeUnload).toBe(false);
  });
});

describe('useUnsavedChanges: return value', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('returns idle status when navigation is not blocked', () => {
    mockUseBlocker.mockReturnValue(IDLE_STATE as never);

    const { result } = renderHook(() => useUnsavedChanges(false));

    expect(result.current.status).toBe('idle');
    expect(result.current.proceed).toBeUndefined();
    expect(result.current.reset).toBeUndefined();
  });

  test('returns blocked status with proceed and reset when navigation is intercepted', () => {
    mockUseBlocker.mockReturnValue(BLOCKED_STATE as never);

    const { result } = renderHook(() => useUnsavedChanges(true));

    expect(result.current.status).toBe('blocked');
    expect(result.current.proceed).toBeDefined();
    expect(result.current.reset).toBeDefined();
  });

  test('proceed callback is callable when blocked', () => {
    const proceed = vi.fn();
    mockUseBlocker.mockReturnValue({ status: 'blocked', proceed, reset: vi.fn() } as never);

    const { result } = renderHook(() => useUnsavedChanges(true));

    result.current.proceed?.();
    expect(proceed).toHaveBeenCalledOnce();
  });

  test('reset callback is callable when blocked', () => {
    const reset = vi.fn();
    mockUseBlocker.mockReturnValue({ status: 'blocked', proceed: vi.fn(), reset } as never);

    const { result } = renderHook(() => useUnsavedChanges(true));

    result.current.reset?.();
    expect(reset).toHaveBeenCalledOnce();
  });
});
