/**
 * API Configuration
 *
 * Cache configuration and storage key constants.
 *
 * The fetch client is initialized in shared/api/client.ts using openapi-fetch.
 * The frontend communicates with backend services through Traefik:
 * - /api/v1/auth/* → user-auth-service (identity)
 * - /api/* → bff-service
 * - /.well-known/jwks.json → user-auth-service
 */
const MS_PER_SECOND: number = 1000;
const SECONDS_PER_MINUTE: number = 60;
const MS_PER_MINUTE: number = SECONDS_PER_MINUTE * MS_PER_SECOND;

const SESSION_STALE_MINUTES: number = 5;
const SESSION_GC_MINUTES: number = 30;
const USER_DATA_STALE_MINUTES: number = 2;
const USER_DATA_GC_MINUTES: number = 10;
const DYNAMIC_STALE_SECONDS: number = 30;
const DYNAMIC_GC_MINUTES: number = 5;
const STATIC_STALE_MINUTES: number = 10;
const STATIC_GC_MINUTES: number = 60;
const AUTH_LISTINGS_STALE_HOURS: number = 3;
const AUTH_LISTINGS_GC_HOURS: number = 24;

/**
 * Cache configuration for different data types.
 * Time values in milliseconds.
 *
 * Design rationale for staleTime/gcTime:
 * - Session: Long stale time (check once, trust for duration)
 * - Profiles: Medium stale time (user-owned, rarely changes externally)
 * - Listings: Short stale time (external data, updates frequently)
 * - Correlations: Short stale time (matches can update based on new jobs)
 * - Templates: Long stale time (system data, rarely changes)
 */
const CACHE_CONFIG = {
  /** Session data - 5 minutes stale, 30 minutes gc */
  SESSION: {
    staleTime: SESSION_STALE_MINUTES * MS_PER_MINUTE,
    gcTime: SESSION_GC_MINUTES * MS_PER_MINUTE,
  },
  /** User-owned data like profiles - 2 minutes stale, 10 minutes gc */
  USER_DATA: {
    staleTime: USER_DATA_STALE_MINUTES * MS_PER_MINUTE,
    gcTime: USER_DATA_GC_MINUTES * MS_PER_MINUTE,
  },
  /** Frequently updating data like listings - 30 seconds stale, 5 minutes gc */
  DYNAMIC: {
    staleTime: DYNAMIC_STALE_SECONDS * MS_PER_SECOND,
    gcTime: DYNAMIC_GC_MINUTES * MS_PER_MINUTE,
  },
  /** Rarely changing system data like templates - 10 minutes stale, 1 hour gc */
  STATIC: {
    staleTime: STATIC_STALE_MINUTES * MS_PER_MINUTE,
    gcTime: STATIC_GC_MINUTES * MS_PER_MINUTE,
  },
  /** Auth page listings - 3 hours stale, 24 hours gc (matches edge cache) */
  AUTH_LISTINGS: {
    staleTime: AUTH_LISTINGS_STALE_HOURS * MS_PER_MINUTE * SECONDS_PER_MINUTE,
    gcTime: AUTH_LISTINGS_GC_HOURS * MS_PER_MINUTE * SECONDS_PER_MINUTE,
  },
  /** Data that should never be cached (mutations, one-time fetches) */
  NONE: {
    staleTime: 0,
    gcTime: 0,
  },
} as const;

/**
 * localStorage keys for persisted state
 */
const STORAGE_KEYS = {
  AUTH_STATE: 'nohiki:auth:state',
  SELECTED_PROFILE: 'nohiki:profile:selected',
  THEME: 'nohiki:theme',
  SIDEBAR_COLLAPSED: 'nohiki:sidebar:collapsed',
} as const;

export { CACHE_CONFIG, STORAGE_KEYS };
