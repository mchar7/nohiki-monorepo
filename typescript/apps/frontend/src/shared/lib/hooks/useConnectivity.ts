import { useEffect, useRef, useState } from 'react';
import {
  useConnectivityRefs,
  useDisconnectTimer,
  useHealthCheck,
  useOnlineOfflineEvents,
} from './useConnectivity.effects.ts';
import type {
  ConnectivityState,
  ConnectivityStatus,
  UseConnectivityOptions,
} from './useConnectivity.helpers.ts';
import {
  computeNextState,
  DEFAULT_OPTIONS,
  MIN_CHECK_DISPLAY_MS,
} from './useConnectivity.helpers.ts';

/**
 * Hook for monitoring backend connectivity status.
 * Provides graceful degradation when the backend is unavailable.
 * Uses exponential backoff for retry when offline.
 */
interface ConnectivityResult {
  status: ConnectivityStatus;
  isBackendAvailable: boolean;
  failureCount: number;
  lastChecked: Date | null;
  lastCheckedAt: number | null;
  isOnline: boolean;
  isOffline: boolean;
  isChecking: boolean;
  isDegraded: boolean;
  timeSinceDisconnect: number;
  hasChecked: boolean;
  forceCheck: () => Promise<boolean>;
  checkNow: () => Promise<boolean>;
}

/** Resolves options with defaults applied. */
function resolveOptions(options: UseConnectivityOptions): Required<UseConnectivityOptions> {
  return {
    healthEndpoint: options.healthEndpoint ?? DEFAULT_OPTIONS.healthEndpoint,
    checkInterval: options.checkInterval ?? DEFAULT_OPTIONS.checkInterval,
    initialRetryDelay: options.initialRetryDelay ?? DEFAULT_OPTIONS.initialRetryDelay,
    maxRetryDelay: options.maxRetryDelay ?? DEFAULT_OPTIONS.maxRetryDelay,
    failureThreshold: options.failureThreshold ?? DEFAULT_OPTIONS.failureThreshold,
    autoCheck: options.autoCheck ?? DEFAULT_OPTIONS.autoCheck,
  };
}

const INITIAL_STATE: ConnectivityState = {
  status: 'checking',
  isBackendAvailable: false,
  failureCount: 0,
  lastCheckedAt: null,
  disconnectedAt: null,
};

interface DeriveResultParams {
  state: ConnectivityState;
  isChecking: boolean;
  timeSinceDisconnect: number;
  hasChecked: boolean;
  checkNow: () => Promise<boolean>;
}

/** Derives the ConnectivityResult from internal state. */
function deriveResult({
  state,
  isChecking,
  timeSinceDisconnect,
  hasChecked,
  checkNow,
}: DeriveResultParams): ConnectivityResult {
  return {
    status: state.status,
    isBackendAvailable: state.isBackendAvailable,
    failureCount: state.failureCount,
    lastChecked: state.lastCheckedAt ? new Date(state.lastCheckedAt) : null,
    lastCheckedAt: state.lastCheckedAt,
    isOnline: state.status === 'online',
    isOffline: state.status === 'offline',
    isChecking,
    isDegraded: state.status === 'degraded',
    timeSinceDisconnect,
    hasChecked,
    forceCheck: checkNow,
    checkNow,
  };
}

function useConnectivity(options: UseConnectivityOptions = {}): ConnectivityResult {
  const opts = resolveOptions(options);
  const [state, setState] = useState<ConnectivityState>(() => ({ ...INITIAL_STATE }));
  const [isChecking, setIsChecking] = useState(true);
  const [hasChecked, setHasChecked] = useState(false);

  const { refs, scheduleNextCheckRef } = useConnectivityRefs(opts.initialRetryDelay);
  const checkHealth = useHealthCheck(opts.healthEndpoint, refs.abortControllerRef);
  const performCheckRef = useRef<() => Promise<boolean>>(async () => false);

  // --- performCheck: inline closure that accesses hook state directly ---
  const performCheck = async (): Promise<boolean> => {
    if (!refs.isMountedRef.current) {
      return false;
    }

    const checkStartTime = Date.now();
    setIsChecking(true);
    const isHealthy = await checkHealth();

    if (!refs.isMountedRef.current) {
      return isHealthy;
    }

    const elapsed = Date.now() - checkStartTime;
    const remainingDelay = Math.max(0, MIN_CHECK_DISPLAY_MS - elapsed);
    await new Promise((resolve) => setTimeout(resolve, remainingDelay));

    if (!refs.isMountedRef.current) {
      return isHealthy;
    }

    const now = Date.now();
    setState((prev) => computeNextState(prev, isHealthy, now, opts.failureThreshold));
    setIsChecking(false);
    setHasChecked(true);

    if (isHealthy) {
      refs.currentRetryDelayRef.current = opts.initialRetryDelay;
    } else {
      refs.currentRetryDelayRef.current = Math.min(
        refs.currentRetryDelayRef.current * 2,
        opts.maxRetryDelay,
      );
    }

    scheduleNextCheckRef.current(isHealthy);
    return isHealthy;
  };

  performCheckRef.current = performCheck;

  // --- scheduleNextCheck: inline closure using performCheckRef for stable scheduling ---
  const scheduleNextCheck = (isOnline: boolean): void => {
    if (refs.checkTimeoutRef.current) {
      clearTimeout(refs.checkTimeoutRef.current);
      refs.checkTimeoutRef.current = null;
    }
    if (!(opts.autoCheck && refs.isMountedRef.current)) {
      return;
    }
    const delay = isOnline ? opts.checkInterval : refs.currentRetryDelayRef.current;
    refs.checkTimeoutRef.current = setTimeout(() => {
      if (refs.isMountedRef.current) {
        performCheckRef.current();
      }
    }, delay);
  };
  scheduleNextCheckRef.current = scheduleNextCheck;

  const checkNow = (): Promise<boolean> => {
    refs.currentRetryDelayRef.current = opts.initialRetryDelay;
    return performCheck();
  };

  // Mount check and cleanup
  useEffect(() => {
    refs.isMountedRef.current = true;
    performCheckRef.current();

    return (): void => {
      refs.isMountedRef.current = false;
      if (refs.checkTimeoutRef.current) {
        clearTimeout(refs.checkTimeoutRef.current);
      }
      refs.abortControllerRef.current?.abort();
    };
  }, [refs]);

  const [timeSinceDisconnect] = useDisconnectTimer(state.disconnectedAt);
  useOnlineOfflineEvents({
    failureThreshold: opts.failureThreshold,
    initialRetryDelay: opts.initialRetryDelay,
    performCheck,
    currentRetryDelayRef: refs.currentRetryDelayRef,
    setState,
  });

  return deriveResult({ state, isChecking, timeSinceDisconnect, hasChecked, checkNow });
}

export type { ConnectivityStatus } from './useConnectivity.helpers.ts';
export { useConnectivity };
