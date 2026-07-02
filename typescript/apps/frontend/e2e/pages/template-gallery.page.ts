import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const SEARCH_RE = /search/iu;
const USE_TEMPLATE_RE = /use template/iu;
const CUSTOMIZE_RE = /customize/iu;
const RETRY_RE = /retry/iu;
const NO_TEMPLATES_RE = /no templates/iu;

export class TemplateGalleryPage extends BasePage {
  readonly url = '/documents/templates';

  readonly searchInput: Locator;
  readonly templateGrid: Locator;
  readonly retryButton: Locator;

  constructor(page: Page) {
    super(page);
    this.searchInput = page
      .getByRole('searchbox', { name: SEARCH_RE })
      .or(page.locator('input[type="search"]'));
    this.templateGrid = page.locator('.grid');
    this.retryButton = page.getByRole('button', { name: RETRY_RE });
  }

  async search(query: string): Promise<void> {
    await this.searchInput.fill(query);
  }

  async clearSearch(): Promise<void> {
    await this.searchInput.clear();
  }

  getTemplateCard(name: string): Locator {
    return this.templateGrid.locator('[class*="card"]').filter({ hasText: name });
  }

  getTemplateCount(): Promise<number> {
    return this.templateGrid.locator('[class*="card"]').count();
  }

  async clickUseTemplate(templateName: string): Promise<void> {
    const card = this.getTemplateCard(templateName);
    await card.getByRole('link', { name: USE_TEMPLATE_RE }).click();
  }

  async clickCustomize(templateName: string): Promise<void> {
    const card = this.getTemplateCard(templateName);
    await card.getByRole('link', { name: CUSTOMIZE_RE }).click();
  }

  getEmptyState(): Locator {
    return this.page
      .locator('[class*="empty"], [data-slot="empty"]')
      .or(this.page.getByText(NO_TEMPLATES_RE));
  }

  hasTemplate(name: string): Promise<boolean> {
    return this.getTemplateCard(name).isVisible();
  }
}
