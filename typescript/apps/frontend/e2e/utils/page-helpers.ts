import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

const DEFAULT_PROJECTION_TIMEOUT = 90_000;
const DEFAULT_POLL_INTERVAL = 3000;
const MIN_FINAL_WAIT_MS = 5000;

/**
 * Poll a page with reloads until an element matching the given text becomes visible.
 *
 * Handles CQRS projection delays in E2E tests where a fresh browser session
 * hits the server before the read model is updated. Reloads the page at
 * intervals until the element appears or the timeout is exceeded.
 */
export async function waitForTextOnPage(
  page: Page,
  text: string,
  options: { timeout?: number; interval?: number } = {},
): Promise<void> {
  const { timeout = DEFAULT_PROJECTION_TIMEOUT, interval = DEFAULT_POLL_INTERVAL } = options;

  // Use Playwright's built-in polling - reload on each failed visibility check until timeout
  await expect(async () => {
    const isVisible = await page
      .getByText(text)
      .isVisible()
      .catch(() => false);
    if (!isVisible) {
      await page.reload();

      throw new Error(`Text "${text}" not yet visible - retrying after reload`);
    }
  }).toPass({
    intervals: [interval],
    timeout: Math.max(timeout - MIN_FINAL_WAIT_MS, interval),
  });

  // Final assertion with remaining timeout to surface a clear failure message
  await expect(page.getByText(text)).toBeVisible({
    timeout: MIN_FINAL_WAIT_MS,
  });
}
