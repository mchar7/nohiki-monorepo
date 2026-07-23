import { isAbsolute } from 'node:path';
import process from 'node:process';
import { defineConfig } from '@playwright/test';

import baseConfig from './playwright.config.ts';

const PUBLIC_ORIGIN = 'http://nohiki.localhost';
const artifactDirOverride: string | undefined = process.env.E2E_ARTIFACT_DIR;
if (artifactDirOverride !== undefined && !isAbsolute(artifactDirOverride)) {
  throw new Error('E2E_ARTIFACT_DIR must be an absolute path');
}
const artifactDir: string = artifactDirOverride ?? '.output/k8s';
if (process.env.E2E_BASE_URL !== PUBLIC_ORIGIN) {
  throw new Error(`E2E_BASE_URL must be ${PUBLIC_ORIGIN}`);
}

export default defineConfig({
  ...baseConfig,
  globalTeardown: './global-teardown.ts',
  retries: 0,
  workers: 1,
  webServer: undefined,
  outputDir: `${artifactDir}/results`,
  reporter: [
    ['list'],
    ['html', { outputFolder: `${artifactDir}/report`, open: 'never' }],
    ['json', { outputFile: `${artifactDir}/results.json` }],
  ],
  use: {
    ...baseConfig.use,
    baseURL: PUBLIC_ORIGIN,
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
