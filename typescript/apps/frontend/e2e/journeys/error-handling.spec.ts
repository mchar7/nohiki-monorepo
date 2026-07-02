import { REGEX_PATTERNS, TIMEOUTS } from '../constants.ts';
import { expect, test } from '../fixtures/auth.ts';
import { expectNoA11yViolations } from '../helpers/axe-helper.ts';
import { LoginPage } from '../pages/index.ts';

const PAGE_NOT_FOUND_RE = /page not found/iu;
const GO_HOME_RE = /go.*dashboard|go.*home/iu;

test.describe('Error Handling Scenarios', () => {
  test.describe('Unauthenticated', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('invalid login shows error message', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      await loginPage.login('nonexistent@example.com', 'wrongpassword123');

      await expect(loginPage.errorMessage).toBeVisible({ timeout: TIMEOUTS.shortAction });
    });

    test('accessing protected route without auth redirects to login', async ({ page }) => {
      await page.goto('/profiles');

      await expect(page).toHaveURL(REGEX_PATTERNS.authRedirectUrl, {
        timeout: TIMEOUTS.navigation,
      });
    });
  });

  test.describe('Authenticated', () => {
    test('404 page for non-existent route', async ({ page }) => {
      await page.goto('/non-existent-route-12345');
      await page.waitForLoadState('load');

      const mainLandmark = page.getByRole('main', { name: PAGE_NOT_FOUND_RE });
      await expect(mainLandmark).toBeVisible({ timeout: TIMEOUTS.elementVisible });

      const heading = page.getByRole('heading', { level: 1, name: PAGE_NOT_FOUND_RE });
      await expect(heading).toBeVisible();

      const homeLink = page.getByRole('link', { name: GO_HOME_RE });
      await expect(homeLink).toBeVisible();
      await expect(homeLink).toHaveAttribute('href', '/');
      await expectNoA11yViolations(page);
    });
  });
});
