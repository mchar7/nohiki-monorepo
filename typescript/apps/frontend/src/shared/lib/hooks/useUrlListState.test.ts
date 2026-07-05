import { renderHook } from '@testing-library/react';
import type { Mock } from 'vitest';
import { beforeEach, describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';

vi.mock('@tanstack/react-router', () => ({
  useRouter: vi.fn(),
  useRouterState: vi.fn(),
}));

import { useRouter, useRouterState } from '@tanstack/react-router';

import { useUrlListState } from './useUrlListState.ts';

const mockUseRouter = vi.mocked(useRouter);
const mockUseRouterState = vi.mocked(useRouterState);

const TEST_PAGE: number = 3;

function setupMocks(search: Record<string, unknown>): Mock {
  const mockNavigate = vi.fn().mockResolvedValue(undefined);
  mockUseRouter.mockReturnValue({ navigate: mockNavigate } as never);
  mockUseRouterState.mockImplementation(
    (opts) => nonNull(nonNull(opts).select)({ location: { search } } as never) as never,
  );
  return mockNavigate;
}

const DEFAULT_OPTIONS: { readonly route: '/profiles'; readonly defaultSort: 'name' | 'keywords' } =
  { route: '/profiles', defaultSort: 'name' };

describe('useUrlListState - state extraction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('returns defaults when URL has no search params', () => {
    setupMocks({});
    const { result } = renderHook(() => useUrlListState(DEFAULT_OPTIONS));
    expect(result.current.page).toBe(1);
    expect(result.current.sortField).toBe('name');
    expect(result.current.sortDirection).toBe('asc');
  });

  test('reads page, sort, dir from URL search params', () => {
    setupMocks({ page: 2, sort: 'keywords', dir: 'desc' });
    const { result } = renderHook(() => useUrlListState(DEFAULT_OPTIONS));
    expect(result.current.page).toBe(2);
    expect(result.current.sortField).toBe('keywords');
    expect(result.current.sortDirection).toBe('desc');
  });

  test('ignores non-matching types in search state', () => {
    setupMocks({ page: 'not-a-number', sort: 42, dir: 'sideways' });
    const { result } = renderHook(() => useUrlListState(DEFAULT_OPTIONS));
    expect(result.current.page).toBe(1);
    expect(result.current.sortField).toBe('name');
    expect(result.current.sortDirection).toBe('asc');
  });

  test('uses custom defaultDirection when provided', () => {
    setupMocks({});
    const { result } = renderHook(() =>
      useUrlListState({ route: '/jobs', defaultSort: 'posted_at', defaultDirection: 'desc' }),
    );
    expect(result.current.sortDirection).toBe('desc');
  });
});

describe('useUrlListState - navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('setPage navigates preserving sort params', () => {
    const mockNavigate = setupMocks({ sort: 'keywords', dir: 'desc' });
    const { result } = renderHook(() => useUrlListState(DEFAULT_OPTIONS));
    result.current.setPage(TEST_PAGE);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/profiles',
      search: { page: TEST_PAGE, sort: 'keywords', dir: 'desc' },
    });
  });

  test('setSortField resets page to 1', () => {
    const mockNavigate = setupMocks({ page: 5, sort: 'name', dir: 'asc' });
    const { result } = renderHook(() => useUrlListState(DEFAULT_OPTIONS));
    result.current.setSortField('keywords');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/profiles',
      search: { page: 1, sort: 'keywords', dir: 'asc' },
    });
  });

  test('setSortDirection resets page to 1', () => {
    const mockNavigate = setupMocks({ page: 5, sort: 'name', dir: 'asc' });
    const { result } = renderHook(() => useUrlListState(DEFAULT_OPTIONS));
    result.current.setSortDirection('desc');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/profiles',
      search: { page: 1, sort: 'name', dir: 'desc' },
    });
  });

  test('navigates to the configured route', () => {
    const mockNavigate = setupMocks({});
    const { result } = renderHook(() =>
      useUrlListState({ route: '/attachments', defaultSort: 'name' }),
    );
    result.current.setPage(2);
    expect(mockNavigate).toHaveBeenCalledWith(expect.objectContaining({ to: '/attachments' }));
  });
});
