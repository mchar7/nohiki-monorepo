import { useContext } from 'react';
import type { ConnectivityContextValue } from './ConnectivityContextModel.ts';
import { ConnectivityContext } from './ConnectivityContextModel.ts';

const defaultCheckFn = async (): Promise<boolean> => true;

function useConnectivityContext(): ConnectivityContextValue {
  const context = useContext(ConnectivityContext);
  if (!context) {
    throw new Error('useConnectivityContext must be used within a ConnectivityProvider');
  }
  return context;
}

/**
 * Returns an optimistic fallback when no ConnectivityProvider is mounted.
 * Use this only for passive UI affordances that should render in tests or
 * degraded shells without failing the entire tree.
 */
function useConnectivitySafe(): ConnectivityContextValue {
  const context = useContext(ConnectivityContext);
  return (
    context ?? {
      status: 'online',
      isBackendAvailable: true,
      isOnline: true,
      isOffline: false,
      isChecking: false,
      isDegraded: false,
      lastChecked: null,
      lastCheckedAt: null,
      failureCount: 0,
      timeSinceDisconnect: 0,
      hasChecked: false,
      forceCheck: defaultCheckFn,
      checkNow: defaultCheckFn,
    }
  );
}

export { useConnectivityContext, useConnectivitySafe };
