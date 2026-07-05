import { act, render, renderHook, screen } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { ThemeProvider } from './theme-provider.tsx';
import { useTheme } from './use-theme.ts';

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  document.documentElement.classList.remove('light', 'dark');
});

describe('ThemeProvider - initial state', () => {
  test('has a valid theme value', () => {
    const wrapper = ({ children }: { children: ReactNode }): JSX.Element => (
      <ThemeProvider>{children}</ThemeProvider>
    );

    const { result } = renderHook(() => useTheme(), { wrapper });

    expect(['light', 'dark', 'system']).toContain(result.current.theme);
  });

  test('has a resolved theme that is light or dark', () => {
    const wrapper = ({ children }: { children: ReactNode }): JSX.Element => (
      <ThemeProvider>{children}</ThemeProvider>
    );

    const { result } = renderHook(() => useTheme(), { wrapper });

    expect(['light', 'dark']).toContain(result.current.resolvedTheme);
  });
});

describe('ThemeProvider - setTheme', () => {
  test('updates theme and saves to localStorage', () => {
    const wrapper = ({ children }: { children: ReactNode }): JSX.Element => (
      <ThemeProvider>{children}</ThemeProvider>
    );

    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => {
      result.current.setTheme('dark');
    });

    expect(result.current.theme).toBe('dark');
    expect(localStorage.getItem('vite-ui-theme')).toBe('dark');
  });

  test('uses custom storage key when provided', () => {
    const wrapper = ({ children }: { children: ReactNode }): JSX.Element => (
      <ThemeProvider storageKey="custom-theme">{children}</ThemeProvider>
    );

    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => {
      result.current.setTheme('light');
    });

    expect(localStorage.getItem('custom-theme')).toBe('light');
  });
});

describe('ThemeProvider - resolvedTheme', () => {
  test('resolves to light when theme is light', () => {
    const wrapper = ({ children }: { children: ReactNode }): JSX.Element => (
      <ThemeProvider defaultTheme="light">{children}</ThemeProvider>
    );

    const { result } = renderHook(() => useTheme(), { wrapper });

    expect(result.current.resolvedTheme).toBe('light');
  });

  test('resolves to dark when theme is dark', () => {
    localStorage.setItem('vite-ui-theme', 'dark');

    const wrapper = ({ children }: { children: ReactNode }): JSX.Element => (
      <ThemeProvider>{children}</ThemeProvider>
    );

    const { result } = renderHook(() => useTheme(), { wrapper });

    expect(result.current.resolvedTheme).toBe('dark');
  });
});

describe('ThemeProvider - document class updates', () => {
  test('adds theme class to document root', () => {
    localStorage.setItem('vite-ui-theme', 'dark');

    const wrapper = ({ children }: { children: ReactNode }): JSX.Element => (
      <ThemeProvider>{children}</ThemeProvider>
    );

    renderHook(() => useTheme(), { wrapper });

    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  test('removes previous theme class when theme changes', () => {
    localStorage.setItem('vite-ui-theme', 'light');

    const wrapper = ({ children }: { children: ReactNode }): JSX.Element => (
      <ThemeProvider>{children}</ThemeProvider>
    );

    const { result } = renderHook(() => useTheme(), { wrapper });

    expect(document.documentElement.classList.contains('light')).toBe(true);

    act(() => {
      result.current.setTheme('dark');
    });

    expect(document.documentElement.classList.contains('light')).toBe(false);
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });
});

describe('ThemeProvider - children rendering', () => {
  test('renders children correctly', () => {
    render(
      <ThemeProvider>
        <div data-testid="child">Child Content</div>
      </ThemeProvider>,
    );

    expect(screen.getByTestId('child')).toBeInTheDocument();
  });
});

describe('useTheme', () => {
  test('throws error when used outside ThemeProvider', () => {
    expect(() => {
      renderHook(() => useTheme());
    }).toThrow('useTheme must be used within a ThemeProvider');
  });
});
