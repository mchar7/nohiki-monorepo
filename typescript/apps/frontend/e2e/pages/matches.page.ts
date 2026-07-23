import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const TOTAL_RE = /total/iu;
const HIGH_QUALITY_RE = /high quality/iu;
const NEW_THIS_WEEK_RE = /new this week/iu;
const SAVED_RE = /saved/iu;
const PROFILE_FILTER_RE = /profile|filter/iu;
const SCORE_RE = /score/iu;
const MIN_SCORE_RE = /minimum.*score/iu;
const CLEAR_RESET_RE = /clear|reset/iu;
const NO_MATCHES_EMPTY_RE = /no.*matches|empty/iu;
const LOADING_RE = /loading/iu;
const LIKE_THUMBS_UP_RE = /like|thumbs.*up/iu;
const DISLIKE_THUMBS_DOWN_RE = /dislike|thumbs.*down/iu;
const PERCENT_SIGN_RE = /%/u;

export class MatchesListPage extends BasePage {
  readonly url = '/jobs/matches?minScore=0';

  readonly statsCards: Locator;
  readonly totalMatchesStat: Locator;
  readonly highQualityStat: Locator;
  readonly newThisWeekStat: Locator;
  readonly savedStat: Locator;

  readonly profileFilter: Locator;
  readonly minScoreFilter: Locator;
  readonly clearFiltersButton: Locator;

  readonly matchesTable: Locator;
  readonly matchRows: Locator;
  readonly emptyState: Locator;
  readonly loadingState: Locator;

  constructor(page: Page) {
    super(page);
    // Scoped to main: a sidebar brand link also carries .grid and must not match
    this.statsCards = page.locator('main .grid.gap-4').first();
    this.totalMatchesStat = page.getByText(TOTAL_RE).locator('..');
    this.highQualityStat = page.getByText(HIGH_QUALITY_RE).locator('..');
    this.newThisWeekStat = page.getByText(NEW_THIS_WEEK_RE).locator('..');
    this.savedStat = page.getByText(SAVED_RE).locator('..');

    this.profileFilter = page.getByRole('combobox', { name: PROFILE_FILTER_RE });
    this.minScoreFilter = page
      .getByRole('slider', { name: SCORE_RE })
      .or(page.getByLabel(MIN_SCORE_RE));
    this.clearFiltersButton = page.getByRole('button', { name: CLEAR_RESET_RE });

    this.matchesTable = page.getByRole('table');
    this.matchRows = page.locator('tbody tr');
    this.emptyState = page.getByRole('status', { name: NO_MATCHES_EMPTY_RE });
    this.loadingState = page.getByRole('status', { name: LOADING_RE });
  }

  async waitForMatchesLoaded(): Promise<void> {
    await this.loadingState.waitFor({ state: 'hidden', timeout: 30_000 }).catch(() => {
      // Spinner may not appear if data loads immediately
    });
  }

  async getMatchCount(): Promise<number> {
    await this.waitForMatchesLoaded();
    return this.dataRows().count();
  }

  /** Rows linking to a match detail; excludes the empty-state row, whose CTA links elsewhere. */
  dataRows(): Locator {
    return this.matchRows.filter({ has: this.page.locator('a[href*="/jobs/matches/"]') });
  }

  async filterByProfile(profileName: string): Promise<void> {
    await this.profileFilter.click();
    await this.page.getByRole('option', { name: profileName }).click();
  }

  async setMinScoreFilter(score: number): Promise<void> {
    await this.minScoreFilter.fill(String(score));
  }

  async clearFilters(): Promise<void> {
    if (await this.clearFiltersButton.isVisible()) {
      await this.clearFiltersButton.click();
    }
  }

  async clickMatch(index: number): Promise<void> {
    await this.dataRows().nth(index).locator('a[href*="/jobs/matches/"]').first().click();
  }

  async clickMatchByTitle(title: string): Promise<void> {
    await this.matchRows.filter({ hasText: title }).first().click();
  }

  async getMatchScore(index: number): Promise<string> {
    const row = this.matchRows.nth(index);
    const scoreCell = row.getByText(PERCENT_SIGN_RE);
    return (await scoreCell.textContent()) ?? '';
  }

  async likeMatch(index: number): Promise<void> {
    const row = this.matchRows.nth(index);
    const likeBtn = row.getByRole('button', { name: LIKE_THUMBS_UP_RE });
    await likeBtn.click();
  }

  async dislikeMatch(index: number): Promise<void> {
    const row = this.matchRows.nth(index);
    const dislikeBtn = row.getByRole('button', { name: DISLIKE_THUMBS_DOWN_RE });
    await dislikeBtn.click();
  }
}
