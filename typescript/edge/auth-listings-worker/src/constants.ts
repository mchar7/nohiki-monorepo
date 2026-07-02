export const WORKER_SERVICE_NAME = 'auth-listings-worker' as const;
export const WORKER_SERVICE_VERSION = '1.0.0' as const;

/** Standard cache freshness: 3 hours */
export const CACHE_FRESH_SECONDS: number = 10_800;

/** Stale-while-revalidate window: 72 hours */
export const CACHE_SWR_SECONDS: number = 259_200;

/** BFF fetch timeout: 5 seconds */
export const BFF_TIMEOUT_MS: number = 5000;

/** Maximum accepted BFF response body (1 MiB). */
export const BFF_MAX_RESPONSE_BYTES: number = 1024 * 1024;

/** Cache key prefix (fake URL for Cloudflare Cache API) */
export const CACHE_KEY_PREFIX = 'https://cache.internal/auth-listings' as const;

/** Cache version for key namespacing */
export const CACHE_VERSION = 'v1' as const;

/** Default country when request.cf is unavailable */
export const DEFAULT_COUNTRY_ALPHA3 = 'USA' as const;

/** Cache TTL for empty responses (5 minutes), shorter so countries get fresh data sooner */
export const CACHE_EMPTY_RESPONSE_SECONDS: number = 300;
