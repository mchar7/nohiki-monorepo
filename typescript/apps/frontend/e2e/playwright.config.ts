import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

import { E2E_CONFIG, E2E_PATHS, PRIMARY_USER_STORAGE_STATE_PATH, TIMEOUTS } from './constants.ts';

const currentDir: string = path.dirname(fileURLToPath(import.meta.url));
const primaryUserStorageState: string = path.join(currentDir, PRIMARY_USER_STORAGE_STATE_PATH);

const retries: number = E2E_CONFIG.isCI ? 2 : 0;
const isAuthListingsLane: boolean = E2E_CONFIG.authListingsLane === 'on';
const baseUrl: string = isAuthListingsLane ? 'http://127.0.0.1:5174' : E2E_CONFIG.baseUrl;
const webServerCommand: string = isAuthListingsLane
  ? 'VITE_E2E=true VITE_FEATURE_AUTH_LISTINGS=true VITE_AUTH_LISTINGS_WORKER_URL=http://auth-listings.e2e pnpm run dev --host 127.0.0.1 --port 5174 --strictPort'
  : 'VITE_E2E=true VITE_FEATURE_AUTH_LISTINGS=false VITE_AUTH_LISTINGS_WORKER_URL= pnpm run dev';

type Reporter = Parameters<typeof defineConfig>[0]['reporter'];
const reporter: Reporter = E2E_CONFIG.isCI
  ? [['list'], ['html', { outputFolder: E2E_PATHS.report }], ['github']]
  : [['list'], ['html', { outputFolder: E2E_PATHS.report }]];

export default defineConfig({
  testDir: './journeys',
  outputDir: E2E_PATHS.results,

  fullyParallel: false,
  workers: 1,

  forbidOnly: E2E_CONFIG.isCI,
  retries,

  reporter,

  timeout: 60_000,
  expect: {
    timeout: TIMEOUTS.elementVisible,
  },

  use: {
    baseURL: baseUrl,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
    viewport: { width: 1280, height: 720 },
    headless: true,
  },

  projects: [
    ...(isAuthListingsLane
      ? []
      : [
          {
            name: 'setup',
            testDir: currentDir,
            testMatch: /global-setup\.ts/u,
          },
        ]),
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        ...(isAuthListingsLane ? {} : { storageState: primaryUserStorageState }),
      },
      ...(isAuthListingsLane ? {} : { dependencies: ['setup'] }),
    },
  ],

  webServer: {
    command: webServerCommand,
    url: baseUrl,
    reuseExistingServer: !isAuthListingsLane,
    timeout: 120_000,
  },
});
