import { expect, test } from '@playwright/test';

import { expectNoA11yViolations } from '../helpers/axe-helper.ts';

test.use({ storageState: { cookies: [], origins: [] } });

test('unauthenticated login page has no serious accessibility violations', async ({ page }) => {
  await page.goto('/auth/login');
  await expect(page.locator('form').first()).toBeVisible();
  await expectNoA11yViolations(page);
});
