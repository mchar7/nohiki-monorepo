import { type Context, createContext } from 'react';

type Theme = 'light' | 'dark' | 'system';

interface ThemeContextValue {
  theme: Theme;
  resolvedTheme: 'light' | 'dark';
  setTheme: (theme: Theme) => void;
}

const ThemeContext: Context<ThemeContextValue | null> = createContext<ThemeContextValue | null>(
  null,
);

export type { Theme, ThemeContextValue };
export { ThemeContext };
