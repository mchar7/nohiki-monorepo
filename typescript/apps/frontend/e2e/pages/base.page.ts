import type { Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { SELECTORS, TIMEOUTS } from '../constants.ts';

const CLOSE_DISMISS_RE = /close|dismiss/iu;

export abstract class BasePage {
  protected readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  abstract readonly url: string;

  async goto(): Promise<void> {
    await this.page.goto(this.url);
    await this.waitForPageLoad();
  }

  async waitForPageLoad(): Promise<void> {
    // Wait for networkidle instead of just 'load'. This SPA has multiple
    // async initialization layers (i18n HTTP bundles, IndexedDB store init,
    // React Suspense resolution, TanStack Query prefetches) that fire after
    // the DOM 'load' event. Interacting with React controlled inputs before
    // these async cycles complete causes fill() to silently lose values
    // when React re-renders with fresh state.
    // biome-ignore lint/nursery/noPlaywrightNetworkidle: SPA has async init layers (i18n, IndexedDB, React Suspense, TanStack Query) that fire after 'load'; networkidle ensures fill() doesn't lose values to React re-renders
    await this.page.waitForLoadState('networkidle');
  }

  getByTestId(testId: string): Locator {
    return this.page.getByTestId(testId);
  }

  get toastLocator(): Locator {
    return this.page.locator(SELECTORS.classes.toast).first();
  }

  async getToastMessage(): Promise<string> {
    await expect(this.toastLocator).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    const content = await this.toastLocator.textContent();
    return content ?? '';
  }

  async waitForToast(text: string | RegExp): Promise<void> {
    await this.page
      .locator(SELECTORS.classes.toast)
      .filter({ hasText: text })
      .waitFor({ timeout: TIMEOUTS.elementVisible });
  }

  async dismissToast(): Promise<void> {
    await expect(this.toastLocator).toBeVisible();
    const closeButton = this.toastLocator.getByRole('button', { name: CLOSE_DISMISS_RE });
    await closeButton.click();
  }
}
