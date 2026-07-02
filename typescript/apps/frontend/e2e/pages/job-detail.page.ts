import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const APPLY_RE = /apply/iu;
const BACK_RE = /back/iu;
const SKILLS_RE = /skills/iu;

export class JobDetailPage extends BasePage {
  readonly url = '/jobs';

  readonly jobTitle: Locator;
  readonly companyName: Locator;
  readonly description: Locator;
  readonly applyButton: Locator;
  readonly backButton: Locator;
  readonly matchScore: Locator;
  readonly skillsList: Locator;

  constructor(page: Page) {
    super(page);
    this.jobTitle = page.getByRole('heading', { level: 1 });
    this.companyName = page
      .getByRole('heading', { level: 2 })
      .or(page.locator('[aria-label*="company"]'));
    this.description = page.getByRole('article').or(page.locator('[aria-label*="description"]'));
    this.applyButton = page.getByRole('link', { name: APPLY_RE });
    this.backButton = page.getByRole('button', { name: BACK_RE });
    this.matchScore = page.locator('[aria-label*="match score"]');
    this.skillsList = page.getByRole('list', { name: SKILLS_RE });
  }

  async gotoJob(listingId: string): Promise<void> {
    await this.page.goto(`/jobs/${listingId}`);
    await this.waitForPageLoad();
  }

  async goBack(): Promise<void> {
    await this.backButton.click();
  }
}
