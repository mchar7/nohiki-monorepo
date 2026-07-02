import type { APIRequestContext } from '@playwright/test';
import { TIMEOUTS } from '../constants.ts';

const HTTP_NOT_FOUND = 404;
const DEFAULT_POLL_INTERVAL_MS = 1000;

function delay(milliseconds: number): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, milliseconds);
  return promise;
}

/**
 * Create a job target profile via the BFF API.
 *
 * Returns the CQRS command acceptance response with request_id.
 */
async function createProfileViaApi(
  request: APIRequestContext,
  data: {
    pref_name: string;
    search_keywords: string[];
    disallowed_keywords?: string[];
    work_arrangements?: string[];
  },
): Promise<{ request_id: string; status: string }> {
  const response = await request.post('/api/v1/profiles', {
    data: {
      pref_name: data.pref_name,
      search_keywords: data.search_keywords,
      disallowed_keywords: data.disallowed_keywords ?? [],
      work_arrangements: data.work_arrangements ?? ['REMOTE'],
      salary_preference: {
        min_salary: { minor_units: 8_000_000, currency: 'USD' },
        target_salary: { minor_units: 12_000_000, currency: 'USD' },
        preferred_frequency: 'ANNUALLY',
      },
      experience_preference: {
        experience_years: 5,
        seniority_levels: ['MID', 'SENIOR'],
      },
    },
  });

  if (!response.ok()) {
    const body = await response.text();
    throw new Error(`Failed to create profile (${response.status()}): ${body}`);
  }

  return response.json();
}

/**
 * Delete a profile via the BFF API (CQRS command).
 */
async function deleteProfileViaApi(request: APIRequestContext, profileId: string): Promise<void> {
  const response = await request.delete(`/api/v1/profiles/${profileId}`);

  if (!response.ok() && response.status() !== HTTP_NOT_FOUND) {
    throw new Error(`Failed to delete profile: ${response.status()}`);
  }
}

/**
 * Poll an API endpoint until a predicate is satisfied.
 *
 * Used for CQRS projection polling - waits for eventually-consistent
 * data to appear after a command is accepted.
 */
async function waitForProjection<T>(
  request: APIRequestContext,
  endpoint: string,
  predicate: (data: T) => boolean,
  options: {
    timeout?: number;
    interval?: number;
    backoffMultiplier?: number;
    maxInterval?: number;
  } = {},
): Promise<T> {
  const {
    timeout = TIMEOUTS.cqrsProjection,
    interval = DEFAULT_POLL_INTERVAL_MS,
    backoffMultiplier = 1,
    maxInterval = 30_000,
  } = options;
  const startTime = Date.now();
  let currentInterval = interval;

  while (Date.now() - startTime < timeout) {
    const response = await request.get(endpoint);
    if (response.ok()) {
      const data = (await response.json()) as T;
      if (predicate(data)) {
        return data;
      }
    }
    await delay(currentInterval);
    if (backoffMultiplier > 1) {
      currentInterval = Math.min(currentInterval * backoffMultiplier, maxInterval);
    }
  }

  throw new Error(`Timeout (${timeout}ms) waiting for projection at ${endpoint}`);
}

interface PaginatedCorrelations {
  items: Array<{ id: string; listing_title: string; fit_score: number; status: string }>;
  total: number;
}

/**
 * Wait for the full Kafka pipeline to produce correlations for the test user.
 *
 * Pipeline: profile created → embedding computed → correlations evaluated → BFF projection updated.
 * This can take 30-120s depending on ML compute load.
 */
function waitForCorrelations(
  request: APIRequestContext,
  options: { minCount?: number; timeout?: number; interval?: number } = {},
): Promise<PaginatedCorrelations> {
  const { minCount = 1, timeout = TIMEOUTS.pipelineCompletion, interval = 2000 } = options;

  return waitForProjection<PaginatedCorrelations>(
    request,
    '/api/v1/listings/correlations/mine?min_score=0',
    (data) => data.total >= minCount,
    { timeout, interval, backoffMultiplier: 1.5, maxInterval: 10_000 },
  );
}

interface PaginatedProfiles {
  items: Array<{ id: string; pref_name: string }>;
  total: number;
}

/**
 * Wait for a profile to appear in the CQRS projection after creation command.
 */
async function waitForProfile(
  request: APIRequestContext,
  profileName: string,
  options: { timeout?: number } = {},
): Promise<string> {
  const { timeout = TIMEOUTS.cqrsProjection } = options;

  const data = await waitForProjection<PaginatedProfiles>(
    request,
    '/api/v1/profiles',
    (result) => result.items.some((p) => p.pref_name === profileName),
    { timeout },
  );

  const profile = data.items.find((p) => p.pref_name === profileName);
  if (!profile) {
    throw new Error(`Profile "${profileName}" not found after waitForProjection`);
  }
  return profile.id;
}

export {
  createProfileViaApi,
  deleteProfileViaApi,
  waitForCorrelations,
  waitForProfile,
  waitForProjection,
};
