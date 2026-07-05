import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useThemeColor } from './useThemeColor.ts';

// Mock the theme library at the path useThemeColor.ts imports from
vi.mock('../theme/theme.ts', () => ({
  DEFAULT_THEME_COLOR: 'emerald',
  getStoredThemeColor: vi.fn(),
  getUseSystemTheme: vi.fn(),
  setUseSystemTheme: vi.fn(),
  getSystemPreferredTheme: vi.fn(),
  applyThemeColor: vi.fn(),
}));

import {
  applyThemeColor,
  getStoredThemeColor,
  getSystemPreferredTheme,
  getUseSystemTheme,
  setUseSystemTheme,
} from '../theme/theme.ts';

const mockGetStoredThemeColor = vi.mocked(getStoredThemeColor);
const mockGetUseSystemTheme = vi.mocked(getUseSystemTheme);
const mockSetUseSystemTheme = vi.mocked(setUseSystemTheme);
const mockGetSystemPreferredTheme = vi.mocked(getSystemPreferredTheme);
const mockApplyThemeColor = vi.mocked(applyThemeColor);

beforeEach(() => {
  vi.clearAllMocks();

  // Default mock implementations
  mockGetStoredThemeColor.mockReturnValue('emerald');
  mockGetUseSystemTheme.mockReturnValue(false);
  mockGetSystemPreferredTheme.mockReturnValue('emerald');
});

describe('useThemeColor - Initialization', () => {
  test('initializes with stored theme color and system preference', () => {
    mockGetStoredThemeColor.mockReturnValue('blue');
    mockGetUseSystemTheme.mockReturnValue(false);

    const { result } = renderHook(() => useThemeColor());

    expect(result.current.themeColor).toBe('blue');
    expect(result.current.useSystemTheme).toBe(false);
    expect(mockGetStoredThemeColor).toHaveBeenCalled();
    expect(mockGetUseSystemTheme).toHaveBeenCalled();
  });

  test('uses system theme when system preference is enabled', () => {
    mockGetStoredThemeColor.mockReturnValue('blue');
    mockGetUseSystemTheme.mockReturnValue(true);
    mockGetSystemPreferredTheme.mockReturnValue('emerald');

    const { result } = renderHook(() => useThemeColor());

    expect(result.current.useSystemTheme).toBe(true);
    expect(result.current.themeColor).toBe('emerald');
  });

  test('calls storage functions to get initial state', () => {
    mockGetStoredThemeColor.mockReturnValue('violet');
    mockGetUseSystemTheme.mockReturnValue(false);

    renderHook(() => useThemeColor());

    expect(mockGetStoredThemeColor).toHaveBeenCalled();
    expect(mockGetUseSystemTheme).toHaveBeenCalled();
  });
});

describe('useThemeColor - setThemeColor', () => {
  test('updates theme color and applies with transition', () => {
    const { result } = renderHook(() => useThemeColor());

    act(() => {
      result.current.setThemeColor('rose');
    });

    expect(result.current.themeColor).toBe('rose');
    expect(result.current.useSystemTheme).toBe(false);
    expect(mockSetUseSystemTheme).toHaveBeenCalledWith(false);
    expect(mockApplyThemeColor).toHaveBeenCalledWith('rose', true);
  });

  test('disables system theme when setting manual theme', () => {
    mockGetUseSystemTheme.mockReturnValue(true);
    const { result } = renderHook(() => useThemeColor());

    expect(result.current.useSystemTheme).toBe(true);

    act(() => {
      result.current.setThemeColor('orange');
    });

    expect(result.current.useSystemTheme).toBe(false);
    expect(mockSetUseSystemTheme).toHaveBeenCalledWith(false);
  });
});

describe('useThemeColor - setUseSystemTheme', () => {
  test('enables system theme and applies system preference', () => {
    mockGetSystemPreferredTheme.mockReturnValue('blue');
    const { result } = renderHook(() => useThemeColor());

    act(() => {
      result.current.setUseSystemTheme(true);
    });

    expect(result.current.useSystemTheme).toBe(true);
    expect(result.current.themeColor).toBe('blue');
    expect(mockSetUseSystemTheme).toHaveBeenCalledWith(true);
    expect(mockApplyThemeColor).toHaveBeenCalledWith('blue', true);
  });

  test('disables system theme when set to false', () => {
    const { result } = renderHook(() => useThemeColor());

    act(() => {
      result.current.setUseSystemTheme(false);
    });

    expect(result.current.useSystemTheme).toBe(false);
    expect(mockSetUseSystemTheme).toHaveBeenCalledWith(false);
  });

  test('applies theme with transition for user interactions', () => {
    mockGetSystemPreferredTheme.mockReturnValue('violet');
    const { result } = renderHook(() => useThemeColor());

    act(() => {
      result.current.setUseSystemTheme(true);
    });

    expect(mockApplyThemeColor).toHaveBeenCalledWith('violet', true);
  });
});

describe('useThemeColor - State Management', () => {
  test('maintains state consistency across multiple operations', () => {
    const { result } = renderHook(() => useThemeColor());

    // Set manual theme
    act(() => {
      result.current.setThemeColor('blue');
    });

    expect(result.current.themeColor).toBe('blue');
    expect(result.current.useSystemTheme).toBe(false);

    // Enable system theme
    mockGetSystemPreferredTheme.mockReturnValue('rose');
    act(() => {
      result.current.setUseSystemTheme(true);
    });

    expect(result.current.themeColor).toBe('rose');
    expect(result.current.useSystemTheme).toBe(true);

    // Set manual theme again
    act(() => {
      result.current.setThemeColor('orange');
    });

    expect(result.current.themeColor).toBe('orange');
    expect(result.current.useSystemTheme).toBe(false);
  });
});

describe('useThemeColor - Integration with Theme Library', () => {
  test('calls theme library functions with correct parameters', () => {
    const { result } = renderHook(() => useThemeColor());

    // Verify initialization calls
    expect(mockGetStoredThemeColor).toHaveBeenCalled();
    expect(mockGetUseSystemTheme).toHaveBeenCalled();

    // Test setThemeColor
    act(() => {
      result.current.setThemeColor('violet');
    });

    expect(mockSetUseSystemTheme).toHaveBeenCalledWith(false);
    expect(mockApplyThemeColor).toHaveBeenCalledWith('violet', true);

    // Test setUseSystemTheme
    act(() => {
      result.current.setUseSystemTheme(true);
    });

    expect(mockSetUseSystemTheme).toHaveBeenCalledWith(true);
    expect(mockGetSystemPreferredTheme).toHaveBeenCalled();
  });
});
