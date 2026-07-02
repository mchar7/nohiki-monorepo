import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';
import { LIST_URL_PATTERNS, TIMEOUTS } from '../constants.ts';
import { DocumentsPage, GenerateWizardPage } from '../pages/index.ts';

const UPLOAD_RE = /upload/iu;
const FILE_INPUT_SELECTOR = 'input[type="file"]';
const DIALOG_RE = /dialog/iu;

/**
 * Navigate to the Documents hub and wait for content to load.
 * Returns the DocumentsPage POM for further interaction.
 */
async function navigateToDocuments(page: Page): Promise<DocumentsPage> {
  const documentsPage = new DocumentsPage(page);
  await documentsPage.goto();
  await expect(page).toHaveURL(LIST_URL_PATTERNS.documents);
  await documentsPage.waitForDocumentsLoaded();
  return documentsPage;
}

/**
 * Upload a document via the upload dialog on the Documents page.
 * Opens the dialog, sets the file, and waits for the upload button to settle.
 */
async function uploadDocument(page: Page, filePath: string): Promise<DocumentsPage> {
  const documentsPage = await navigateToDocuments(page);

  await documentsPage.clickUploadButton();
  const fileInput = page.locator(FILE_INPUT_SELECTOR);
  await fileInput.setInputFiles(filePath);

  const submitButton = page
    .getByRole('button', { name: UPLOAD_RE })
    .filter({ hasNotText: DIALOG_RE })
    .last();
  const submitVisible = await submitButton.isVisible().catch(() => false);
  if (submitVisible) {
    await submitButton.click();
  }

  return documentsPage;
}

interface GenerateDocumentOptions {
  readonly docType?: string;
  readonly profileName?: string;
  readonly skipMatch?: boolean;
  readonly templateName?: string;
}

/**
 * Walk through the generation wizard steps.
 * Returns the wizard POM positioned at the review/progress stage.
 */
async function generateDocument(
  page: Page,
  options: GenerateDocumentOptions = {},
): Promise<GenerateWizardPage> {
  const wizard = new GenerateWizardPage(page);
  await wizard.goto();

  if (options.docType) {
    await wizard.selectDocType(options.docType);
    await wizard.clickNext();
  }

  if (options.profileName) {
    await wizard.selectProfile(options.profileName);
    await wizard.clickNext();
  }

  if (options.skipMatch !== false) {
    await wizard.skipMatch();
  }

  if (options.templateName) {
    await wizard.selectTemplate(options.templateName);
    await wizard.clickNext();
  }

  return wizard;
}

/**
 * Link a document to a profile via the card action menu.
 * Requires the user to already be on the documents page.
 */
async function linkToProfile(page: Page, documentName: string): Promise<void> {
  const documentsPage = new DocumentsPage(page);
  await documentsPage.linkToProfile(documentName);

  await expect(page.getByRole('dialog').or(page.getByRole('listbox'))).toBeVisible({
    timeout: TIMEOUTS.elementVisible,
  });
}

export type { GenerateDocumentOptions };
export { generateDocument, linkToProfile, navigateToDocuments, uploadDocument };
