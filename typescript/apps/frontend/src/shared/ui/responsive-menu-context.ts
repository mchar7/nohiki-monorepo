import { createContext } from 'react';

interface ResponsiveMenuContextValue {
  readonly isMobile: boolean;
  readonly close: () => void;
}

const ResponsiveMenuContext = createContext<ResponsiveMenuContextValue | null>(null);

export type { ResponsiveMenuContextValue };
export { ResponsiveMenuContext };
