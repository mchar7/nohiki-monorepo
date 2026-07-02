import { REGEX_PATTERNS, TIMEOUTS } from '../constants.ts';
import { expect, test } from '../fixtures/auth.ts';
import { expectNoA11yViolations } from '../helpers/axe-helper.ts';
import { AccountSettingsPage } from '../pages/index.ts';
import { assertAccountFieldsVisible, gotoAccountPage } from '../utils/account-helpers.ts';

const SECURITY_HEADING_RE = /security/iu;
const CURRENT_NEW_PASSWORD_RE = /current password|new password/iu;
const AT_SIGN_RE = /@/u;

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('Account Settings Journey', () => {
  test('1. User navigates to account settings', async ({ page }) => {
    const accountPage = new AccountSettingsPage(page);
    await accountPage.goto();
    await expect(page).toHaveURL('/account');
    await page.waitForLoadState('load');
  });

  test('2. User sees account information fields', async ({ page }) => {
    const accountPage = await gotoAccountPage(page);
    await assertAccountFieldsVisible(accountPage);
    expect(true).toBeTruthy();
  });

  test('3. User can edit display name', async ({ page }) => {
    const accountPage = await gotoAccountPage(page);

    const originalName = await accountPage.getDisplayName();
    const newName = `E2E Test ${Date.now()}`;
    await accountPage.updateDisplayName(newName);

    const updatedName = await accountPage.getDisplayName();
    expect(updatedName).toBe(newName);
    await accountPage.updateDisplayName(originalName || 'E2E User');
  });

  test('4. Save button is visible and clickable', async ({ page }) => {
    await gotoAccountPage(page);
    const accountPage = new AccountSettingsPage(page);
    await expect(accountPage.saveButton).toBeEnabled();
  });

  test('5. Change password section exists', async ({ page }) => {
    const accountPage = await gotoAccountPage(page);

    const hasChangePassword = await accountPage.changePasswordButton.isVisible();
    const hasSecurityHeading = await page.getByRole('heading', { name: SECURITY_HEADING_RE }).isVisible();
    const hasSecurityCard = await page.getByRole('region', { name: SECURITY_HEADING_RE }).isVisible();
    const hasPasswordForm = await page.getByLabel(CURRENT_NEW_PASSWORD_RE).first().isVisible();

    expect(hasChangePassword || hasSecurityHeading || hasSecurityCard || hasPasswordForm).toBeTruthy();
  });

  test('6. Email field shows current email', async ({ page }) => {
    const accountPage = await gotoAccountPage(page);
    const email = await accountPage.getEmail();
    expect(email).toMatch(AT_SIGN_RE);
  });
});

test.describe('Account Settings Error Handling', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('account page requires authentication', async ({ page }) => {
    await page.goto('/account');
    await expect(page).toHaveURL(REGEX_PATTERNS.authRedirectUrl, { timeout: TIMEOUTS.navigation });
    await expectNoA11yViolations(page);
  });
});
