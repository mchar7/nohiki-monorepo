/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_API_GATEWAY_URL?: string;
  readonly VITE_API_TIMEOUT: string;
  readonly VITE_FEATURE_OMAKASE: string;
  readonly VITE_FEATURE_JOB_BOARD: string;
  readonly VITE_FEATURE_SCHEDULES: string;
  readonly VITE_FEATURE_MESSAGING: string;
  readonly VITE_FEATURE_AUTH: string;
  readonly VITE_AUTH_LISTINGS_WORKER_URL: string;
  readonly VITE_FEATURE_AUTH_LISTINGS: string;
  readonly VITE_APP_NAME: string;
  readonly VITE_APP_VERSION: string;
  readonly VITE_APP_ENVIRONMENT: string;
  readonly VITE_BUILD_TIME?: string;
  readonly VITE_MAX_FILE_SIZE: string;
  readonly VITE_DEBOUNCE_DELAY: string;
  readonly VITE_SENTRY_DSN?: string;
  readonly VITE_ANALYTICS_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module '*.css' {
  const content: string;
  export default content;
}

declare module '*.html?raw' {
  const content: string;
  export default content;
}

declare module '*.json' {
  const content: Record<string, unknown>;
  export default content;
}
