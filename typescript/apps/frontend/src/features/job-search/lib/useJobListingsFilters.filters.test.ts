import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';

vi.mock('@tanstack/react-router', () => ({
  useRouter: vi.fn(),
  useRouterState: vi.fn(),
}));

import { useRouter, useRouterState } from '@tanstack/react-router';

import { useJobListingsFilters } from './useJobListingsFilters.ts';

const mockUseRouter = vi.mocked(useRouter);
const mockUseRouterState = vi.mocked(useRouterState);

function setupMocks(search: Record<string, unknown>) {
  const mockNavigate = vi.fn(() => Promise.resolve());
  mockUseRouter.mockReturnValue({ navigate: mockNavigate } as never);
  mockUseRouterState.mockImplementation(
    (opts) => opts?.select?.({ location: { search } } as never) as never,
  );
  return mockNavigate;
}

describe('useJobListingsFilters - setCompany, setQuery, clearFilters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('setCompany navigates with company string', () => {
    const mockNavigate = setupMocks({ page: 3 });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setCompany('Acme');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, company: 'Acme' },
    });
  });

  test('setCompany navigates with undefined when passed null', () => {
    const mockNavigate = setupMocks({ page: 3, company: 'Acme' });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setCompany(null);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, company: undefined },
    });
  });

  test('setQuery navigates with q string', () => {
    const mockNavigate = setupMocks({ page: 3 });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setQuery('python developer');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, q: 'python developer' },
    });
  });

  test('setQuery navigates with undefined when passed null', () => {
    const mockNavigate = setupMocks({ page: 3, q: 'python' });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setQuery(null);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, q: undefined },
    });
  });

  test('clearFilters navigates to page 1 discarding all params', () => {
    const mockNavigate = setupMocks({
      page: 3,
      source: 'linkedin',
      company: 'Acme',
      q: 'python',
    });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.clearFilters();
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/jobs', search: { page: 1 } });
  });
});

describe('useJobListingsFilters - setWorkArrangement, setSeniority, setDateRange', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('setWorkArrangement navigates with value', () => {
    const mockNavigate = setupMocks({ page: 3 });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setWorkArrangement('remote');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, workArrangement: 'remote' },
    });
  });

  test('setWorkArrangement navigates with undefined when passed null', () => {
    const mockNavigate = setupMocks({ page: 3, workArrangement: 'remote' });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setWorkArrangement(null);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, workArrangement: undefined },
    });
  });

  test('setSeniority navigates with value', () => {
    const mockNavigate = setupMocks({ page: 3 });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setSeniority('senior');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, seniority: 'senior' },
    });
  });

  test('setDateRange navigates with value', () => {
    const mockNavigate = setupMocks({ page: 3 });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setDateRange('7d');
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, dateRange: '7d' },
    });
  });

  test('setShowDismissed resets page while preserving the filter value', () => {
    const mockNavigate = setupMocks({ page: 4, hasSalary: true });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setShowDismissed(true);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, hasSalary: true, showDismissed: true },
    });
  });

  test('setHasSalary resets page while preserving dismissed state', () => {
    const mockNavigate = setupMocks({ page: 4, showDismissed: true });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.setHasSalary(true);
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/jobs',
      search: { page: 1, showDismissed: true, hasSalary: true },
    });
  });
  test('clearFilters resets all including new filters', () => {
    const mockNavigate = setupMocks({
      page: 2,
      source: 'linkedin',
      workArrangement: 'remote',
      seniority: 'senior',
      dateRange: '7d',
    });
    const { result } = renderHook(() => useJobListingsFilters());
    result.current.clearFilters();
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/jobs', search: { page: 1 } });
  });
});
