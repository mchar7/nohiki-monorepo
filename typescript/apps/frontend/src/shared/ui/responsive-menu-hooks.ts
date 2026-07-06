import { useContext } from 'react';
import {
  ResponsiveMenuContext,
  type ResponsiveMenuContextValue,
} from './responsive-menu-context.ts';

function useResponsiveMenuContext(): ResponsiveMenuContextValue {
  const ctx = useContext(ResponsiveMenuContext);
  if (!ctx) {
    throw new Error('useResponsiveMenuContext must be used inside ResponsiveMenu');
  }
  return ctx;
}

export { useResponsiveMenuContext };
