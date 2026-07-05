import { useEffect, useState } from 'react';

/**
 * Breakpoints matching Tailwind CSS defaults and shadcn sidebar behavior.
 * These are consistent with the sidebar's MOBILE_BREAKPOINT of 768px.
 */
export const BREAKPOINTS = {
  /** Extra small screens (phones) */
  xs: 480,
  /** Small screens (large phones, small tablets) */
  sm: 640,
  /** Medium screens (tablets) - matches shadcn sidebar mobile breakpoint */
  md: 768,
  /** Large screens (small laptops) */
  lg: 1024,
  /** Extra large screens (desktops) */
  xl: 1280,
  /** 2XL screens (large desktops) */
  '2xl': 1536,
} as const;

type Breakpoint = keyof typeof BREAKPOINTS;

/**
 * Hook to detect if the viewport matches a media query.
 *
 * @param query - CSS media query string (e.g., '(max-width: 768px)')
 * @returns boolean indicating if the query matches
 *
 * @example
 * ```tsx
 * const isMobile = useMediaQuery('(max-width: 767px)');
 * const prefersReducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
 * ```
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    // SSR safety: return false during server rendering
    if (typeof globalThis.window === 'undefined') {
      return false;
    }
    return globalThis.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof globalThis.window === 'undefined') {
      return;
    }

    const mql = globalThis.matchMedia(query);
    const onChange = (e: MediaQueryListEvent): void => setMatches(e.matches);

    // Set initial value
    setMatches(mql.matches);

    // Listen for changes
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

/**
 * Hook to detect if the viewport is at or below a specific breakpoint.
 * Matches the same behavior as Tailwind's responsive prefixes.
 *
 * @param breakpoint - Breakpoint name from BREAKPOINTS
 * @returns boolean indicating if viewport is at or below the breakpoint
 *
 * @example
 * ```tsx
 * const isMobile = useBreakpoint('md'); // true when < 768px
 * const isTablet = useBreakpoint('lg'); // true when < 1024px
 * ```
 */
export function useBreakpoint(breakpoint: Breakpoint): boolean {
  const width = BREAKPOINTS[breakpoint];
  return useMediaQuery(`(max-width: ${width - 1}px)`);
}

/**
 * Hook to detect if viewport is considered "mobile" for layout purposes.
 * Uses the same 768px breakpoint as shadcn sidebar.
 *
 * This is the preferred hook for responsive layout decisions.
 */
export function useIsMobileLayout(): boolean {
  return useBreakpoint('md');
}

/**
 * Hook to detect if viewport is narrow enough to need single-column layout.
 * Uses 1024px breakpoint (lg).
 */
export function useIsCompactLayout(): boolean {
  return useBreakpoint('lg');
}

/**
 * Hook to detect if viewport width is below a custom threshold.
 * Useful for component-specific responsive behavior.
 *
 * @param widthPx - Width threshold in pixels
 */
export function useIsNarrowerThan(widthPx: number): boolean {
  return useMediaQuery(`(max-width: ${widthPx - 1}px)`);
}

/**
 * Hook to detect if the viewport height is limited.
 * Useful for collapsing secondary UI elements on short screens.
 *
 * @param threshold - Height in pixels (default: 700)
 */
export function useIsShortViewport(threshold: number = 700): boolean {
  return useMediaQuery(`(max-height: ${threshold - 1}px)`);
}

/**
 * Hook to detect user's motion preference.
 * Useful for disabling animations when user prefers reduced motion.
 */
export function usePrefersReducedMotion(): boolean {
  return useMediaQuery('(prefers-reduced-motion: reduce)');
}
