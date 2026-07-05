import { afterEach, beforeEach, describe, expect, vi } from 'vitest';

/** Theme transition animation duration used in applyThemeColor (ms) */
const THEME_TRANSITION_DURATION_MS: number = 300;

import {
  applyThemeColor,
  DEFAULT_THEME_COLOR,
  getStoredThemeColor,
  getSystemPreferredTheme,
  getUseSystemTheme,
  SYSTEM_THEME_STORAGE_KEY,
  setStoredThemeColor,
  setUseSystemTheme,
  THEME_COLOR_STORAGE_KEY,
  THEME_COLORS,
  type ThemeColor,
  themeService,
} from './theme.ts';

// Mock localStorage
const mockLocalStorage: {
  getItem: ReturnType<typeof vi.fn>;
  setItem: ReturnType<typeof vi.fn>;
  removeItem: ReturnType<typeof vi.fn>;
  clear: ReturnType<typeof vi.fn>;
} = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
};

Object.defineProperty(globalThis, 'localStorage', {
  value: mockLocalStorage,
});

// Mock document.documentElement
const mockClassList: {
  add: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
  contains: ReturnType<typeof vi.fn>;
} = {
  add: vi.fn(),
  remove: vi.fn(),
  contains: vi.fn(),
};

Object.defineProperty(document, 'documentElement', {
  value: {
    classList: mockClassList,
  },
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.clearAllTimers();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('Theme Library - Constants', () => {
  test('has correct default theme', () => {
    expect(DEFAULT_THEME_COLOR).toBe('emerald');
  });

  test('has all required theme colors', () => {
    const expectedThemes = ['emerald', 'blue', 'violet', 'rose', 'orange'];
    const actualThemes = Object.keys(THEME_COLORS);

    expect(actualThemes).toEqual(expectedThemes);
  });

  test('has proper theme configuration structure', () => {
    for (const [key, config] of Object.entries(THEME_COLORS)) {
      expect(config).toHaveProperty('nameKey');
      expect(config).toHaveProperty('descriptionKey');
      expect(config).toHaveProperty('cssClass');
      expect(config).toHaveProperty('previewColor');
      expect(config.cssClass).toBe(`theme-${key}`);
      expect(typeof config.nameKey).toBe('string');
      expect(typeof config.descriptionKey).toBe('string');
      expect(typeof config.previewColor).toBe('string');
    }
  });
});

describe('Theme Library - getStoredThemeColor', () => {
  test('returns stored theme color when valid', () => {
    mockLocalStorage.getItem.mockReturnValue('blue');
    expect(getStoredThemeColor()).toBe('blue');
    expect(mockLocalStorage.getItem).toHaveBeenCalledWith(THEME_COLOR_STORAGE_KEY);
  });

  test('returns default theme when stored value is invalid', () => {
    mockLocalStorage.getItem.mockReturnValue('invalid-theme');
    expect(getStoredThemeColor()).toBe(DEFAULT_THEME_COLOR);
  });

  test('returns default theme when nothing is stored', () => {
    mockLocalStorage.getItem.mockReturnValue(null);
    expect(getStoredThemeColor()).toBe(DEFAULT_THEME_COLOR);
  });
});

describe('Theme Library - setStoredThemeColor', () => {
  test('stores theme color in localStorage', () => {
    setStoredThemeColor('violet');
    expect(mockLocalStorage.setItem).toHaveBeenCalledWith(THEME_COLOR_STORAGE_KEY, 'violet');
  });
});

describe('Theme Library - getUseSystemTheme', () => {
  test('returns true when system theme is enabled', () => {
    mockLocalStorage.getItem.mockReturnValue('true');
    expect(getUseSystemTheme()).toBe(true);
    expect(mockLocalStorage.getItem).toHaveBeenCalledWith(SYSTEM_THEME_STORAGE_KEY);
  });

  test('returns false when system theme is disabled', () => {
    mockLocalStorage.getItem.mockReturnValue('false');
    expect(getUseSystemTheme()).toBe(false);
  });

  test('returns false when nothing is stored', () => {
    mockLocalStorage.getItem.mockReturnValue(null);
    expect(getUseSystemTheme()).toBe(false);
  });
});

describe('Theme Library - setUseSystemTheme', () => {
  test('stores true when enabled', () => {
    setUseSystemTheme(true);
    expect(mockLocalStorage.setItem).toHaveBeenCalledWith(SYSTEM_THEME_STORAGE_KEY, 'true');
  });

  test('stores false when disabled', () => {
    setUseSystemTheme(false);
    expect(mockLocalStorage.setItem).toHaveBeenCalledWith(SYSTEM_THEME_STORAGE_KEY, 'false');
  });
});

describe('Theme Library - System Theme Detection', () => {
  test('returns default theme for system preference', () => {
    expect(getSystemPreferredTheme()).toBe(DEFAULT_THEME_COLOR);
  });
});

describe('Theme Library - applyThemeColor', () => {
  test('removes all theme classes and adds selected theme', () => {
    applyThemeColor('blue', false);

    // Should remove all theme classes
    for (const { cssClass } of Object.values(THEME_COLORS)) {
      expect(mockClassList.remove).toHaveBeenCalledWith(cssClass);
    }

    // Should add selected theme class
    expect(mockClassList.add).toHaveBeenCalledWith('theme-blue');

    // Should store the preference
    expect(mockLocalStorage.setItem).toHaveBeenCalledWith(THEME_COLOR_STORAGE_KEY, 'blue');
  });

  test('adds transition class when withTransition is true', () => {
    applyThemeColor('rose', true);

    expect(mockClassList.add).toHaveBeenCalledWith('theme-transitioning');
    expect(mockClassList.add).toHaveBeenCalledWith('theme-rose');
  });

  test('removes transition class after timeout when withTransition is true', () => {
    applyThemeColor('orange', true);

    expect(mockClassList.add).toHaveBeenCalledWith('theme-transitioning');

    // Fast-forward time
    vi.advanceTimersByTime(THEME_TRANSITION_DURATION_MS);

    expect(mockClassList.remove).toHaveBeenCalledWith('theme-transitioning');
  });

  test('does not add transition class when withTransition is false', () => {
    applyThemeColor('violet', false);

    expect(mockClassList.add).not.toHaveBeenCalledWith('theme-transitioning');
    expect(mockClassList.add).toHaveBeenCalledWith('theme-violet');
  });
});

describe('Theme Library - themeService getCurrentTheme', () => {
  test('returns current stored theme', () => {
    mockLocalStorage.getItem.mockReturnValue('blue');
    expect(themeService.getCurrentTheme()).toBe('blue');
  });
});

describe('Theme Library - themeService setTheme', () => {
  test('applies theme with transition by default', () => {
    themeService.setTheme('rose');

    expect(mockClassList.add).toHaveBeenCalledWith('theme-transitioning');
    expect(mockClassList.add).toHaveBeenCalledWith('theme-rose');
  });

  test('applies theme without transition when specified', () => {
    themeService.setTheme('orange', false);

    expect(mockClassList.add).not.toHaveBeenCalledWith('theme-transitioning');
    expect(mockClassList.add).toHaveBeenCalledWith('theme-orange');
  });
});

describe('Theme Library - themeService setThemeImmediate', () => {
  test('applies theme without transition', () => {
    themeService.setThemeImmediate('violet');

    expect(mockClassList.add).not.toHaveBeenCalledWith('theme-transitioning');
    expect(mockClassList.add).toHaveBeenCalledWith('theme-violet');
  });
});

describe('Theme Library - themeService getAvailableThemes', () => {
  test('returns all theme colors', () => {
    expect(themeService.getAvailableThemes()).toBe(THEME_COLORS);
  });
});

describe('Theme Library - themeService system theme methods', () => {
  test('detects system theme state', () => {
    mockLocalStorage.getItem.mockReturnValue('true');
    expect(themeService.isSystemThemeEnabled()).toBe(true);

    mockLocalStorage.getItem.mockReturnValue('false');
    expect(themeService.isSystemThemeEnabled()).toBe(false);
  });

  test('enables system theme', () => {
    themeService.enableSystemTheme();

    expect(mockLocalStorage.setItem).toHaveBeenCalledWith(SYSTEM_THEME_STORAGE_KEY, 'true');
    expect(mockClassList.add).toHaveBeenCalledWith(`theme-${DEFAULT_THEME_COLOR}`);
  });

  test('disables system theme', () => {
    themeService.disableSystemTheme();

    expect(mockLocalStorage.setItem).toHaveBeenCalledWith(SYSTEM_THEME_STORAGE_KEY, 'false');
  });
});

describe('Theme Library - Type Safety', () => {
  test('only accepts valid theme colors', () => {
    const validThemes: ThemeColor[] = ['emerald', 'blue', 'violet', 'rose', 'orange'];

    for (const theme of validThemes) {
      expect(() => applyThemeColor(theme)).not.toThrow();
    }
  });
});
