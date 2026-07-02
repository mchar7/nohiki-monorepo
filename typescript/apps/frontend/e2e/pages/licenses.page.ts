import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const OPEN_SOURCE_LICENSES_RE = /open source licenses/iu;
const LICENSE_SUMMARY_RE = /license summary/iu;
const FULL_LICENSE_TEXTS_RE = /full license texts/iu;
const DOWNLOAD_LICENSE_RE = /download.*license/iu;

export class LicensesPage extends BasePage {
  readonly url = '/licenses';

  readonly pageHeading: Locator;
  readonly licenseSummaryTab: Locator;
  readonly fullLicenseTextsTab: Locator;
  readonly downloadButton: Locator;

  constructor(page: Page) {
    super(page);
    this.pageHeading = page.getByRole('heading', { name: OPEN_SOURCE_LICENSES_RE });
    this.licenseSummaryTab = page.getByRole('tab', { name: LICENSE_SUMMARY_RE });
    this.fullLicenseTextsTab = page.getByRole('tab', { name: FULL_LICENSE_TEXTS_RE });
    this.downloadButton = page.getByRole('button', { name: DOWNLOAD_LICENSE_RE });
  }

  async switchToFullLicenseTexts(): Promise<void> {
    await this.fullLicenseTextsTab.click();
  }

  async switchToLicenseSummary(): Promise<void> {
    await this.licenseSummaryTab.click();
  }
}
