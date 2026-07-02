import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const NEXT_RE = /next/iu;
const BACK_RE = /back/iu;
const GENERATE_RE = /generate/iu;
const SKIP_RE = /skip/iu;
const STEP_PROGRESS_RE = /progress/iu;

export class GenerateWizardPage extends BasePage {
  readonly url = '/documents/generate';

  readonly stepIndicator: Locator;
  readonly nextButton: Locator;
  readonly backButton: Locator;
  readonly generateButton: Locator;

  constructor(page: Page) {
    super(page);
    this.stepIndicator = page.getByRole('navigation', { name: STEP_PROGRESS_RE });
    this.nextButton = page.getByRole('button', { name: NEXT_RE });
    this.backButton = page.getByRole('button', { name: BACK_RE });
    this.generateButton = page.getByRole('button', { name: GENERATE_RE });
  }

  async gotoWithTemplate(templateId: string): Promise<void> {
    await this.page.goto(`${this.url}?templateId=${templateId}`);
    await this.waitForPageLoad();
  }

  getStepByNumber(stepNumber: number): Locator {
    return this.stepIndicator.locator('li').nth(stepNumber - 1);
  }

  getCurrentStepSection(): Locator {
    return this.page.locator('section[aria-label]');
  }

  async selectDocType(name: string): Promise<void> {
    await this.page.getByRole('radio', { name }).click();
  }

  async selectProfile(name: string): Promise<void> {
    await this.page.getByRole('radio', { name }).click();
  }

  async selectMatch(name: string): Promise<void> {
    await this.page.getByRole('button', { name }).or(this.page.getByText(name)).click();
  }

  async skipMatch(): Promise<void> {
    const skipButton = this.page.getByRole('button', { name: SKIP_RE });
    const isVisible = await skipButton.isVisible().catch(() => false);
    if (isVisible) {
      await skipButton.click();
    } else {
      await this.clickNext();
    }
  }

  async selectTemplate(name: string): Promise<void> {
    await this.page.getByRole('radio', { name }).click();
  }

  async clickNext(): Promise<void> {
    await this.nextButton.click();
  }

  async clickBack(): Promise<void> {
    await this.backButton.click();
  }

  async clickGenerate(): Promise<void> {
    await this.generateButton.click();
  }

  getProgressView(): Locator {
    return this.page.locator('[class*="progress"]').or(this.page.getByRole('progressbar'));
  }
}
