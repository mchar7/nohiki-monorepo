import { z } from 'zod';

const MS_PER_SECOND: number = 1000;
const SECONDS_PER_MINUTE: number = 60;
const MS_PER_MINUTE: number = SECONDS_PER_MINUTE * MS_PER_SECOND;
const HOURS_PER_DAY: number = 24;
const BYTES_PER_KB: number = 1024;
const BYTES_PER_MB: number = BYTES_PER_KB * BYTES_PER_KB;
/** API timeout in seconds */
const API_TIMEOUT_SECONDS: number = 30;
/** Default API timeout (30 seconds) */
const DEFAULT_API_TIMEOUT_MS: number = API_TIMEOUT_SECONDS * MS_PER_SECOND;
/** Default max file size (10 MB) */
const DEFAULT_MAX_FILE_SIZE_BYTES: number = 10 * BYTES_PER_MB;
/** Default debounce delay (ms) */
const DEFAULT_DEBOUNCE_DELAY_MS: number = 300;
/** Default API retry attempts */
const DEFAULT_API_RETRY_ATTEMPTS: number = 3;
/** Default API retry delay (ms) */
const DEFAULT_API_RETRY_DELAY_MS: number = MS_PER_SECOND;
/** Toast notification duration (5 seconds) */
const TOAST_DURATION_SECONDS: number = 5;
/** Toast notification duration (ms) */
const TOAST_DURATION_MS: number = TOAST_DURATION_SECONDS * MS_PER_SECOND;
/** Modal animation duration (ms) */
const MODAL_ANIMATION_DURATION_MS: number = 200;
/** Default pagination size */
const DEFAULT_PAGINATION_SIZE: number = 10;
/** Auto-save delay (ms) */
const AUTO_SAVE_DELAY_MS: number = MS_PER_SECOND;
/** Maximum query retries */
const QUERY_MAX_RETRIES: number = 2;
const QUERY_STALE_TIME_MINUTES: number = 5;
const QUERY_GC_TIME_MINUTES: number = 30;
const QUERY_MAX_RETRY_DELAY_SECONDS: number = 10;
/** Max form field length (characters) */
const MAX_FORM_FIELD_LENGTH: number = 1000;
/** Max textarea length (characters) */
const MAX_TEXTAREA_LENGTH: number = 5000;
/** Min password length (characters) */
const MIN_PASSWORD_LENGTH: number = 8;
/** PDF default page number */
const PDF_DEFAULT_PAGE: number = 1;
/** PDF max zoom level */
const PDF_MAX_ZOOM: number = 2;
/** PDF min zoom level */
const PDF_MIN_ZOOM: number = 0.5;
/** PDF zoom step */
const PDF_ZOOM_STEP: number = 0.1;
/** PDF default width (px) */
const PDF_DEFAULT_WIDTH_PX: number = 800;
/** PDF fullscreen width (px) */
const PDF_FULLSCREEN_WIDTH_PX: number = 1200;
/** PDF cache expiry (ms) - 24 hours */
const PDF_CACHE_EXPIRY_MS: number = HOURS_PER_DAY * MS_PER_MINUTE * SECONDS_PER_MINUTE;

const stringToNumber = (defaultVal: number): z.ZodType<number> =>
  z
    .string()
    .optional()
    .transform((val) => (val ? Number(val) : defaultVal))
    .pipe(z.number().positive());

const stringToBoolean = (defaultVal: boolean): z.ZodType<boolean> =>
  z
    .string()
    .optional()
    .transform((val) => (val ? val === 'true' : defaultVal));

function getEnvVar(key: string, defaultValue?: string): string | undefined {
  if (import.meta.env[key]) {
    return import.meta.env[key];
  }
  return defaultValue;
}

const envSchema = z.object({
  VITE_API_BASE_URL: z.string().optional().default('http://localhost:8000'),
  VITE_API_TIMEOUT: stringToNumber(DEFAULT_API_TIMEOUT_MS),

  VITE_FEATURE_OMAKASE: stringToBoolean(true),
  VITE_FEATURE_JOB_BOARD: stringToBoolean(false),
  VITE_FEATURE_SCHEDULES: stringToBoolean(false),
  VITE_FEATURE_MESSAGING: stringToBoolean(false),
  VITE_FEATURE_AUTH: stringToBoolean(true),
  VITE_AUTH_LISTINGS_WORKER_URL: z.string().optional().default(''),
  VITE_FEATURE_AUTH_LISTINGS: stringToBoolean(false),

  VITE_APP_NAME: z.string().optional().default('Nohiki'),
  VITE_APP_VERSION: z.string().optional().default('1.0.0'),
  VITE_APP_ENVIRONMENT: z
    .enum(['development', 'staging', 'production'])
    .optional()
    .default('development'),

  VITE_MAX_FILE_SIZE: stringToNumber(DEFAULT_MAX_FILE_SIZE_BYTES),
  VITE_DEBOUNCE_DELAY: stringToNumber(DEFAULT_DEBOUNCE_DELAY_MS),

  VITE_SENTRY_DSN: z.string().optional(),
  VITE_ANALYTICS_ID: z.string().optional(),
});

type ParsedEnv = z.infer<typeof envSchema>;

function parseEnvironment(): ParsedEnv {
  try {
    const envObj = {
      VITE_API_BASE_URL: getEnvVar('VITE_API_BASE_URL', 'http://localhost:8000'),
      VITE_API_TIMEOUT: getEnvVar('VITE_API_TIMEOUT'),
      VITE_FEATURE_OMAKASE: getEnvVar('VITE_FEATURE_OMAKASE'),
      VITE_FEATURE_JOB_BOARD: getEnvVar('VITE_FEATURE_JOB_BOARD'),
      VITE_FEATURE_SCHEDULES: getEnvVar('VITE_FEATURE_SCHEDULES'),
      VITE_FEATURE_MESSAGING: getEnvVar('VITE_FEATURE_MESSAGING'),
      VITE_FEATURE_AUTH: getEnvVar('VITE_FEATURE_AUTH'),
      VITE_AUTH_LISTINGS_WORKER_URL: getEnvVar('VITE_AUTH_LISTINGS_WORKER_URL', ''),
      VITE_FEATURE_AUTH_LISTINGS: getEnvVar('VITE_FEATURE_AUTH_LISTINGS'),
      VITE_APP_NAME: getEnvVar('VITE_APP_NAME', 'Nohiki'),
      VITE_APP_VERSION: getEnvVar('VITE_APP_VERSION', '1.0.0'),
      VITE_APP_ENVIRONMENT: getEnvVar(
        'VITE_APP_ENVIRONMENT',
        import.meta.env.PROD ? 'production' : 'development',
      ),
      VITE_MAX_FILE_SIZE: getEnvVar('VITE_MAX_FILE_SIZE'),
      VITE_DEBOUNCE_DELAY: getEnvVar('VITE_DEBOUNCE_DELAY'),
      VITE_SENTRY_DSN: getEnvVar('VITE_SENTRY_DSN'),
      VITE_ANALYTICS_ID: getEnvVar('VITE_ANALYTICS_ID'),
    };
    return envSchema.parse(envObj);
  } catch (error) {
    throw new Error('Invalid environment configuration', { cause: error });
  }
}

const env: ParsedEnv = parseEnvironment();

const config = {
  app: {
    name: env.VITE_APP_NAME,
    version: env.VITE_APP_VERSION,
    environment: env.VITE_APP_ENVIRONMENT,
    isDevelopment: env.VITE_APP_ENVIRONMENT === 'development',
    isProduction: env.VITE_APP_ENVIRONMENT === 'production',
    isStaging: env.VITE_APP_ENVIRONMENT === 'staging',
  },

  api: {
    baseUrl: env.VITE_API_BASE_URL,
    timeout: env.VITE_API_TIMEOUT,
    retryAttempts: DEFAULT_API_RETRY_ATTEMPTS,
    retryDelay: DEFAULT_API_RETRY_DELAY_MS,
  },

  query: {
    staleTime: QUERY_STALE_TIME_MINUTES * MS_PER_MINUTE,
    gcTime: QUERY_GC_TIME_MINUTES * MS_PER_MINUTE,
    maxRetries: QUERY_MAX_RETRIES,
    maxRetryDelay: QUERY_MAX_RETRY_DELAY_SECONDS * MS_PER_SECOND,
    refetchOnWindowFocus: false,
    retryMutations: false,
  },

  features: {
    omakase: env.VITE_FEATURE_OMAKASE,
    jobBoard: env.VITE_FEATURE_JOB_BOARD,
    schedules: env.VITE_FEATURE_SCHEDULES,
    messaging: env.VITE_FEATURE_MESSAGING,
    auth: env.VITE_FEATURE_AUTH,
    authListings: env.VITE_FEATURE_AUTH_LISTINGS,
  },

  ui: {
    debounceDelay: env.VITE_DEBOUNCE_DELAY,
    toastDuration: TOAST_DURATION_MS,
    modalAnimationDuration: MODAL_ANIMATION_DURATION_MS,
    paginationSize: DEFAULT_PAGINATION_SIZE,
    maxFileSize: env.VITE_MAX_FILE_SIZE,
  },

  pdf: {
    defaultPage: PDF_DEFAULT_PAGE,
    maxZoom: PDF_MAX_ZOOM,
    minZoom: PDF_MIN_ZOOM,
    zoomStep: PDF_ZOOM_STEP,
    defaultWidth: PDF_DEFAULT_WIDTH_PX,
    fullscreenWidth: PDF_FULLSCREEN_WIDTH_PX,
    cacheExpiry: PDF_CACHE_EXPIRY_MS,
  },

  form: {
    autoSaveDelay: AUTO_SAVE_DELAY_MS,
    maxFieldLength: MAX_FORM_FIELD_LENGTH,
    maxTextareaLength: MAX_TEXTAREA_LENGTH,
    minPasswordLength: MIN_PASSWORD_LENGTH,
  },

  storage: {
    keys: {
      store: 'nohiki-store',
      theme: 'nohiki-theme',
      lastTemplate: 'nohiki-last-template',
      editorPreferences: 'nohiki-editor-prefs',
    },
  },

  services: {
    sentry: {
      dsn: env.VITE_SENTRY_DSN,
      enabled: Boolean(env.VITE_SENTRY_DSN) && env.VITE_APP_ENVIRONMENT === 'production',
    },
    analytics: {
      id: env.VITE_ANALYTICS_ID,
      enabled: Boolean(env.VITE_ANALYTICS_ID) && env.VITE_APP_ENVIRONMENT === 'production',
    },
    authListings: {
      workerUrl: env.VITE_AUTH_LISTINGS_WORKER_URL,
    },
  },
} as const;

function isFeatureEnabled(feature: keyof typeof config.features): boolean {
  return config.features[feature];
}

export { config, isFeatureEnabled };
