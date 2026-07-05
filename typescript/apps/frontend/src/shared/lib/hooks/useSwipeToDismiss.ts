import { type RefObject, useEffect, useRef } from 'react';

const SWIPE_THRESHOLD_PX = 80;

interface UseSwipeToDismissOptions {
  readonly ref: RefObject<HTMLElement | null>;
  readonly onDismiss: () => void;
  readonly enabled?: boolean;
  readonly direction?: 'down' | 'right';
}

/**
 * Detects swipe gestures on a target element and triggers dismiss callback
 * when the swipe distance exceeds the threshold.
 */
function useSwipeToDismiss({
  ref,
  onDismiss,
  enabled = true,
  direction = 'down',
}: UseSwipeToDismissOptions): void {
  const startY = useRef(0);
  const startX = useRef(0);

  useEffect(() => {
    const el = ref.current;
    if (!(el && enabled)) {
      return;
    }

    const handleTouchStart = (e: TouchEvent): void => {
      const [touch] = e.touches;
      if (touch) {
        startY.current = touch.clientY;
        startX.current = touch.clientX;
      }
    };

    const handleTouchEnd = (e: TouchEvent): void => {
      const [changedTouch] = e.changedTouches;
      if (!changedTouch) {
        return;
      }
      const endY = changedTouch.clientY;
      const endX = changedTouch.clientX;
      const diffY = endY - startY.current;
      const diffX = endX - startX.current;

      if (direction === 'down' && diffY > SWIPE_THRESHOLD_PX && Math.abs(diffX) < diffY) {
        onDismiss();
      }
      if (direction === 'right' && diffX > SWIPE_THRESHOLD_PX && Math.abs(diffY) < diffX) {
        onDismiss();
      }
    };

    el.addEventListener('touchstart', handleTouchStart, { passive: true });
    el.addEventListener('touchend', handleTouchEnd, { passive: true });

    return () => {
      el.removeEventListener('touchstart', handleTouchStart);
      el.removeEventListener('touchend', handleTouchEnd);
    };
  }, [ref, onDismiss, enabled, direction]);
}

export { SWIPE_THRESHOLD_PX, useSwipeToDismiss };
