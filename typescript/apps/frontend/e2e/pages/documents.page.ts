import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const NO_DOCUMENTS_RE = /no documents/iu;
const LOADING_RE = /loading/iu;
const FILTER_STATUS_RE = /status|filter|type/iu;
const SORT_RE = /sort|ascending|descending/iu;
const DOWNLOAD_RE = /download/iu;
const DELETE_REMOVE_RE = /delete|remove/iu;
const CONFIRM_OR_DELETE_RE = /confirm|yes|delete/iu;
const PREVIEW_VIEW_RE = /preview|view/iu;
const LINK_PROFILE_RE = /link.*profile|assign.*profile/iu;
const UPLOAD_RE = /upload/iu;
const REFRESH_RE = /refresh/iu;

const TAB_ALL_RE = /all/iu;
const TAB_UPLOADED_RE = /uploaded/iu;
const TAB_GENERATED_RE = /generated/iu;

export class DocumentsPage extends BasePage {
  readonly url = '/documents';

  readonly documentList: Locator;
  readonly emptyState: Locator;
  readonly loadingSpinner: Locator;
  readonly filterDropdown: Locator;
  readonly sortDropdown: Locator;

  readonly tabAll: Locator;
  readonly tabUploaded: Locator;
  readonly tabGenerated: Locator;
  readonly tabsList: Locator;

  readonly uploadButton: Locator;
  readonly refreshButton: Locator;
  readonly fileInput: Locator;

  constructor(page: Page) {
    super(page);
    this.documentList = page.locator('main');
    this.emptyState = page.getByText(NO_DOCUMENTS_RE);
    this.loadingSpinner = page.getByRole('status', { name: LOADING_RE });
    this.filterDropdown = page
      .getByRole('combobox', { name: FILTER_STATUS_RE })
      .or(page.getByRole('button', { name: FILTER_STATUS_RE }));
    this.sortDropdown = page
      .getByRole('combobox', { name: SORT_RE })
      .or(page.getByRole('button', { name: SORT_RE }));

    this.tabsList = page.getByRole('tablist');
    this.tabAll = page.getByRole('tab', { name: TAB_ALL_RE });
    this.tabUploaded = page.getByRole('tab', { name: TAB_UPLOADED_RE });
    this.tabGenerated = page.getByRole('tab', { name: TAB_GENERATED_RE });

    this.uploadButton = page.getByRole('button', { name: UPLOAD_RE }).first();
    this.refreshButton = page.getByRole('button', { name: REFRESH_RE });
    this.fileInput = page.locator('input[type="file"]');
  }

  async waitForDocumentsLoaded(): Promise<void> {
    const isSpinnerVisible = await this.loadingSpinner.isVisible().catch(() => false);
    if (isSpinnerVisible) {
      await this.loadingSpinner.waitFor({ state: 'hidden', timeout: 30_000 });
    }
    await this.page.waitForLoadState('load');
  }

  async getDocumentCount(): Promise<number> {
    await this.waitForDocumentsLoaded();
    const cards = this.page.locator('[class*="card"]').getByRole('article');
    const tableRows = this.page.locator('table tbody tr');
    const cardCount = await cards.count().catch(() => 0);
    const tableCount = await tableRows.count().catch(() => 0);
    return Math.max(cardCount, tableCount);
  }

  async selectTab(tab: 'all' | 'uploaded' | 'generated'): Promise<void> {
    const tabMap = {
      all: this.tabAll,
      uploaded: this.tabUploaded,
      generated: this.tabGenerated,
    } as const;
    await tabMap[tab].click();
  }

  async clickDocument(name: string): Promise<void> {
    await this.documentList.getByRole('link', { name }).click();
  }

  async downloadDocument(name: string): Promise<void> {
    const card = this.getDocumentCard(name);
    await card
      .getByRole('button', { name: DOWNLOAD_RE })
      .or(card.getByRole('link', { name: DOWNLOAD_RE }))
      .click();
  }

  async previewDocument(name: string): Promise<void> {
    const card = this.getDocumentCard(name);
    await card.getByRole('button', { name: PREVIEW_VIEW_RE }).click();
  }

  async linkToProfile(name: string): Promise<void> {
    const card = this.getDocumentCard(name);
    await card.getByRole('button', { name: LINK_PROFILE_RE }).click();
  }

  async deleteDocument(name: string): Promise<void> {
    const card = this.getDocumentCard(name);
    await card.getByRole('button', { name: DELETE_REMOVE_RE }).click();
    await this.page.getByRole('button', { name: CONFIRM_OR_DELETE_RE }).click();
  }

  getDocumentCard(name: string): Locator {
    return this.documentList.locator('[class*="card"]').filter({ hasText: name });
  }

  async hasDocument(name: string): Promise<boolean> {
    await this.waitForDocumentsLoaded();
    return this.documentList.getByText(name).isVisible();
  }

  async filterByType(type: string): Promise<void> {
    await this.filterDropdown.click();
    await this.page.getByRole('option', { name: type }).click();
  }

  async sortBy(option: string): Promise<void> {
    await this.sortDropdown.click();
    await this.page.getByRole('option', { name: option }).click();
  }

  async uploadFile(filePath: string): Promise<void> {
    await this.fileInput.setInputFiles(filePath);
  }

  async clickUploadButton(): Promise<void> {
    await this.uploadButton.click();
  }

  async clickRefresh(): Promise<void> {
    await this.refreshButton.click();
  }
}
