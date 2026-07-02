import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { REGEX_PATTERNS, TIMEOUTS } from '../constants.ts';
import { LoginPage, ProfilesPage } from '../pages/index.ts';

/** Log in and navigate to the profiles page. */
export async function loginAndGoToProfiles(
  page: Page,
  email: string,
  password: string,
): Promise<ProfilesPage> {
  const loginPage = new LoginPage(page);
  await loginPage.goto();
  await loginPage.login(email, password);
  await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl, { timeout: TIMEOUTS.elementVisible });

  const profilesPage = new ProfilesPage(page);
  await profilesPage.goto();
  await page.waitForLoadState('load');
  return profilesPage;
}
