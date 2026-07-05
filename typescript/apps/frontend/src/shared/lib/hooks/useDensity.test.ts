import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect } from 'vitest';
import { useAppStore } from '@/shared/model/appStore.ts';
import { DENSITY_CLASSES, useDensity } from './useDensity.ts';

afterEach(() => {
  useAppStore.setState({ density: 'comfortable' });
});

describe('useDensity - initial state', () => {
  test('returns comfortable density by default', () => {
    const { result } = renderHook(() => useDensity());
    expect(result.current.density).toBe('comfortable');
  });

  test('returns the DENSITY_CLASSES entry for the current density', () => {
    const { result } = renderHook(() => useDensity());
    expect(result.current.classes).toEqual(DENSITY_CLASSES.comfortable);
  });
});

describe('useDensity - setDensity', () => {
  test('updates density to compact', () => {
    const { result } = renderHook(() => useDensity());
    act(() => {
      result.current.setDensity('compact');
    });
    expect(result.current.density).toBe('compact');
    expect(result.current.classes).toEqual(DENSITY_CLASSES.compact);
  });

  test('updates density to spacious', () => {
    const { result } = renderHook(() => useDensity());
    act(() => {
      result.current.setDensity('spacious');
    });
    expect(result.current.density).toBe('spacious');
    expect(result.current.classes).toEqual(DENSITY_CLASSES.spacious);
  });

  test('updates density back to comfortable', () => {
    const { result } = renderHook(() => useDensity());
    act(() => {
      result.current.setDensity('compact');
    });
    act(() => {
      result.current.setDensity('comfortable');
    });
    expect(result.current.density).toBe('comfortable');
  });
});

describe('useDensity - pick helper', () => {
  test('returns compact value when density is compact', () => {
    const { result } = renderHook(() => useDensity());
    act(() => {
      result.current.setDensity('compact');
    });
    expect(result.current.pick('small', 'medium', 'large')).toBe('small');
  });

  test('returns comfortable value when density is comfortable', () => {
    const { result } = renderHook(() => useDensity());
    expect(result.current.pick('small', 'medium', 'large')).toBe('medium');
  });

  test('returns spacious value when density is spacious', () => {
    const { result } = renderHook(() => useDensity());
    act(() => {
      result.current.setDensity('spacious');
    });
    expect(result.current.pick('small', 'medium', 'large')).toBe('large');
  });

  test('works with non-string values', () => {
    const COMPACT_VALUE = 1;
    const COMFORTABLE_VALUE = 2;
    const SPACIOUS_VALUE = 3;
    const { result } = renderHook(() => useDensity());
    act(() => {
      result.current.setDensity('compact');
    });
    expect(result.current.pick(COMPACT_VALUE, COMFORTABLE_VALUE, SPACIOUS_VALUE)).toBe(
      COMPACT_VALUE,
    );
  });
});

describe('DENSITY_CLASSES constant', () => {
  test('has entries for all three density levels', () => {
    expect(DENSITY_CLASSES).toHaveProperty('compact');
    expect(DENSITY_CLASSES).toHaveProperty('comfortable');
    expect(DENSITY_CLASSES).toHaveProperty('spacious');
  });

  test('each entry has gap, padding, and text keys', () => {
    for (const classes of Object.values(DENSITY_CLASSES)) {
      expect(classes).toHaveProperty('gap');
      expect(classes).toHaveProperty('padding');
      expect(classes).toHaveProperty('text');
    }
  });
});
