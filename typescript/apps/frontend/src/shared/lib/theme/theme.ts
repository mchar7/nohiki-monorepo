import { config } from '@shared/config/index.ts';

export const THEME_COLORS = {
  emerald: {
    nameKey: 'appearance.colorScheme.emerald',
    descriptionKey: 'appearance.colorScheme.emeraldDescription',
    cssClass: 'theme-emerald',
    previewColor: 'oklch(0.498 0.154 160.62)',
  },
  blue: {
    nameKey: 'appearance.colorScheme.blue',
    descriptionKey: 'appearance.colorScheme.blueDescription',
    cssClass: 'theme-blue',
    previewColor: 'oklch(0.546 0.245 262.881)',
  },
  violet: {
    nameKey: 'appearance.colorScheme.violet',
    descriptionKey: 'appearance.colorScheme.violetDescription',
    cssClass: 'theme-violet',
    previewColor: 'oklch(0.606 0.25 292.717)',
  },
  rose: {
    nameKey: 'appearance.colorScheme.rose',
    descriptionKey: 'appearance.colorScheme.roseDescription',
    cssClass: 'theme-rose',
    previewColor: 'oklch(0.586 0.225 17.383)',
  },
  orange: {
    nameKey: 'appearance.colorScheme.orange',
    descriptionKey: 'appearance.colorScheme.orangeDescription',
    cssClass: 'theme-orange',
    previewColor: 'oklch(0.646 0.222 41.116)',
  },
} as const;

export type ThemeColor = keyof typeof THEME_COLORS;

export const DEFAULT_THEME_COLOR: ThemeColor = 'emerald';

export const THEME_COLOR_STORAGE_KEY = `${config.storage.keys.theme}-color`;
export const SYSTEM_THEME_STORAGE_KEY = `${config.storage.keys.theme}-system`;

export function getStoredThemeColor(): ThemeColor {
  if (globalThis.window === undefined) {
    return DEFAULT_THEME_COLOR;
  }

  const stored = localStorage.getItem(THEME_COLOR_STORAGE_KEY);
  if (stored && stored in THEME_COLORS) {
    return stored as ThemeColor;
  }
  return DEFAULT_THEME_COLOR;
}

export function setStoredThemeColor(color: ThemeColor): void {
  if (globalThis.window === undefined) {
    return;
  }
  localStorage.setItem(THEME_COLOR_STORAGE_KEY, color);
}

export function getUseSystemTheme(): boolean {
  if (globalThis.window === undefined) {
    return false;
  }
  return localStorage.getItem(SYSTEM_THEME_STORAGE_KEY) === 'true';
}

export function setUseSystemTheme(useSystem: boolean): void {
  if (globalThis.window === undefined) {
    return;
  }
  localStorage.setItem(SYSTEM_THEME_STORAGE_KEY, useSystem ? 'true' : 'false');
}

export function getSystemPreferredTheme(): ThemeColor {
  if (globalThis.window === undefined) {
    return DEFAULT_THEME_COLOR;
  }

  // This is a simplified system theme detection
  // In a real app, you might detect based on system accent color
  // For now, we'll use emerald as the system default
  return DEFAULT_THEME_COLOR;
}

export function applyThemeColor(color: ThemeColor, withTransition: boolean = true): void {
  if (globalThis.window === undefined) {
    return;
  }

  const root = document.documentElement;

  // Add transition class for smooth color changes
  if (withTransition) {
    root.classList.add('theme-transitioning');
  }

  // Remove all theme classes
  for (const { cssClass } of Object.values(THEME_COLORS)) {
    root.classList.remove(cssClass);
  }

  // Add the selected theme class
  root.classList.add(THEME_COLORS[color].cssClass);

  // Store the preference
  setStoredThemeColor(color);

  // Remove transition class after animation completes
  if (withTransition) {
    setTimeout(() => {
      root.classList.remove('theme-transitioning');
    }, config.ui.modalAnimationDuration);
  }
}

// Enhanced API for external services (e.g., Playwright tests)
export const themeService = {
  getCurrentTheme(): ThemeColor {
    return getStoredThemeColor();
  },

  setTheme(color: ThemeColor, withTransition: boolean = true): void {
    applyThemeColor(color, withTransition);
  },

  getAvailableThemes(): typeof THEME_COLORS {
    return THEME_COLORS;
  },

  isSystemThemeEnabled(): boolean {
    return getUseSystemTheme();
  },

  enableSystemTheme(): void {
    setUseSystemTheme(true);
    const systemTheme = getSystemPreferredTheme();
    applyThemeColor(systemTheme);
  },

  disableSystemTheme(): void {
    setUseSystemTheme(false);
  },

  // For testing purposes - apply theme without transition
  setThemeImmediate(color: ThemeColor): void {
    applyThemeColor(color, false);
  },
};

export { ThemeProvider } from './theme-provider.tsx';
export { useTheme } from './use-theme.ts';
