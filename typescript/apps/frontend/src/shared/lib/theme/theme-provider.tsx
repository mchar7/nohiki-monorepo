/**
 * Theme provider using CSS class-based theming.
 */

import type { JSX } from 'react';
import { type ReactNode, useEffect, useState } from 'react';
import type { Theme } from './theme-context.ts';
import { ThemeContext } from './theme-context.ts';

const STORAGE_KEY = 'vite-ui-theme';

function getSystemTheme(): 'light' | 'dark' {
  if (typeof globalThis.window === 'undefined') {
    return 'light';
  }
  return globalThis.window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getStoredTheme(): Theme {
  if (typeof globalThis.window === 'undefined') {
    return 'system';
  }
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored;
  }
  return 'system';
}

/** Syncs resolved theme to the document root element. */
function useThemeDocumentSync(
  theme: Theme,
  attribute: string,
  setResolvedTheme: (t: 'light' | 'dark') => void,
): void {
  useEffect(() => {
    const resolved = theme === 'system' ? getSystemTheme() : theme;
    setResolvedTheme(resolved);

    const root = document.documentElement;
    root.classList.remove('light', 'dark');
    if (attribute === 'class') {
      root.classList.add(resolved);
    } else {
      root.setAttribute(attribute, resolved);
    }
  }, [theme, attribute, setResolvedTheme]);
}

/** Listens for system color scheme changes when theme is 'system'. */
function useSystemThemeListener(
  theme: Theme,
  setResolvedTheme: (t: 'light' | 'dark') => void,
): void {
  useEffect(() => {
    if (theme !== 'system') {
      return;
    }

    const mediaQuery = globalThis.window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (): void => {
      const resolved = getSystemTheme();
      setResolvedTheme(resolved);
      document.documentElement.classList.remove('light', 'dark');
      document.documentElement.classList.add(resolved);
    };

    mediaQuery.addEventListener('change', handleChange);
    return (): void => mediaQuery.removeEventListener('change', handleChange);
  }, [theme, setResolvedTheme]);
}

interface ThemeProviderProps {
  readonly children: ReactNode;
  readonly defaultTheme?: Theme;
  readonly storageKey?: string;
  readonly attribute?: string;
}

export function ThemeProvider({
  children,
  defaultTheme = 'system',
  storageKey = STORAGE_KEY,
  attribute = 'class',
}: ThemeProviderProps): JSX.Element {
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof globalThis.window === 'undefined') {
      return defaultTheme;
    }
    return getStoredTheme();
  });

  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() => {
    if (theme === 'system') {
      return getSystemTheme();
    }
    return theme;
  });

  const setTheme = (newTheme: Theme): void => {
    setThemeState(newTheme);
    localStorage.setItem(storageKey, newTheme);
  };

  useThemeDocumentSync(theme, attribute, setResolvedTheme);
  useSystemThemeListener(theme, setResolvedTheme);

  const value = { theme, resolvedTheme, setTheme };

  return <ThemeContext value={value}>{children}</ThemeContext>;
}
