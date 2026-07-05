import { renderHook } from '@testing-library/react';
import type { Mock } from 'vitest';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useUnsavedChanges } from '../useUnsavedChanges.ts';

vi.mock('@tanstack/react-router', () => ({
  useBlocker: vi.fn(),
}));

// Deferred import so we get the mocked version after vi.mock hoisting.
const getUseBlocker = async () => {
  const mod = await import('@tanstack/react-router');
  return vi.mocked(mod.useBlocker);
};
type UseBlockerOptions = {
  shouldBlockFn: () => boolean;
  withResolver: boolean;
  enableBeforeUnload: boolean;
};

describe('useUnsavedChanges - useBlocker options', () => {
  let useBlockerMock: Mock;

  beforeEach(async () => {
    useBlockerMock = await getUseBlocker();
    useBlockerMock.mockClear();
  });

  test('passes shouldBlockFn returning false and enableBeforeUnload=false when isDirty is false', () => {
    useBlockerMock.mockReturnValue({
      status: 'idle',
      proceed: undefined,
      reset: undefined,
    } as never);

    renderHook(() => useUnsavedChanges(false));

    expect(useBlockerMock).toHaveBeenCalledOnce();
    const [[opts]] = useBlockerMock.mock.calls as [[UseBlockerOptions]];

    expect(opts.shouldBlockFn()).toBe(false);
    expect(opts.enableBeforeUnload).toBe(false);
    expect(opts.withResolver).toBe(true);
  });

  test('passes shouldBlockFn returning true and enableBeforeUnload=true when isDirty is true', () => {
    useBlockerMock.mockReturnValue({
      status: 'blocked',
      proceed: vi.fn(),
      reset: vi.fn(),
    } as never);

    renderHook(() => useUnsavedChanges(true));

    expect(useBlockerMock).toHaveBeenCalledOnce();
    const [[opts]] = useBlockerMock.mock.calls as [[UseBlockerOptions]];

    expect(opts.shouldBlockFn()).toBe(true);
    expect(opts.enableBeforeUnload).toBe(true);
    expect(opts.withResolver).toBe(true);
  });
});

describe('useUnsavedChanges - return value', () => {
  let useBlockerMock: Mock;
  beforeEach(async () => {
    useBlockerMock = await getUseBlocker();
    useBlockerMock.mockClear();
  });

  test('forwards blocked status and callbacks from useBlocker', () => {
    const proceed = vi.fn();
    const reset = vi.fn();
    useBlockerMock.mockReturnValue({ status: 'blocked', proceed, reset } as never);

    const { result } = renderHook(() => useUnsavedChanges(true));

    expect(result.current.status).toBe('blocked');
    expect(result.current.proceed).toBe(proceed);
    expect(result.current.reset).toBe(reset);
  });

  test('forwards idle status and undefined callbacks from useBlocker', () => {
    useBlockerMock.mockReturnValue({
      status: 'idle',
      proceed: undefined,
      reset: undefined,
    } as never);

    const { result } = renderHook(() => useUnsavedChanges(false));

    expect(result.current.status).toBe('idle');
    expect(result.current.proceed).toBeUndefined();
    expect(result.current.reset).toBeUndefined();
  });
});
