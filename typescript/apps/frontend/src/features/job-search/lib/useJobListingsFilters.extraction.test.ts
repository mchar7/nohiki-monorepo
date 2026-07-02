import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';

const TEST_PAGE_NUMBER: number = 3;

vi.mock('@tanstack/react-router', () => ({
  useRouter: vi.fn(),
  useRouterState: vi.fn(),
}));

import { useRouter, useRouterState } from '@tanstack/react-router';

import { useJobListingsFilters } from './useJobListingsFilters.ts';

const mockUseRouter = vi.mocked(useRouter);
const mockUseRouterState = vi.mocked(useRouterState);

function setupMocks(search: Record<string, unknown>): ReturnType<typeof vi.fn> {
  const mockNavigate = vi.fn();
  mockUseRouter.mockReturnValue({ navigate: mockNavigate } as never);
  mockUseRouterState.mockImplementation(
    (opts) => opts?.select?.({ location: { search } } as never) as never,
  );
  return mockNavigate;
}

describe('useJobListingsFilters - core filter extraction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('extracts typed search params via the select function', () => {
    setupMocks({ page: 1 });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters).toEqual({
      page: 1,
      sort: 'posted_at',
      dir: 'desc',
      source: null,
      company: null,
      q: null,
      showDismissed: false,
      workArrangement: null,
      seniority: null,
      dateRange: null,
      hasSalary: false,
    });
  });

  test('extracts page from search params', () => {
    setupMocks({ page: TEST_PAGE_NUMBER });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.page).toBe(TEST_PAGE_NUMBER);
  });

  test('extracts source from search params', () => {
    setupMocks({ page: 1, source: 'linkedin' });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.source).toBe('linkedin');
  });

  test('extracts company from search params', () => {
    setupMocks({ page: 1, company: 'Acme' });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.company).toBe('Acme');
  });

  test('extracts query from search params', () => {
    setupMocks({ page: 1, q: 'python' });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.q).toBe('python');
  });
});

describe('useJobListingsFilters - boolean and option filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('extracts showDismissed from search params', () => {
    setupMocks({ page: 1, showDismissed: true });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.showDismissed).toBe(true);
  });

  test('extracts workArrangement from search params', () => {
    setupMocks({ page: 1, workArrangement: 'remote' });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.workArrangement).toBe('remote');
  });

  test('extracts seniority from search params', () => {
    setupMocks({ page: 1, seniority: 'senior' });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.seniority).toBe('senior');
  });

  test('extracts dateRange from search params', () => {
    setupMocks({ page: 1, dateRange: '7d' });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.dateRange).toBe('7d');
  });

  test('extracts hasSalary from search params', () => {
    setupMocks({ page: 1, hasSalary: true });
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.hasSalary).toBe(true);
  });
});

describe('useJobListingsFilters - default values', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('defaults page to 1 when not provided', () => {
    setupMocks({});
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.page).toBe(1);
  });

  test('defaults sort to posted_at when not provided', () => {
    setupMocks({});
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.sort).toBe('posted_at');
  });

  test('defaults dir to desc when not provided', () => {
    setupMocks({});
    const { result } = renderHook(() => useJobListingsFilters());
    expect(result.current.filters.dir).toBe('desc');
  });
});
