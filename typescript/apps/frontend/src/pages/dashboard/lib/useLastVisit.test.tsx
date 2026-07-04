import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { useLastVisit } from './useLastVisit.ts';

const STORAGE_KEY = 'nohiki_dashboard_last_visit';

function setupSpies(): {
  getItemSpy: ReturnType<typeof vi.spyOn>;
  setItemSpy: ReturnType<typeof vi.spyOn>;
} {
  const getItemSpy = vi.spyOn(Storage.prototype, 'getItem');
  const setItemSpy = vi.spyOn(Storage.prototype, 'setItem');
  localStorage.clear();
  return { getItemSpy, setItemSpy };
}

describe('useLastVisit: timestamp tracking', () => {
  let getItemSpy: ReturnType<typeof vi.spyOn>;
  let setItemSpy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    ({ getItemSpy, setItemSpy } = setupSpies());
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });
  test('returns null lastVisit on first visit', () => {
    getItemSpy.mockReturnValue(null);
    const { result } = renderHook(() => useLastVisit());
    expect(result.current.lastVisit).toBeNull();
    expect(setItemSpy).toHaveBeenCalledWith(STORAGE_KEY, expect.any(String));
  });
  test('returns previous timestamp on subsequent visit', () => {
    const previousVisit = '2025-01-15T10:00:00.000Z';
    getItemSpy.mockReturnValue(previousVisit);
    const { result } = renderHook(() => useLastVisit());
    expect(result.current.lastVisit).toEqual(new Date(previousVisit));
    expect(setItemSpy).toHaveBeenCalledWith(STORAGE_KEY, expect.any(String));
  });
  test('handles invalid localStorage value gracefully', () => {
    getItemSpy.mockReturnValue('not-a-valid-date');
    const { result } = renderHook(() => useLastVisit());
    expect(result.current.lastVisit).toBeNull();
    expect(setItemSpy).toHaveBeenCalledWith(STORAGE_KEY, expect.any(String));
  });
  test('handles localStorage read throwing an error', () => {
    getItemSpy.mockImplementation(() => {
      throw new Error('SecurityError');
    });
    const { result } = renderHook(() => useLastVisit());
    expect(result.current.lastVisit).toBeNull();
  });
  test('handles localStorage write throwing an error without crashing', () => {
    getItemSpy.mockReturnValue('2025-01-15T10:00:00.000Z');
    setItemSpy.mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    const { result } = renderHook(() => useLastVisit());
    expect(result.current.lastVisit).toEqual(new Date('2025-01-15T10:00:00.000Z'));
  });
});

describe('useLastVisit: newSinceLastVisit', () => {
  let getItemSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    ({ getItemSpy } = setupSpies());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test('counts items created after lastVisit correctly', () => {
    const previousVisit = '2025-01-15T10:00:00.000Z';
    getItemSpy.mockReturnValue(previousVisit);

    const items = [
      { created_at: '2025-01-14T08:00:00.000Z' }, // before
      { created_at: '2025-01-15T12:00:00.000Z' }, // after
      { created_at: '2025-01-16T09:00:00.000Z' }, // after
      { created_at: '2025-01-15T10:00:00.000Z' }, // exact same time, not counted
    ];

    const { result } = renderHook(() => useLastVisit());

    expect(result.current.newSinceLastVisit(items)).toBe(2);
  });

  test('returns 0 when lastVisit is null', () => {
    getItemSpy.mockReturnValue(null);

    const items = [
      { created_at: '2025-01-16T09:00:00.000Z' },
      { created_at: '2025-01-17T09:00:00.000Z' },
    ];

    const { result } = renderHook(() => useLastVisit());

    expect(result.current.newSinceLastVisit(items)).toBe(0);
  });

  test('returns 0 for empty items array with a valid lastVisit', () => {
    getItemSpy.mockReturnValue('2025-01-15T10:00:00.000Z');

    const { result } = renderHook(() => useLastVisit());

    expect(result.current.newSinceLastVisit([])).toBe(0);
  });
});
