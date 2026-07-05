import type { JSX, ReactNode } from 'react';
import { useConnectivity } from '../hooks/useConnectivity.ts';
import { ConnectivityContext } from './ConnectivityContextModel.ts';

interface ConnectivityProviderProps {
  readonly children: ReactNode;
  readonly healthEndpoint?: string;
  readonly checkInterval?: number;
}

function ConnectivityProvider({
  children,
  healthEndpoint,
  checkInterval,
}: ConnectivityProviderProps): JSX.Element {
  const connectivity = useConnectivity({
    ...(healthEndpoint !== undefined ? { healthEndpoint } : {}),
    ...(checkInterval !== undefined ? { checkInterval } : {}),
  });

  return (
    <ConnectivityContext.Provider value={connectivity}>{children}</ConnectivityContext.Provider>
  );
}

export { ConnectivityProvider };
