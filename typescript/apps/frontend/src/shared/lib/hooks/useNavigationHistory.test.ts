import { renderHook } from '@testing-library/react';
import type { Mock } from 'vitest';
import { beforeEach, describe, expect, vi } from 'vitest';

vi.mock('@tanstack/react-router', () => ({
  useRouter: vi.fn(),
  useNavigate: vi.fn(),
}));

import { useNavigate, useRouter } from '@tanstack/react-router';

import { MAX_HISTORY_SIZE, useNavigationHistory } from './useNavigationHistory.ts';

const mockUseRouter = vi.mocked(useRouter);
const mockUseNavigate = vi.mocked(useNavigate);

/** Extra navigations beyond MAX_HISTORY_SIZE to verify capping. */
const OVERFLOW_COUNT = 5;

type SubscribeCallback = (event: { toLocation: { pathname: string } }) => void;

interface MockRouter {
  readonly state: { readonly location: { readonly pathname: string } };
  readonly subscribe: Mock;
}

function createMockRouter(initialPathname: string = '/'): {
  router: MockRouter;
  triggerNavigation: (pathname: string) => void;
  unsubscribe: Mock;
} {
  let callback: SubscribeCallback | null = null;
  const unsubscribe: Mock = vi.fn();

  const router: MockRouter = {
    state: { location: { pathname: initialPathname } },
    subscribe: vi.fn((_event: string, cb: SubscribeCallback) => {
      callback = cb;
      return unsubscribe;
    }),
  };

  const triggerNavigation = (pathname: string): void => {
    callback?.({ toLocation: { pathname } });
  };

  return { router, triggerNavigation, unsubscribe };
}

describe('useNavigationHistory - state', () => {
  let mockNavigate: Mock;

  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate = vi.fn().mockResolvedValue(undefined);
    mockUseNavigate.mockReturnValue(mockNavigate as never);
    vi.spyOn(globalThis.history, 'back').mockImplementation(() => undefined);
  });

  test('returns canGoBack: false with no navigation', () => {
    const { router } = createMockRouter('/');
    mockUseRouter.mockReturnValue(router as never);

    const { result } = renderHook(() => useNavigationHistory());

    expect(result.current.canGoBack).toBe(false);
  });

  test('returns canGoBack: true after 2+ navigations', () => {
    const { router, triggerNavigation } = createMockRouter('/page-a');
    mockUseRouter.mockReturnValue(router as never);

    const { result, rerender } = renderHook(() => useNavigationHistory());

    triggerNavigation('/page-b');
    rerender();

    expect(result.current.canGoBack).toBe(true);
  });

  test('caps stack at MAX_HISTORY_SIZE', () => {
    const { router, triggerNavigation } = createMockRouter('/start');
    mockUseRouter.mockReturnValue(router as never);

    const { result, rerender } = renderHook(() => useNavigationHistory());

    const totalNavigations = MAX_HISTORY_SIZE + OVERFLOW_COUNT;
    for (let i = 0; i < totalNavigations; i += 1) {
      triggerNavigation(`/page-${i}`);
    }
    rerender();

    expect(result.current.canGoBack).toBe(true);
  });
});

describe('useNavigationHistory - goBack', () => {
  let mockNavigate: Mock;

  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate = vi.fn().mockResolvedValue(undefined);
    mockUseNavigate.mockReturnValue(mockNavigate as never);
    vi.spyOn(globalThis.history, 'back').mockImplementation(() => undefined);
  });

  test('calls globalThis.history.back() when canGoBack', () => {
    const { router, triggerNavigation } = createMockRouter('/page-a');
    mockUseRouter.mockReturnValue(router as never);

    const { result, rerender } = renderHook(() => useNavigationHistory());

    triggerNavigation('/page-b');
    rerender();

    result.current.goBack('/fallback');

    expect(globalThis.history.back).toHaveBeenCalledOnce();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  test('calls navigate(fallback) when !canGoBack', () => {
    const { router } = createMockRouter('/');
    mockUseRouter.mockReturnValue(router as never);

    const { result } = renderHook(() => useNavigationHistory());

    result.current.goBack('/fallback');

    expect(globalThis.history.back).not.toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/fallback' });
  });
});

describe('useNavigationHistory - cleanup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseNavigate.mockReturnValue(vi.fn().mockResolvedValue(undefined) as never);
    vi.spyOn(globalThis.history, 'back').mockImplementation(() => undefined);
  });

  test('unsubscribes on unmount', () => {
    const { router, unsubscribe } = createMockRouter('/');
    mockUseRouter.mockReturnValue(router as never);

    const { unmount } = renderHook(() => useNavigationHistory());

    unmount();

    expect(unsubscribe).toHaveBeenCalledOnce();
  });
});
