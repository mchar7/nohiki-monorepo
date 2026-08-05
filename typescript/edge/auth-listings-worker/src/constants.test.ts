import { describe, expect, it } from 'vitest';
import {
  BFF_TIMEOUT_MS,
  CACHE_EMPTY_RESPONSE_SECONDS,
  CACHE_FRESH_SECONDS,
  CACHE_KEY_PREFIX,
  CACHE_SWR_SECONDS,
  DEFAULT_COUNTRY_ALPHA3,
  WORKER_SERVICE_NAME,
  WORKER_SERVICE_VERSION,
} from './constants';

const THREE_HOURS_IN_SECONDS = 10_800;
const SEVENTY_TWO_HOURS_IN_SECONDS = 259_200;
const FIVE_SECONDS_IN_MS = 5000;
const FIVE_MINUTES_IN_SECONDS = 300;

describe('constants', () => {
  it('WORKER_SERVICE_NAME is auth-listings-worker', () => {
    expect(WORKER_SERVICE_NAME).toBe('auth-listings-worker');
  });

  it('WORKER_SERVICE_VERSION is 1.0.0', () => {
    expect(WORKER_SERVICE_VERSION).toBe('1.0.0');
  });

  it('CACHE_FRESH_SECONDS is 3 hours (10800)', () => {
    expect(CACHE_FRESH_SECONDS).toBe(THREE_HOURS_IN_SECONDS);
  });

  it('CACHE_SWR_SECONDS is 72 hours (259200)', () => {
    expect(CACHE_SWR_SECONDS).toBe(SEVENTY_TWO_HOURS_IN_SECONDS);
  });

  it('BFF_TIMEOUT_MS is 5 seconds (5000)', () => {
    expect(BFF_TIMEOUT_MS).toBe(FIVE_SECONDS_IN_MS);
  });

  it('CACHE_KEY_PREFIX is the internal cache URL', () => {
    expect(CACHE_KEY_PREFIX).toBe('https://cache.internal/auth-listings');
  });

  it('DEFAULT_COUNTRY_ALPHA3 is USA', () => {
    expect(DEFAULT_COUNTRY_ALPHA3).toBe('USA');
  });

  it('CACHE_EMPTY_RESPONSE_SECONDS is 5 minutes (300)', () => {
    expect(CACHE_EMPTY_RESPONSE_SECONDS).toBe(FIVE_MINUTES_IN_SECONDS);
  });
});
