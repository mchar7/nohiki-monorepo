/**
 * E2E Test Constants
 *
 * Centralized configuration for all E2E tests.
 * No magic values allowed in test files - all constants defined here.
 */

import process from 'node:process';

// Non-export constants (must be before exports per useExportsLast rule)
const INITIAL_RETRY_MS = 1000;
const RETRY_MULTIPLIER = 2;
const MAX_RETRY_EXPONENT = 3;

export const E2E_CONFIG = {
  authListingsLane: process.env.E2E_AUTH_LISTINGS_LANE ?? 'off',
  baseUrl: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
  isCI: process.env.CI === 'true',
} as const;

export const TIMEOUTS = {
  navigation: 30_000,
  networkIdle: 10_000,
  elementVisible: 10_000,
  formSubmit: 30_000,
  apiResponse: 15_000,
  cqrsProjection: 60_000,
  pipelineCompletion: 180_000,
  shortAction: 5000,
} as const;

/** Exponential backoff intervals (ms) for toPass() retry assertions on CQRS projections. */
export const RETRY_INTERVALS = [
  INITIAL_RETRY_MS,
  INITIAL_RETRY_MS * RETRY_MULTIPLIER,
  INITIAL_RETRY_MS * RETRY_MULTIPLIER ** 2,
  INITIAL_RETRY_MS * RETRY_MULTIPLIER ** MAX_RETRY_EXPONENT,
] as const;

export const TEST_USER = {
  email: 'e2e-playwright@example.com',
  password: 'PlaywrightP@ss123!',
  displayName: 'E2E Playwright',
} as const;

export const AUTH_PATHS = {
  login: '/auth',
  register: '/auth/register',
  loginApi: '/api/v1/auth/login',
  registerApi: '/api/v1/auth/register',
  refreshApi: '/api/v1/auth/refresh',
  sessionApi: '/api/v1/session',
} as const;

export const APP_PATHS = {
  home: '/',
  dashboard: '/dashboard',
  profiles: '/profiles',
  profileNew: '/profiles/new',
  jobs: '/jobs',
  jobMatches: '/jobs/matches',
  documents: '/documents',
  settings: '/settings',
} as const;

export const EXTERNAL_URLS = {
  termsOfService: 'https://www.nohiki.com/terms',
  privacyPolicy: 'https://www.nohiki.com/privacy',
} as const;

/** Root directory for all E2E artifacts, relative to the config file (e2e/). */
const E2E_OUTPUT_DIR = '.output';

export const E2E_PATHS = {
  auth: `${E2E_OUTPUT_DIR}/auth`,
  results: `${E2E_OUTPUT_DIR}/results`,
  report: `${E2E_OUTPUT_DIR}/report`,
} as const;

export const PRIMARY_USER_STORAGE_STATE_PATH = `${E2E_PATHS.auth}/primary-user.json`;

export const TEST_DATA = {
  skills: {
    allowed: ['Python', 'JavaScript', 'PostgreSQL', 'SQL', 'Java'],
    disallowed: ['PHP', 'WordPress', 'Drupal'],
  },
  workArrangements: ['remote', 'hybrid', 'onsite'] as const,
} as const;

export const SELECTORS = {
  tabs: {
    signIn: { role: 'tab' as const, name: /sign in/iu },
    signUp: { role: 'tab' as const, name: /sign up/iu },
  },
  buttons: {
    signIn: { role: 'button' as const, name: /^sign in$/iu },
    signUp: { role: 'button' as const, name: /^sign up$/iu },
    google: { role: 'button' as const, name: /google/iu },
    github: { role: 'button' as const, name: /github/iu },
    delete: { role: 'button' as const, name: /delete/iu },
    confirm: { role: 'button' as const, name: /confirm|yes|delete/iu },
    createProfile: { role: 'button' as const, name: /create new|new profile|create profile/iu },
  },
  inputs: {
    email: { label: /email/iu },
    password: { label: /^password$/iu },
    confirmPassword: { label: /confirm password/iu },
    displayName: { label: /display name/iu },
  },
  links: {
    terms: { role: 'link' as const, name: /terms of service/iu },
    privacy: { role: 'link' as const, name: /privacy policy/iu },
  },
  testIds: {
    formRootError: 'form-root-error',
    userMenu: 'user-menu',
    profileCard: 'profile-card',
    jobList: 'job-list',
    jobCard: 'job-card',
    statsCards: 'stats-cards',
    quickActions: 'quick-actions',
    recentActivity: 'recent-activity',
  },
  classes: {
    errorMessage: '.text-destructive',
    toast: '[data-sonner-toast]',
  },
} as const;

export const REGEX_PATTERNS = {
  dashboardUrl: /\/$|\/dashboard/u,
  profileDetailUrl: /\/profiles\/[\w-]+/u,
  matchDetailUrl: /\/jobs\/matches\/[\w-]+/u,
  authRedirectUrl: /\/auth(?:\/login)?(?:\?|$)|\/login/u,
  uuid: /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu,
} as const;

/** List page URL patterns tolerate query params injected by useUrlListState. */
export const LIST_URL_PATTERNS = {
  profiles: /\/profiles(?:\?|$)/u,
  jobs: /\/jobs(?:\?|$)/u,
  jobMatches: /\/jobs\/matches(?:\?|$)/u,
  attachments: /\/attachments(?:\?|$)/u,
  documents: /\/documents(?:\?|$)/u,
} as const;
