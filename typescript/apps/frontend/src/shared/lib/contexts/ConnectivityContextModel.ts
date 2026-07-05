import { type Context, createContext } from 'react';
import type { ConnectivityStatus } from '../hooks/useConnectivity.ts';

interface ConnectivityContextValue {
  status: ConnectivityStatus;
  isBackendAvailable: boolean;
  isOnline: boolean;
  isOffline: boolean;
  isChecking: boolean;
  isDegraded: boolean;
  lastChecked: Date | null;
  lastCheckedAt: number | null;
  failureCount: number;
  timeSinceDisconnect: number;
  /** Whether at least one connectivity check has completed */
  hasChecked: boolean;
  forceCheck: () => Promise<boolean>;
  checkNow: () => Promise<boolean>;
}

const ConnectivityContext: Context<ConnectivityContextValue | null> =
  createContext<ConnectivityContextValue | null>(null);

export type { ConnectivityContextValue };
export { ConnectivityContext };
