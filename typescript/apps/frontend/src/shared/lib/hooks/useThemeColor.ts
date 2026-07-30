import { useReducer } from 'react';
import {
  applyThemeColor,
  getStoredThemeColor,
  getSystemPreferredTheme,
  getUseSystemTheme,
  setUseSystemTheme as setStoredUseSystemTheme,
  type ThemeColor,
} from '../theme/theme.ts';

interface ThemeState {
  color: ThemeColor;
  useSystem: boolean;
}

type ThemeAction =
  | { type: 'SET_COLOR'; color: ThemeColor }
  | { type: 'SET_USE_SYSTEM'; useSystem: boolean };

function getInitialState(): ThemeState {
  const shouldUseSystem = getUseSystemTheme();
  const color = shouldUseSystem ? getSystemPreferredTheme() : getStoredThemeColor();
  return { color, useSystem: shouldUseSystem };
}

function themeReducer(state: ThemeState, action: ThemeAction): ThemeState {
  switch (action.type) {
    case 'SET_COLOR':
      return { color: action.color, useSystem: false };
    case 'SET_USE_SYSTEM': {
      const color = action.useSystem ? getSystemPreferredTheme() : state.color;
      return { color, useSystem: action.useSystem };
    }
    default:
      return state;
  }
}

export function useThemeColor(): {
  themeColor: ThemeColor;
  setThemeColor: (color: ThemeColor) => void;
  useSystemTheme: boolean;
  setUseSystemTheme: (shouldUseSystem: boolean) => void;
} {
  const [state, dispatch] = useReducer(themeReducer, undefined, getInitialState);

  const setThemeColor = (color: ThemeColor): void => {
    dispatch({ type: 'SET_COLOR', color });
    setStoredUseSystemTheme(false);
    applyThemeColor(color, true);
  };

  const setUseSystemTheme = (shouldUseSystem: boolean): void => {
    dispatch({ type: 'SET_USE_SYSTEM', useSystem: shouldUseSystem });
    setStoredUseSystemTheme(shouldUseSystem);
    if (shouldUseSystem) {
      const systemColor = getSystemPreferredTheme();
      applyThemeColor(systemColor, true);
    }
  };

  return {
    themeColor: state.color,
    setThemeColor,
    useSystemTheme: state.useSystem,
    setUseSystemTheme,
  };
}
