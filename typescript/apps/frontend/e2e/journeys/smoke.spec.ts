import { APP_PATHS, LIST_URL_PATTERNS, REGEX_PATTERNS, TIMEOUTS } from '../constants.ts';
import { expect, test } from '../fixtures/auth.ts';
import { expectNoA11yViolations } from '../helpers/axe-helper.ts';

test.describe('Smoke Test', () => {
  test('authenticated user can access dashboard', async ({ page }) => {
    await page.goto(APP_PATHS.home);
    await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl);
    // Use accessible selector: Dashboard heading indicates authenticated access
    await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible({
      timeout: TIMEOUTS.elementVisible,
    });
  });

  test('can navigate to profiles page', async ({ page }) => {
    await page.goto(APP_PATHS.profiles);
    await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles);
    await expectNoA11yViolations(page);
  });
});
