import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import {
  BREAKPOINTS,
  useBreakpoint,
  useIsCompactLayout,
  useIsMobileLayout,
  useIsNarrowerThan,
  useIsShortViewport,
  useMediaQuery,
  usePrefersReducedMotion,
} from './useMediaQuery.ts';

/** Expected pixel values for each BREAKPOINTS entry */
const EXPECTED_BREAKPOINT_XS: number = 480;
const EXPECTED_BREAKPOINT_SM: number = 640;
const EXPECTED_BREAKPOINT_MD: number = 768;
const EXPECTED_BREAKPOINT_LG: number = 1024;
const EXPECTED_BREAKPOINT_XL: number = 1280;
const EXPECTED_BREAKPOINT_2XL: number = 1536;
/** Custom narrow width used for useIsNarrowerThan tests */
const CUSTOM_NARROW_WIDTH_PX: number = 500;
/** Custom short viewport height for useIsShortViewport test */
const CUSTOM_SHORT_HEIGHT_PX: number = 500;

let originalMatchMedia: typeof globalThis.matchMedia;
let createdMqls: Map<string, MockMediaQueryList>;

/**
 * jsdom does not implement `window.matchMedia`, so each test must install its
 * own. Extending the real `EventTarget` gives us `addEventListener`,
 * `removeEventListener`, and `dispatchEvent` for free with the exact signatures
 * `MediaQueryList` declares, with no unsafe cast required.
 */
class MockMediaQueryList extends EventTarget implements MediaQueryList {
  readonly media: string;
  matches: boolean;
  onchange: ((this: MediaQueryList, ev: MediaQueryListEvent) => unknown) | null = null;

  constructor(media: string, matches: boolean) {
    super();
    this.media = media;
    this.matches = matches;
  }

  // Legacy addListener/removeListener are deprecated aliases of
  // addEventListener('change', ...) on the real interface.
  addListener(listener: ((this: MediaQueryList, ev: MediaQueryListEvent) => unknown) | null): void {
    if (listener) {
      this.addEventListener('change', listener as EventListener);
    }
  }
  removeListener(
    listener: ((this: MediaQueryList, ev: MediaQueryListEvent) => unknown) | null,
  ): void {
    if (listener) {
      this.removeEventListener('change', listener as EventListener);
    }
  }
}

function installMatchMedia(matches: boolean): void {
  globalThis.matchMedia = (query: string): MediaQueryList => {
    const cached = createdMqls.get(query);
    if (cached !== undefined) {
      return cached;
    }
    const mql = new MockMediaQueryList(query, matches);
    createdMqls.set(query, mql);
    return mql;
  };
}

function fireChange(mql: MockMediaQueryList, matches: boolean): void {
  mql.matches = matches;
  // MediaQueryListEvent is not constructible in jsdom 28; we dispatch a plain
  // Event but extend it with `matches` and `media` so listeners reading those
  // fields receive correct values, matching the browser semantics tested.
  const event = new Event('change') as Event & { matches: boolean; media: string };
  event.matches = matches;
  event.media = mql.media;
  mql.dispatchEvent(event);
}

beforeEach(() => {
  originalMatchMedia = globalThis.matchMedia;
  createdMqls = new Map();
});

afterEach(() => {
  globalThis.matchMedia = originalMatchMedia;
  vi.clearAllMocks();
});

describe('BREAKPOINTS', () => {
  test('has correct values', () => {
    expect(BREAKPOINTS.xs).toBe(EXPECTED_BREAKPOINT_XS);
    expect(BREAKPOINTS.sm).toBe(EXPECTED_BREAKPOINT_SM);
    expect(BREAKPOINTS.md).toBe(EXPECTED_BREAKPOINT_MD);
    expect(BREAKPOINTS.lg).toBe(EXPECTED_BREAKPOINT_LG);
    expect(BREAKPOINTS.xl).toBe(EXPECTED_BREAKPOINT_XL);
    expect(BREAKPOINTS['2xl']).toBe(EXPECTED_BREAKPOINT_2XL);
  });
});

describe('useMediaQuery', () => {
  test('returns true when query matches', () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useMediaQuery('(max-width: 768px)'));
    expect(result.current).toBe(true);
  });

  test('returns false when query does not match', () => {
    installMatchMedia(false);
    const { result } = renderHook(() => useMediaQuery('(max-width: 768px)'));
    expect(result.current).toBe(false);
  });

  test('updates when media query changes', () => {
    installMatchMedia(false);

    const { result } = renderHook(() => useMediaQuery('(max-width: 768px)'));
    expect(result.current).toBe(false);

    const mql = createdMqls.get('(max-width: 768px)');
    if (mql === undefined) {
      throw new Error('expected matchMedia to have been called for the query');
    }
    act(() => {
      fireChange(mql, true);
    });

    expect(result.current).toBe(true);
  });
});

describe('useBreakpoint', () => {
  test('uses correct query for md breakpoint', () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useBreakpoint('md'));
    expect(result.current).toBe(true);
  });

  test('uses correct query for lg breakpoint', () => {
    installMatchMedia(false);
    const { result } = renderHook(() => useBreakpoint('lg'));
    expect(result.current).toBe(false);
  });
});

describe('useIsMobileLayout', () => {
  test('returns true for mobile viewport', () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useIsMobileLayout());
    expect(result.current).toBe(true);
  });

  test('returns false for desktop viewport', () => {
    installMatchMedia(false);
    const { result } = renderHook(() => useIsMobileLayout());
    expect(result.current).toBe(false);
  });
});

describe('useIsCompactLayout', () => {
  test('returns true for compact viewport', () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useIsCompactLayout());
    expect(result.current).toBe(true);
  });
});

describe('useIsNarrowerThan', () => {
  test('uses custom width threshold', () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useIsNarrowerThan(CUSTOM_NARROW_WIDTH_PX));
    expect(result.current).toBe(true);
  });

  test('returns false when wider than threshold', () => {
    installMatchMedia(false);
    const { result } = renderHook(() => useIsNarrowerThan(CUSTOM_NARROW_WIDTH_PX));
    expect(result.current).toBe(false);
  });
});

describe('useIsShortViewport', () => {
  test('returns false when viewport is tall', () => {
    installMatchMedia(false);
    const { result } = renderHook(() => useIsShortViewport());
    expect(result.current).toBe(false);
  });

  test('returns true when viewport is short', () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useIsShortViewport(CUSTOM_SHORT_HEIGHT_PX));
    expect(result.current).toBe(true);
  });
});

describe('usePrefersReducedMotion', () => {
  test('returns true when user prefers reduced motion', () => {
    installMatchMedia(true);
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(true);
  });

  test('returns false when user does not prefer reduced motion', () => {
    installMatchMedia(false);
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
  });
});
