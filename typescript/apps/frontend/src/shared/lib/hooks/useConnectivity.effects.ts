/**
 * Reusable effect hooks for useConnectivity.
 * Each hook encapsulates a self-contained concern (refs, health fetch, timers, events).
 */

import { useEffect, useRef, useState } from 'react';
import type { ConnectivityState } from './useConnectivity.helpers.ts';

/** Threshold (ms) after which the disconnect timer switches to a slower update interval */
const SLOW_UPDATE_ELAPSED_THRESHOLD_MS: number = 10_000;
/** Slow update interval (ms) for the disconnect timer after threshold is reached */
const SLOW_UPDATE_INTERVAL_MS: number = 5000;
/** Fast update interval (ms) for the disconnect timer before threshold is reached */
const FAST_UPDATE_INTERVAL_MS: number = 1000;

interface HealthCheckRefs {
  currentRetryDelayRef: React.MutableRefObject<number>;
  checkTimeoutRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
  abortControllerRef: React.MutableRefObject<AbortController | null>;
  isMountedRef: React.MutableRefObject<boolean>;
}

/** No-op placeholder for ref initialization. */
const noop = (): void => undefined;

/** Initializes all refs needed for connectivity checking. */
function useConnectivityRefs(initialRetryDelay: number): {
  refs: HealthCheckRefs;
  scheduleNextCheckRef: React.MutableRefObject<(isOnline: boolean) => void>;
} {
  const currentRetryDelayRef = useRef(initialRetryDelay);
  const checkTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);
  const scheduleNextCheckRef = useRef<(isOnline: boolean) => void>(noop);

  return {
    refs: { currentRetryDelayRef, checkTimeoutRef, abortControllerRef, isMountedRef },
    scheduleNextCheckRef,
  };
}

/** Creates a health check function bound to the endpoint. */
function useHealthCheck(
  healthEndpoint: string,
  abortControllerRef: React.MutableRefObject<AbortController | null>,
): () => Promise<boolean> {
  return async (): Promise<boolean> => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch(healthEndpoint, {
        method: 'GET',
        signal: abortControllerRef.current.signal,
        headers: { Accept: 'application/json' },
      });
      return response.ok;
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        return false;
      }
      return false;
    }
  };
}

/** Tracks elapsed time since disconnect with adaptive interval. */
function useDisconnectTimer(
  disconnectedAt: number | null,
): [number, React.Dispatch<React.SetStateAction<number>>] {
  const [timeSinceDisconnect, setTimeSinceDisconnect] = useState(0);
  const disconnectTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (disconnectTimerRef.current) {
      clearInterval(disconnectTimerRef.current);
      disconnectTimerRef.current = null;
    }

    if (disconnectedAt) {
      const elapsed = Date.now() - disconnectedAt;
      setTimeSinceDisconnect(elapsed);

      const interval =
        elapsed > SLOW_UPDATE_ELAPSED_THRESHOLD_MS
          ? SLOW_UPDATE_INTERVAL_MS
          : FAST_UPDATE_INTERVAL_MS;

      disconnectTimerRef.current = setInterval(() => {
        if (disconnectedAt) {
          setTimeSinceDisconnect(Date.now() - disconnectedAt);
        }
      }, interval);
    } else {
      setTimeSinceDisconnect(0);
    }

    return (): void => {
      if (disconnectTimerRef.current) {
        clearInterval(disconnectTimerRef.current);
      }
    };
  }, [disconnectedAt]);

  return [timeSinceDisconnect, setTimeSinceDisconnect];
}

interface OnlineOfflineEventsParams {
  failureThreshold: number;
  initialRetryDelay: number;
  performCheck: () => Promise<boolean>;
  currentRetryDelayRef: React.MutableRefObject<number>;
  setState: React.Dispatch<React.SetStateAction<ConnectivityState>>;
}

/** Listens for browser online/offline events. */
function useOnlineOfflineEvents({
  failureThreshold,
  initialRetryDelay,
  performCheck,
  currentRetryDelayRef,
  setState,
}: OnlineOfflineEventsParams): void {
  useEffect(() => {
    const handleOnline = (): void => {
      currentRetryDelayRef.current = initialRetryDelay;
      performCheck().catch(() => undefined);
    };

    const handleOffline = (): void => {
      setState((prev) => ({
        ...prev,
        status: 'offline',
        isBackendAvailable: false,
        failureCount: failureThreshold,
        disconnectedAt: prev.disconnectedAt ?? Date.now(),
      }));
    };

    globalThis.addEventListener('online', handleOnline);
    globalThis.addEventListener('offline', handleOffline);

    return (): void => {
      globalThis.removeEventListener('online', handleOnline);
      globalThis.removeEventListener('offline', handleOffline);
    };
  }, [failureThreshold, initialRetryDelay, performCheck, currentRetryDelayRef, setState]);
}

export { useConnectivityRefs, useDisconnectTimer, useHealthCheck, useOnlineOfflineEvents };
