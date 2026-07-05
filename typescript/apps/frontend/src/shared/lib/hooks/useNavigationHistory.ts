import { useNavigate, useRouter } from '@tanstack/react-router';
import { useEffect, useRef } from 'react';
import { handleNavigationPromise } from '@/shared/lib/index.ts';

/** Maximum internal navigation entries to retain. */
const MAX_HISTORY_SIZE = 20;

interface NavigationHistoryEntry {
  /** Route pathname (excludes search params, which are route-specific). */
  readonly pathname: string;
  /** Monotonic timestamp for ordering. */
  readonly timestamp: number;
}

interface UseNavigationHistoryResult {
  /** Whether there is a meaningful internal page to go back to. */
  readonly canGoBack: boolean;
  /** Navigate to the previous internal page. Falls back to `fallbackTo` when
   *  no history exists. The caller must always provide a fallback route so
   *  deep-link users still get a sensible destination. */
  goBack: (fallbackTo: string) => void;
}

/**
 * Tracks internal navigation history via TanStack Router subscription.
 *
 * Uses `router.subscribe('onResolved')` to build an internal stack of visited
 * pathnames. `canGoBack` is `true` when the stack has >= 2 entries (current page
 * plus at least one previous). `goBack` calls `window.history.back()` when
 * possible (preserves scroll position and search params), otherwise navigates
 * to the provided fallback route.
 *
 * @example
 * ```tsx
 * const { canGoBack, goBack } = useNavigationHistory();
 * if (canGoBack) goBack('/fallback');
 * ```
 */
function useNavigationHistory(): UseNavigationHistoryResult {
  const router = useRouter();
  const navigate = useNavigate();
  const stackRef = useRef<NavigationHistoryEntry[]>([]);

  useEffect(() => {
    // Seed with the current location so first-page loads are counted
    const current = router.state.location.pathname;
    if (stackRef.current.length === 0) {
      stackRef.current.push({ pathname: current, timestamp: Date.now() });
    }

    const unsubscribe = router.subscribe('onResolved', ({ toLocation }) => {
      const stack = stackRef.current;
      const { pathname } = toLocation;

      // Avoid duplicate consecutive entries (e.g. search param changes on same page)
      if (stack.length > 0 && stack.at(-1)?.pathname === pathname) {
        return;
      }

      stack.push({ pathname, timestamp: Date.now() });

      // Cap stack size to prevent unbounded growth
      if (stack.length > MAX_HISTORY_SIZE) {
        stackRef.current = stack.slice(stack.length - MAX_HISTORY_SIZE);
      }
    });

    return unsubscribe;
  }, [router]);

  const canGoBack = stackRef.current.length >= 2;

  const goBack = (fallbackTo: string): void => {
    if (canGoBack) {
      globalThis.history.back();
    } else {
      handleNavigationPromise(navigate({ to: fallbackTo }));
    }
  };

  return { canGoBack, goBack };
}

export { MAX_HISTORY_SIZE, useNavigationHistory };
