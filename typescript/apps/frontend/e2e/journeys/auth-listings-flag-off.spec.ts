import { expect, test } from '@playwright/test';

import { E2E_CONFIG } from '../constants.ts';

/**
 * Verifies that the auth page renders normally when the auth-listings
 * feature flag is disabled. The default Playwright server explicitly sets
 * `VITE_FEATURE_AUTH_LISTINGS=false`; the feature-on lane skips this spec.
 *
 * Anchored on the presence of the inline `<style>` element that only the
 * listings canvas injects, which avoids matching the purely presentational
 * radial vignette overlay that shares the canvas's CSS classes.
 */

const AUTH_PATH = '/auth/login';
const CANVAS_LOCATOR = 'div[aria-hidden="true"].fixed.inset-0:has(> style)';

test.skip(E2E_CONFIG.authListingsLane === 'on', 'Incompatible with the feature-on lane');

test.use({ storageState: { cookies: [], origins: [] } });

test('auth page omits the listings canvas when the feature flag is off', async ({
  page,
}, testInfo) => {
  await page.goto(AUTH_PATH);

  // Login form must always be present.
  await expect(page.locator('form').first()).toBeVisible();

  // Canvas must be completely absent from the DOM.
  await expect(page.locator(CANVAS_LOCATOR)).toHaveCount(0);

  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach('flag-off.png', { body: screenshot, contentType: 'image/png' });
});
