/**
 * Environment utilities for Vite SPA.
 * Uses import.meta.env which is Vite's standard for environment variables.
 */

export const isDevelopment: boolean = import.meta.env.DEV;
export const isProduction: boolean = import.meta.env.PROD;
export const isTest: boolean = import.meta.env.MODE === 'test';

export const env = {
  MODE: import.meta.env.MODE,
  DEV: import.meta.env.DEV,
  PROD: import.meta.env.PROD,
  // API URLs - all prefixed with VITE_ to be exposed to client
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  VITE_BUILD_TIME: import.meta.env.VITE_BUILD_TIME,
  VITE_APP_VERSION: import.meta.env.VITE_APP_VERSION || '0.1.0',
} as const;
