import { expect, test } from '@playwright/test';
import { LIST_URL_PATTERNS, REGEX_PATTERNS, TIMEOUTS } from '../constants.ts';
import { expectNoA11yViolations } from '../helpers/axe-helper.ts';
import { DashboardPage, ProfileCreatePage, RegisterPage } from '../pages/index.ts';
import { waitForTextOnPage } from '../utils/index.ts';
import { loginAndGoToProfiles } from '../utils/onboarding-helpers.ts';

test.use({ storageState: { cookies: [], origins: [] } });

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('New User Onboarding - Registration', () => {
  let userEmail: string;
  let userPassword: string;
  let profileName: string;

  test.beforeAll(() => {
    const timestamp = Date.now();
    userEmail = `e2e-newuser-${timestamp}@example.com`;
    userPassword = 'NewUserP@ss123!';
    profileName = `My First Profile ${timestamp}`;
  });

  test('1. New user registers successfully', async ({ page }) => {
    const registerPage = new RegisterPage(page);
    await registerPage.goto();
    await registerPage.register({ email: userEmail, password: userPassword, displayName: 'New User' });
    await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl, { timeout: TIMEOUTS.navigation });
  });

  test('2. New user sees empty profiles', async ({ page }) => {
    const profilesPage = await loginAndGoToProfiles(page, userEmail, userPassword);
    const profileCount = await profilesPage.getProfileCount();
    expect(profileCount).toBe(0);
  });

  test('3. New user creates their first profile', async ({ page }) => {
    const profilesPage = await loginAndGoToProfiles(page, userEmail, userPassword);
    await profilesPage.clickCreateProfile();

    const createPage = new ProfileCreatePage(page);
    await createPage.fillAndSubmit({
      name: profileName,
      keywords: ['JavaScript', 'SQL', 'PostgreSQL'],
    });
    await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles, { timeout: 30_000 });
  });

  const LOGOUT_LOGIN_TIMEOUT_MS = 120_000;
  test('4. New user can log out and log back in', async ({ page }) => {
    test.setTimeout(LOGOUT_LOGIN_TIMEOUT_MS);
    await loginAndGoToProfiles(page, userEmail, userPassword);

    const dashboardPage = new DashboardPage(page);
    await dashboardPage.logout();
    await expect(page).toHaveURL(REGEX_PATTERNS.authRedirectUrl, { timeout: TIMEOUTS.elementVisible });

    await loginAndGoToProfiles(page, userEmail, userPassword);
    await waitForTextOnPage(page, profileName);
    await expectNoA11yViolations(page);
  });
});
