import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';

const TEST_PAGE_NUMBER: number = 3;

vi.mock('@tanstack/react-router', () => ({
  useRouter: vi.fn(),
  useRouterState: vi.fn(),
}));

vi.mock('@/shared/lib/index.ts', () => ({
  handleNavigationPromise: vi.fn(),
}));

import { useRouter, useRouterState } from '@tanstack/react-router';
import { handleNavigationPromise } from '@/shared/lib/index.ts';

import { useJobListingsFilters } from './useJobListingsFilters.ts';

const mockUseRouter = vi.mocked(useRouter);
const mockUseRouterState = vi.mocked(useRouterState);
const mockHandleNavigationPromise = vi.mocked(handleNavigationPromise);

function setupMocks(search: Record<string, unknown>) {
  const mockNavigate = vi.fn(() => Promise.resolve());
  mockUseRouter.mockReturnValue({ navigate: mockNavigate } as never);
  mockUseRouterState.mockImplementation(
    (opts) => opts?.select?.({ location: { search } } as never) as never,
  );
  return mockNavigate;
}

describe('useJobListingsFilters - setPage and setSource', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('setPage navigates preserving existing params', () => {
    const mockNavigate = setupMocks({ page: 1, source: 'linkedin' });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setPage(TEST_PAGE_NUMBER);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: TEST_PAGE_NUMBER, source: 'linkedin' },
    });
    expect(mockHandleNavigationPromise).toHaveBeenCalledWith(mockNavigate.mock.results[0]?.value);
  });

  test('setSource navigates with source string', () => {
    const mockNavigate = setupMocks({ page: 1 });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setSource('linkedin');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, source: 'linkedin' },
    });
  });

  test('setSource navigates with undefined when passed null', () => {
    const mockNavigate = setupMocks({ page: 1, source: 'linkedin' });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setSource(null);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, source: undefined },
    });
  });
});

describe('useJobListingsFilters - setSortField and setSortDirection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('setSortField navigates with new sort and resets page to 1', () => {
    const mockNavigate = setupMocks({ page: 3, sort: 'posted_at', dir: 'desc' });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setSortField('title');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, sort: 'title', dir: 'desc' },
    });
  });

  test('setSortDirection navigates with new dir and resets page to 1', () => {
    const mockNavigate = setupMocks({ page: 2, sort: 'posted_at', dir: 'desc' });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setSortDirection('asc');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, sort: 'posted_at', dir: 'asc' },
    });
  });

  test('preserves every active URL filter when sorting changes', () => {
    const activeSearch = {
      page: 4,
      sort: 'posted_at',
      dir: 'desc',
      source: 'linkedin',
      company: 'Acme',
      q: 'platform engineer',
      showDismissed: true,
      hasSalary: true,
      workArrangement: 'remote',
      seniority: 'senior',
      dateRange: '7d',
    };
    const mockNavigate = setupMocks(activeSearch);
    const { result } = renderHook(() => useJobListingsFilters());

    result.current.setSortField('company_name');

    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { ...activeSearch, page: 1, sort: 'company_name' },
    });
  });
});
