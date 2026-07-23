import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test as setup } from '@playwright/test';

import { AUTH_PATHS, PRIMARY_USER_STORAGE_STATE_PATH, REGEX_PATTERNS } from './constants.ts';
import {
  fillRegistrationForm,
  navigateToSignUpTab,
  submitRegistrationAndWait,
} from './utils/auth-setup-helpers.ts';

const currentDir: string = path.dirname(fileURLToPath(import.meta.url));
const STORAGE_STATE_FILE: string = path.join(currentDir, PRIMARY_USER_STORAGE_STATE_PATH);

function generateUniqueEmail(): string {
  return `e2e-${Date.now()}@example.com`;
}
function ensureStorageStateDirectory(): void {
  fs.mkdirSync(path.dirname(STORAGE_STATE_FILE), { recursive: true });
}

setup('authenticate', async ({ page }) => {
  ensureStorageStateDirectory();

  const uniqueEmail = generateUniqueEmail();

  await page.goto(AUTH_PATHS.register);

  await navigateToSignUpTab(page);
  await fillRegistrationForm(page, uniqueEmail);
  await submitRegistrationAndWait(page, REGEX_PATTERNS.dashboardUrl);
  await page.context().storageState({ path: STORAGE_STATE_FILE });
});
