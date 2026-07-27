import type { Page } from '@playwright/test';

import { AccountSettingsPage } from '../pages/index.ts';

/** Navigate to account settings and wait for the page to load. */
export async function gotoAccountPage(page: Page): Promise<AccountSettingsPage> {
  const accountPage = new AccountSettingsPage(page);
  await accountPage.goto();

  // Wait for the account API response to populate the form (skeleton disappears)
  await accountPage.saveButton.waitFor({ state: 'visible', timeout: 15_000 });
  return accountPage;
}
