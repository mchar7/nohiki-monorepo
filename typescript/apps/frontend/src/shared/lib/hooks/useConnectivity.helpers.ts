/**
 * Pure helper functions and types for the useConnectivity hook.
 * Extracted to keep the main hook file under the line limit.
 */

type ConnectivityStatus = 'online' | 'offline' | 'checking' | 'degraded';

interface ConnectivityState {
  /** Current connectivity status */
  status: ConnectivityStatus;
  /** Whether backend is reachable */
  isBackendAvailable: boolean;
  /** Consecutive failure count */
  failureCount: number;
  /** Last successful check timestamp */
  lastCheckedAt: number | null;
  /** When we first detected offline status */
  disconnectedAt: number | null;
}

interface UseConnectivityOptions {
  /** Health check endpoint URL */
  readonly healthEndpoint?: string;
  /** Base interval between health checks when online (default: 30000ms) */
  readonly checkInterval?: number;
  /** Initial retry delay when offline (default: 2000ms) */
  readonly initialRetryDelay?: number;
  /** Maximum retry delay when offline (default: 60000ms) */
  readonly maxRetryDelay?: number;
  /** Number of consecutive failures before considering offline (default: 3) */
  readonly failureThreshold?: number;
  /** Enable automatic health checks (default: true) */
  readonly autoCheck?: boolean;
}

const DEFAULT_OPTIONS: Required<UseConnectivityOptions> = {
  // Use /api/ping - public endpoint exposed via API gateway for connectivity checks
  healthEndpoint: '/api/ping',
  checkInterval: 60_000, // Check less frequently (1 minute)
  initialRetryDelay: 2000,
  maxRetryDelay: 60_000,
  failureThreshold: 3, // Require 3 consecutive failures before considering offline
  // Enable automatic polling to allow recovery from transient failures
  autoCheck: true,
};

// Minimum time to show checking state to avoid flicker jank
const MIN_CHECK_DISPLAY_MS = 1200;

function resolveConnectivityStatus(isHealthy: boolean, isOffline: boolean): ConnectivityStatus {
  if (isHealthy) {
    return 'online';
  }
  if (isOffline) {
    return 'offline';
  }
  return 'degraded';
}

interface ResolveDisconnectedAtParams {
  isOffline: boolean;
  wasOffline: boolean;
  isHealthy: boolean;
  now: number;
  prevDisconnectedAt: number | null;
}

function resolveDisconnectedAt({
  isOffline,
  wasOffline,
  isHealthy,
  now,
  prevDisconnectedAt,
}: ResolveDisconnectedAtParams): number | null {
  if (isOffline && !wasOffline) {
    return now;
  }
  if (isHealthy) {
    return null;
  }
  return prevDisconnectedAt;
}

function computeNextState(
  prev: ConnectivityState,
  isHealthy: boolean,
  now: number,
  failureThreshold: number,
): ConnectivityState {
  const newFailureCount = isHealthy ? 0 : prev.failureCount + 1;
  const isOffline = newFailureCount >= failureThreshold;
  const wasOffline = prev.status === 'offline';

  const newStatus: ConnectivityStatus = resolveConnectivityStatus(isHealthy, isOffline);

  const disconnectedAt = resolveDisconnectedAt({
    isOffline,
    wasOffline,
    isHealthy,
    now,
    prevDisconnectedAt: prev.disconnectedAt,
  });

  return {
    status: newStatus,
    isBackendAvailable: isHealthy || newFailureCount < failureThreshold,
    failureCount: newFailureCount,
    lastCheckedAt: now,
    disconnectedAt,
  };
}

export type { ConnectivityState, ConnectivityStatus, UseConnectivityOptions };
export { computeNextState, DEFAULT_OPTIONS, MIN_CHECK_DISPLAY_MS };
