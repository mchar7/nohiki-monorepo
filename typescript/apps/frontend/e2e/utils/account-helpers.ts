import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { AccountSettingsPage } from '../pages/index.ts';

/** Navigate to account settings and wait for the page to load. */
export async function gotoAccountPage(page: Page): Promise<AccountSettingsPage> {
  const accountPage = new AccountSettingsPage(page);
  await accountPage.goto();
  await page.waitForLoadState('load');
  // Wait for the account API response to populate the form (skeleton disappears)
  await accountPage.saveButton.waitFor({ state: 'visible', timeout: 15_000 });
  return accountPage;
}

/** Assert that at least one account information field is visible. */
export async function assertAccountFieldsVisible(accountPage: AccountSettingsPage): Promise<void> {
  const hasDisplayName = await accountPage.displayNameInput.isVisible();
  const hasFirstName = await accountPage.firstNameInput.isVisible();
  const hasLastName = await accountPage.lastNameInput.isVisible();
  const hasEmail = await accountPage.emailInput.isVisible();

  expect(hasDisplayName || hasFirstName || hasLastName || hasEmail).toBeTruthy();
}
