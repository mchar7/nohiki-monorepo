import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';

const TEST_PAGE_NUMBER = 4;
const TEST_MIN_SCORE = 65;
const TEST_MIN_SCORE_ALT = 75;
const TEST_MIN_SCORE_NONZERO = 50;
const TEST_PAGE_2 = 2;

vi.mock('@tanstack/react-router', () => ({
  useRouter: vi.fn(),
  useRouterState: vi.fn(),
}));

vi.mock('@/shared/lib/index.ts', () => ({
  handleNavigationPromise: vi.fn(),
}));

import { useRouter, useRouterState } from '@tanstack/react-router';
import { handleNavigationPromise } from '@/shared/lib/index.ts';

import { useMatchesFilters } from './useMatchesFilters.ts';

const mockUseRouter = vi.mocked(useRouter);
const mockUseRouterState = vi.mocked(useRouterState);
const mockHandleNavigationPromise = vi.mocked(handleNavigationPromise);

function setupMocks(search: Record<string, unknown>): ReturnType<typeof vi.fn> {
  const mockNavigate = vi.fn(() => Promise.resolve());
  mockUseRouter.mockReturnValue({ navigate: mockNavigate } as never);
  mockUseRouterState.mockImplementation(
    (opts) => opts?.select?.({ location: { search } } as never) as never,
  );
  return mockNavigate;
}

describe('useMatchesFilters - filter extraction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('maps present optional params through correctly', () => {
    setupMocks({ page: TEST_PAGE_2, prefId: 'pref-abc', minScore: TEST_MIN_SCORE_ALT });
    const { result } = renderHook(() => useMatchesFilters());
    expect(result.current.filters).toEqual({
      page: TEST_PAGE_2,
      prefId: 'pref-abc',
      minScore: TEST_MIN_SCORE_ALT,
    });
  });
});

describe('useMatchesFilters - hasActiveFilters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('is true when prefId is set', () => {
    setupMocks({ page: 1, prefId: 'pref-abc' });
    const { result } = renderHook(() => useMatchesFilters());
    expect(result.current.hasActiveFilters).toBe(true);
  });

  test('is true when minScore differs from the unfiltered threshold', () => {
    setupMocks({ page: 1, minScore: TEST_MIN_SCORE_NONZERO });
    const { result } = renderHook(() => useMatchesFilters());
    expect(result.current.hasActiveFilters).toBe(true);
  });

  test('is true when minScore is exactly 0', () => {
    setupMocks({ page: 1, minScore: 0 });
    const { result } = renderHook(() => useMatchesFilters());
    expect(result.current.hasActiveFilters).toBe(true);
  });
});

describe('useMatchesFilters - setPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('navigates preserving existing params', () => {
    const mockNavigate = setupMocks({ page: 1, prefId: 'pref-abc' });
    const { result } = renderHook(() => useMatchesFilters());
    result.current.setPage(TEST_PAGE_NUMBER);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs/matches',
      search: { page: TEST_PAGE_NUMBER, prefId: 'pref-abc' },
    });
    expect(mockHandleNavigationPromise).toHaveBeenCalledWith(mockNavigate.mock.results[0]?.value);
  });
});

describe('useMatchesFilters - setPrefId', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('navigates with prefId string', () => {
    const mockNavigate = setupMocks({ page: 1 });
    const { result } = renderHook(() => useMatchesFilters());
    result.current.setPrefId('pref-123');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs/matches',
      search: { page: 1, prefId: 'pref-123' },
    });
  });

  test('navigates with undefined when passed null', () => {
    const mockNavigate = setupMocks({ page: 1, prefId: 'pref-abc' });
    const { result } = renderHook(() => useMatchesFilters());
    result.current.setPrefId(null);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs/matches',
      search: { page: 1, prefId: undefined },
    });
  });
});

describe('useMatchesFilters - setMinScore and clearFilters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('setMinScore navigates with minScore number', () => {
    const mockNavigate = setupMocks({ page: 1 });
    const { result } = renderHook(() => useMatchesFilters());
    result.current.setMinScore(TEST_MIN_SCORE);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs/matches',
      search: { page: 1, minScore: TEST_MIN_SCORE },
    });
  });

  test('setMinScore navigates with undefined when passed null', () => {
    const mockNavigate = setupMocks({ page: 1, minScore: TEST_MIN_SCORE });
    const { result } = renderHook(() => useMatchesFilters());
    result.current.setMinScore(null);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs/matches',
      search: { page: 1, minScore: undefined },
    });
  });

  test('clearFilters navigates to page 1 discarding all params', () => {
    const mockNavigate = setupMocks({
      page: TEST_PAGE_2,
      prefId: 'pref-abc',
      minScore: TEST_MIN_SCORE_NONZERO,
    });
    const { result } = renderHook(() => useMatchesFilters());
    result.current.clearFilters();
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/jobs/matches', search: { page: 1 } });
  });
});
