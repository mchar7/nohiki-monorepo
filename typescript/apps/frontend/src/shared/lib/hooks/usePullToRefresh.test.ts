import { fireEvent, renderHook, waitFor } from '@testing-library/react';
import type React from 'react';
import { describe, expect, vi } from 'vitest';
import { PULL_THRESHOLD_PX, usePullToRefresh } from './usePullToRefresh.ts';

describe('usePullToRefresh', () => {
  const createMockRef = (): React.RefObject<HTMLElement | null> => {
    const el = document.createElement('div');
    Object.defineProperty(el, 'scrollTop', {
      value: 0,
      writable: true,
    });
    return { current: el };
  };

  test('Touch start/move/end lifecycle triggers pull distance update', () => {
    const ref = createMockRef();
    const onRefresh = vi.fn();
    const { result } = renderHook(() => usePullToRefresh({ ref, onRefresh }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 0 }] });
    expect(result.current.pullDistance).toBe(0);

    fireEvent.touchMove(el, { touches: [{ clientY: 120, clientX: 0 }] });
    expect(result.current.pullDistance).toBe(20);

    fireEvent.touchEnd(el);
    expect(result.current.pullDistance).toBe(0);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  test('Pull past PULL_THRESHOLD_PX triggers onRefresh callback', async () => {
    const ref = createMockRef();
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => usePullToRefresh({ ref, onRefresh }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 0 }] });
    fireEvent.touchMove(el, { touches: [{ clientY: 100 + PULL_THRESHOLD_PX + 10, clientX: 0 }] });
    expect(result.current.pullDistance).toBe(PULL_THRESHOLD_PX + 10);

    fireEvent.touchEnd(el);
    expect(result.current.pullDistance).toBe(0);
    expect(onRefresh).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(result.current.isRefreshing).toBe(false);
    });
  });

  test('Pull below threshold does NOT trigger refresh', () => {
    const ref = createMockRef();
    const onRefresh = vi.fn();
    const { result } = renderHook(() => usePullToRefresh({ ref, onRefresh }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 0 }] });
    fireEvent.touchMove(el, { touches: [{ clientY: 100 + PULL_THRESHOLD_PX - 10, clientX: 0 }] });
    fireEvent.touchEnd(el);

    expect(result.current.pullDistance).toBe(0);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  test('enabled: false prevents all touch handling', () => {
    const ref = createMockRef();
    const onRefresh = vi.fn();
    const { result } = renderHook(() => usePullToRefresh({ ref, onRefresh, enabled: false }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 0 }] });
    fireEvent.touchMove(el, { touches: [{ clientY: 100 + PULL_THRESHOLD_PX + 10, clientX: 0 }] });

    expect(result.current.pullDistance).toBe(0);

    fireEvent.touchEnd(el);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  test('isRefreshing is true during refresh, false after', async () => {
    const ref = createMockRef();
    let resolveRefresh: () => void = () => undefined;
    const refreshPromise = new Promise<void>((resolve) => {
      resolveRefresh = resolve;
    });
    const onRefresh = vi.fn(() => refreshPromise);

    const { result } = renderHook(() => usePullToRefresh({ ref, onRefresh }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 0 }] });
    fireEvent.touchMove(el, { touches: [{ clientY: 100 + PULL_THRESHOLD_PX + 10, clientX: 0 }] });
    fireEvent.touchEnd(el);

    expect(result.current.isRefreshing).toBe(true);

    resolveRefresh();

    await waitFor(() => {
      expect(result.current.isRefreshing).toBe(false);
    });
  });

  test('Cleanup removes event listeners on unmount', () => {
    const ref = createMockRef();
    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    const addEventListenerSpy = vi.spyOn(el, 'addEventListener');
    const removeEventListenerSpy = vi.spyOn(el, 'removeEventListener');

    const { unmount } = renderHook(() => usePullToRefresh({ ref, onRefresh: vi.fn() }));

    expect(addEventListenerSpy).toHaveBeenCalledWith('touchstart', expect.any(Function), {
      passive: true,
    });
    expect(addEventListenerSpy).toHaveBeenCalledWith('touchmove', expect.any(Function), {
      passive: true,
    });
    expect(addEventListenerSpy).toHaveBeenCalledWith('touchend', expect.any(Function));

    unmount();

    expect(removeEventListenerSpy).toHaveBeenCalledWith('touchstart', expect.any(Function));
    expect(removeEventListenerSpy).toHaveBeenCalledWith('touchmove', expect.any(Function));
    expect(removeEventListenerSpy).toHaveBeenCalledWith('touchend', expect.any(Function));
  });

  test('Concurrent touches (second finger) are ignored', () => {
    const ref = createMockRef();
    const onRefresh = vi.fn();
    const { result } = renderHook(() => usePullToRefresh({ ref, onRefresh }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 0 }] });

    fireEvent.touchMove(el, {
      touches: [
        { clientY: 150, clientX: 0 },
        { clientY: 300, clientX: 0 },
      ],
    });

    expect(result.current.pullDistance).toBe(50);
  });

  test('Horizontal swipe does not trigger vertical pull', () => {
    const ref = createMockRef();
    const onRefresh = vi.fn();
    const { result } = renderHook(() => usePullToRefresh({ ref, onRefresh }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchMove(el, { touches: [{ clientY: 100, clientX: 200 }] });

    expect(result.current.pullDistance).toBe(0);
  });
});
