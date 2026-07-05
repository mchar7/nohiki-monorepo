import { useContext } from 'react';
import type { ThemeContextValue } from './theme-context.ts';
import { ThemeContext } from './theme-context.ts';

function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}

export { useTheme };
