import { type RefObject, useEffect, useRef, useState } from 'react';

/** Pull distance (px) at which a refresh triggers. */
const PULL_THRESHOLD_PX: number = 60;
const MAX_PULL_DISTANCE_PX: number = PULL_THRESHOLD_PX * 2;

interface UsePullToRefreshOptions {
  readonly ref: RefObject<HTMLElement | null>;
  /** Called when pull threshold is exceeded. Return value is ignored (awaited if thenable). */
  readonly onRefresh: () => void;
  readonly enabled?: boolean;
}

interface UsePullToRefreshResult {
  readonly isRefreshing: boolean;
  readonly pullDistance: number;
}

interface PullRefs {
  readonly startY: React.RefObject<number>;
  readonly isPulling: React.RefObject<boolean>;
  readonly currentPull: React.RefObject<number>;
}

/** Attaches touch listeners and returns a cleanup function. */
function attachPullListeners(
  el: HTMLElement,
  refs: PullRefs,
  setPullDistance: (value: number) => void,
  triggerRefresh: () => void,
): () => void {
  const handleTouchStart = (e: TouchEvent): void => {
    const [touch] = e.touches;
    if (el.scrollTop === 0 && touch) {
      refs.startY.current = touch.clientY;
      refs.isPulling.current = true;
    }
  };

  const handleTouchMove = (e: TouchEvent): void => {
    if (!refs.isPulling.current) {
      return;
    }
    const [touch] = e.touches;
    if (!touch) {
      return;
    }
    const diff = touch.clientY - refs.startY.current;
    if (diff > 0) {
      const clamped = Math.min(diff, MAX_PULL_DISTANCE_PX);
      refs.currentPull.current = clamped;
      setPullDistance(clamped);
    }
  };

  const handleTouchEnd = (): void => {
    if (!refs.isPulling.current) {
      return;
    }
    refs.isPulling.current = false;
    const exceeded = refs.currentPull.current >= PULL_THRESHOLD_PX;
    refs.currentPull.current = 0;
    setPullDistance(0);
    refs.startY.current = 0;
    if (exceeded) {
      triggerRefresh();
    }
  };

  el.addEventListener('touchstart', handleTouchStart, { passive: true });
  el.addEventListener('touchmove', handleTouchMove, { passive: true });
  el.addEventListener('touchend', handleTouchEnd);

  return () => {
    el.removeEventListener('touchstart', handleTouchStart);
    el.removeEventListener('touchmove', handleTouchMove);
    el.removeEventListener('touchend', handleTouchEnd);
  };
}

/**
 * Implements pull-to-refresh gesture detection for scrollable containers.
 * Only triggers when the container is scrolled to the top.
 */
function usePullToRefresh({
  ref,
  onRefresh,
  enabled = true,
}: UsePullToRefreshOptions): UsePullToRefreshResult {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [pullDistance, setPullDistance] = useState(0);
  const startY = useRef(0);
  const isPulling = useRef(false);
  const currentPull = useRef(0);

  useEffect(() => {
    const el = ref.current;
    if (!(el && enabled)) {
      return;
    }

    const triggerRefresh = (): void => {
      setIsRefreshing(true);
      Promise.resolve(onRefresh())
        .catch(() => undefined)
        .finally(() => {
          setIsRefreshing(false);
        });
    };

    return attachPullListeners(
      el,
      { startY, isPulling, currentPull },
      setPullDistance,
      triggerRefresh,
    );
  }, [ref, onRefresh, enabled]);

  return { isRefreshing, pullDistance };
}

export { PULL_THRESHOLD_PX, usePullToRefresh };
