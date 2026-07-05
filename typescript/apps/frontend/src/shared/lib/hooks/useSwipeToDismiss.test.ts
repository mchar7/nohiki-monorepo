import { fireEvent, renderHook } from '@testing-library/react';
import type React from 'react';
import { describe, expect, vi } from 'vitest';
import { SWIPE_THRESHOLD_PX, useSwipeToDismiss } from './useSwipeToDismiss.ts';

describe('useSwipeToDismiss', () => {
  const createMockRef = (): React.RefObject<HTMLElement | null> => {
    const el = document.createElement('div');
    return { current: el };
  };

  test('Swipe down past threshold calls onDismiss', () => {
    const ref = createMockRef();
    const onDismiss = vi.fn();
    renderHook(() => useSwipeToDismiss({ ref, onDismiss }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [{ clientY: 100 + SWIPE_THRESHOLD_PX + 10, clientX: 100 }],
    });

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  test('Swipe below threshold cancels (no dismiss)', () => {
    const ref = createMockRef();
    const onDismiss = vi.fn();
    renderHook(() => useSwipeToDismiss({ ref, onDismiss }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [{ clientY: 100 + SWIPE_THRESHOLD_PX - 10, clientX: 100 }],
    });

    expect(onDismiss).not.toHaveBeenCalled();
  });

  test("direction: 'down' only responds to vertical swipes", () => {
    const ref = createMockRef();
    const onDismiss = vi.fn();
    renderHook(() => useSwipeToDismiss({ ref, onDismiss, direction: 'down' }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    // Try a horizontal swipe
    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [{ clientY: 100, clientX: 100 + SWIPE_THRESHOLD_PX + 10 }],
    });
    expect(onDismiss).not.toHaveBeenCalled();

    // Try a diagonal swipe where horizontal movement is larger
    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [
        { clientY: 100 + SWIPE_THRESHOLD_PX + 10, clientX: 100 + SWIPE_THRESHOLD_PX + 20 },
      ],
    });
    expect(onDismiss).not.toHaveBeenCalled();

    // Try a vertical swipe
    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [{ clientY: 100 + SWIPE_THRESHOLD_PX + 10, clientX: 100 }],
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  test("direction: 'right' only responds to horizontal swipes", () => {
    const ref = createMockRef();
    const onDismiss = vi.fn();
    renderHook(() => useSwipeToDismiss({ ref, onDismiss, direction: 'right' }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    // Try a vertical swipe
    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [{ clientY: 100 + SWIPE_THRESHOLD_PX + 10, clientX: 100 }],
    });
    expect(onDismiss).not.toHaveBeenCalled();

    // Try a diagonal swipe where vertical movement is larger
    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [
        { clientY: 100 + SWIPE_THRESHOLD_PX + 20, clientX: 100 + SWIPE_THRESHOLD_PX + 10 },
      ],
    });
    expect(onDismiss).not.toHaveBeenCalled();

    // Try a horizontal swipe
    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [{ clientY: 100, clientX: 100 + SWIPE_THRESHOLD_PX + 10 }],
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  test('enabled: false prevents all swipe handling', () => {
    const ref = createMockRef();
    const onDismiss = vi.fn();
    renderHook(() => useSwipeToDismiss({ ref, onDismiss, enabled: false }));

    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    fireEvent.touchStart(el, { touches: [{ clientY: 100, clientX: 100 }] });
    fireEvent.touchEnd(el, {
      changedTouches: [{ clientY: 100 + SWIPE_THRESHOLD_PX + 10, clientX: 100 }],
    });

    expect(onDismiss).not.toHaveBeenCalled();
  });

  test('Cleanup removes listeners on unmount', () => {
    const ref = createMockRef();
    const el = ref.current;
    if (!el) {
      throw new Error('element is null');
    }

    const addEventListenerSpy = vi.spyOn(el, 'addEventListener');
    const removeEventListenerSpy = vi.spyOn(el, 'removeEventListener');

    const { unmount } = renderHook(() => useSwipeToDismiss({ ref, onDismiss: vi.fn() }));

    expect(addEventListenerSpy).toHaveBeenCalledWith('touchstart', expect.any(Function), {
      passive: true,
    });
    expect(addEventListenerSpy).toHaveBeenCalledWith('touchend', expect.any(Function), {
      passive: true,
    });

    unmount();

    expect(removeEventListenerSpy).toHaveBeenCalledWith('touchstart', expect.any(Function));
    expect(removeEventListenerSpy).toHaveBeenCalledWith('touchend', expect.any(Function));
  });
});
