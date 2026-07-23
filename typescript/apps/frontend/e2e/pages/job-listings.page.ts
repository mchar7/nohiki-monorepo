import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const SEARCH_RE = /search/iu;
const FILTER_RE = /filter/iu;
const JOB_LISTINGS_RE = /job listings/iu;
const NO_JOBS_EMPTY_RE = /no.*jobs|empty/iu;
const LOADING_RE = /loading/iu;
const MATCHES_RE = /matches/iu;

export class JobListingsPage extends BasePage {
  readonly url = '/jobs';

  readonly searchInput: Locator;
  readonly filterButton: Locator;
  readonly jobList: Locator;
  readonly emptyState: Locator;
  readonly loadingSpinner: Locator;
  readonly matchesLink: Locator;

  constructor(page: Page) {
    super(page);
    this.searchInput = page.getByPlaceholder(SEARCH_RE);
    this.filterButton = page.getByRole('button', { name: FILTER_RE });
    this.jobList = page.getByRole('list', { name: JOB_LISTINGS_RE });
    this.emptyState = page.getByRole('status', { name: NO_JOBS_EMPTY_RE });
    this.loadingSpinner = page.getByRole('status', { name: LOADING_RE });
    this.matchesLink = page.getByRole('link', { name: MATCHES_RE });
  }

  async waitForJobsLoaded(): Promise<void> {
    // Wait for either job list content or explicit empty state to appear
    await this.jobList.or(this.emptyState).waitFor({ state: 'visible', timeout: 30_000 });
  }

  async getJobCount(): Promise<number> {
    await this.waitForJobsLoaded();
    return this.jobList.getByRole('article').count();
  }

  async clickJob(title: string): Promise<void> {
    await this.jobList.getByRole('link', { name: title }).click();
  }

  async searchJobs(query: string): Promise<void> {
    await this.searchInput.fill(query);
    // Wait for the URL to reflect the search query after the debounce settles
    await this.page.waitForURL((url) => url.search.includes('q='), { timeout: 5000 });
  }

  async navigateToMatches(): Promise<void> {
    await this.matchesLink.click();
  }

  getJobCard(title: string): Locator {
    return this.jobList.getByRole('article').filter({ hasText: title });
  }
}
