import { renderHook } from '@testing-library/react';
import type { MockInstance } from 'vitest';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { useResizeObserver } from './useResizeObserver.ts';

const mockObserve: MockInstance = vi.fn();
const mockDisconnect: MockInstance = vi.fn();

class MockResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    MockResizeObserver.lastCallback = callback;
  }
  static lastCallback: ResizeObserverCallback | null = null;
  observe = mockObserve;
  disconnect = mockDisconnect;
  unobserve = vi.fn();
}

describe('useResizeObserver', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', MockResizeObserver);
    vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => {
      cb(0);
      return 0;
    });
    vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {
      /* noop stub */
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    MockResizeObserver.lastCallback = null;
  });

  test('returns a ref and initial size of 0x0', () => {
    const { result } = renderHook(() => useResizeObserver());
    expect(result.current[0]).toBeDefined();
    expect(result.current[1]).toEqual({ width: 0, height: 0 });
  });

  test('cleans up on unmount', () => {
    const { unmount } = renderHook(() => useResizeObserver());
    unmount();
    // The hook uses a ref-attached element; disconnect fires only after observe()
    // is called on a real DOM element. In jsdom, the ref is never attached so
    // no observe/disconnect calls happen - but the hook must not throw on cleanup.
    expect(mockObserve).not.toHaveBeenCalled();
    expect(mockDisconnect).not.toHaveBeenCalled();
  });
});
