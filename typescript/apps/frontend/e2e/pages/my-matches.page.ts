import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const MATCHES_RE = /matches/iu;
const NO_MATCHES_EMPTY_RE = /no.*matches|empty/iu;
const LOADING_RE = /loading/iu;
const FILTER_PROFILE_RE = /filter|profile/iu;
const SORT_RE = /sort/iu;

export class MyMatchesPage extends BasePage {
  readonly url = '/jobs/matches?minScore=0';

  readonly matchList: Locator;
  readonly emptyState: Locator;
  readonly loadingSpinner: Locator;
  readonly filterDropdown: Locator;
  readonly sortDropdown: Locator;

  constructor(page: Page) {
    super(page);
    this.matchList = page.getByRole('table').or(page.getByRole('list', { name: MATCHES_RE }));
    this.emptyState = page.getByRole('status', { name: NO_MATCHES_EMPTY_RE });
    this.loadingSpinner = page.getByRole('status', { name: LOADING_RE });
    this.filterDropdown = page.getByRole('combobox', { name: FILTER_PROFILE_RE });
    this.sortDropdown = page.getByRole('combobox', { name: SORT_RE });
  }

  async waitForMatchesLoaded(): Promise<void> {
    await this.loadingSpinner.waitFor({ state: 'hidden', timeout: 30_000 });
  }

  async getMatchCount(): Promise<number> {
    await this.waitForMatchesLoaded();
    const isTable = await this.page.getByRole('table').isVisible();
    if (isTable) {
      // Table rows include header + empty-state row; count only data rows with links
      return this.matchList
        .locator('tbody tr')
        .filter({ has: this.page.getByRole('link') })
        .count();
    }
    return this.matchList.getByRole('row').count();
  }

  async clickMatch(jobTitle: string): Promise<void> {
    await this.matchList.getByRole('link', { name: jobTitle }).click();
  }

  getMatchCard(jobTitle: string): Locator {
    return this.matchList.getByRole('row').filter({ hasText: jobTitle });
  }
}
