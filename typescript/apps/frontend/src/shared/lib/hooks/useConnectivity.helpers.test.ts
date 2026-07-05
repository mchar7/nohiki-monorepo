import { describe, expect } from 'vitest';
import type { ConnectivityState } from './useConnectivity.helpers.ts';
import { computeNextState } from './useConnectivity.helpers.ts';

const ONLINE_STATE: ConnectivityState = {
  status: 'online',
  isBackendAvailable: true,
  failureCount: 0,
  lastCheckedAt: Date.now(),
  disconnectedAt: null,
};

const NOW = 1_700_000_000_000;
/** Default failure threshold: 3 consecutive failures trigger offline */
const THRESHOLD_DEFAULT = 3;
/** Single-failure threshold for verifying immediate-offline behavior */
const THRESHOLD_SINGLE = 1;

describe('computeNextState - failure accumulation (threshold=3)', () => {
  test('remains non-offline (isBackendAvailable stays true) after 1 consecutive failure', () => {
    const next = computeNextState(ONLINE_STATE, false, NOW, THRESHOLD_DEFAULT);

    expect(next.status).not.toBe('offline');
    expect(next.isBackendAvailable).toBe(true);
    expect(next.failureCount).toBe(1);
  });

  test('remains non-offline (isBackendAvailable stays true) after 2 consecutive failures', () => {
    const afterFirst = computeNextState(ONLINE_STATE, false, NOW, THRESHOLD_DEFAULT);
    const afterSecond = computeNextState(afterFirst, false, NOW + 1, THRESHOLD_DEFAULT);

    expect(afterSecond.status).not.toBe('offline');
    expect(afterSecond.isBackendAvailable).toBe(true);
    expect(afterSecond.failureCount).toBe(2);
  });

  test('transitions to offline after 3 consecutive failures', () => {
    const afterFirst = computeNextState(ONLINE_STATE, false, NOW, THRESHOLD_DEFAULT);
    const afterSecond = computeNextState(afterFirst, false, NOW + 1, THRESHOLD_DEFAULT);
    const afterThird = computeNextState(afterSecond, false, NOW + 2, THRESHOLD_DEFAULT);

    expect(afterThird.status).toBe('offline');
    expect(afterThird.isBackendAvailable).toBe(false);
    expect(afterThird.failureCount).toBe(THRESHOLD_DEFAULT);
  });
});

describe('computeNextState - recovery and timestamps (threshold=3)', () => {
  test('resets failure count and returns online after a successful check', () => {
    const afterFirst = computeNextState(ONLINE_STATE, false, NOW, THRESHOLD_DEFAULT);
    const afterSecond = computeNextState(afterFirst, false, NOW + 1, THRESHOLD_DEFAULT);
    const recovered = computeNextState(afterSecond, true, NOW + 2, THRESHOLD_DEFAULT);

    expect(recovered.status).toBe('online');
    expect(recovered.isBackendAvailable).toBe(true);
    expect(recovered.failureCount).toBe(0);
  });

  test('records disconnectedAt only when transitioning to offline', () => {
    const afterFirst = computeNextState(ONLINE_STATE, false, NOW, THRESHOLD_DEFAULT);
    const afterSecond = computeNextState(afterFirst, false, NOW + 1, THRESHOLD_DEFAULT);
    const afterThird = computeNextState(afterSecond, false, NOW + 2, THRESHOLD_DEFAULT);

    // No disconnectedAt until we actually go offline
    expect(afterFirst.disconnectedAt).toBeNull();
    expect(afterSecond.disconnectedAt).toBeNull();
    // Recorded when status first becomes offline
    expect(afterThird.disconnectedAt).toBe(NOW + 2);
  });

  test('clears disconnectedAt when recovering from offline', () => {
    const afterFirst = computeNextState(ONLINE_STATE, false, NOW, THRESHOLD_DEFAULT);
    const afterSecond = computeNextState(afterFirst, false, NOW + 1, THRESHOLD_DEFAULT);
    const offline = computeNextState(afterSecond, false, NOW + 2, THRESHOLD_DEFAULT);
    // Recovery check happens one step after reaching offline (time = NOW + threshold)
    const recovered = computeNextState(offline, true, NOW + THRESHOLD_DEFAULT, THRESHOLD_DEFAULT);

    expect(recovered.disconnectedAt).toBeNull();
  });
});

describe('computeNextState - single-failure threshold (threshold=1)', () => {
  test('transitions to offline immediately on the first failure', () => {
    const next = computeNextState(ONLINE_STATE, false, NOW, THRESHOLD_SINGLE);

    expect(next.status).toBe('offline');
    expect(next.isBackendAvailable).toBe(false);
    expect(next.failureCount).toBe(THRESHOLD_SINGLE);
  });
});
