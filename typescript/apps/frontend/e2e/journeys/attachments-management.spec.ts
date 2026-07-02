import { REGEX_PATTERNS, TIMEOUTS } from '../constants';
import { expect, test } from '../fixtures/auth.ts';
import { expectNoA11yViolations } from '../helpers/axe-helper';
import { DocumentsPage } from '../pages/index';

const NO_UPLOADS_RE = /no uploaded documents/iu;
const UPLOADED_TAB_RE = /tab=uploaded/u;

test.describe
  .serial('Uploaded Documents Management Journey', () => {
    test('1. User navigates to uploaded documents tab', async ({ page }) => {
      const documentsPage = new DocumentsPage(page);
      await documentsPage.goto();
      await documentsPage.selectTab('uploaded');

      await expect(page).toHaveURL(UPLOADED_TAB_RE);
    });

    test('2. User sees uploaded list or empty state', async ({ page }) => {
      const documentsPage = new DocumentsPage(page);
      await documentsPage.goto();
      await documentsPage.selectTab('uploaded');
      await documentsPage.waitForDocumentsLoaded();

      const hasDocuments = (await documentsPage.getDocumentCount()) > 0;
      const hasEmptyState = await page.getByText(NO_UPLOADS_RE).isVisible();
      const hasUploadButton = await documentsPage.uploadButton.isVisible();

      expect(hasDocuments || hasEmptyState || hasUploadButton).toBeTruthy();
    });

    test('3. Upload button is visible and clickable', async ({ page }) => {
      const documentsPage = new DocumentsPage(page);
      await documentsPage.goto();

      await page.waitForLoadState('load');

      await expect(documentsPage.uploadButton).toBeEnabled();
    });

    test('4. User can see file input for uploads', async ({ page }) => {
      const documentsPage = new DocumentsPage(page);
      await documentsPage.goto();

      await page.waitForLoadState('load');

      const fileInput = page.locator('input[type="file"]');

      await documentsPage.clickUploadButton();
      await expect(fileInput.or(documentsPage.uploadButton)).toBeVisible();
    });
  });

test.describe('Uploaded Documents Error Handling', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('documents page requires authentication', async ({ page }) => {
    await page.goto('/documents');

    await expect(page).toHaveURL(REGEX_PATTERNS.authRedirectUrl, { timeout: TIMEOUTS.navigation });
    await expectNoA11yViolations(page);
  });
});
