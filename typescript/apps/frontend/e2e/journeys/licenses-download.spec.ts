import { readFile } from 'node:fs/promises';

import { expect, test } from '../fixtures/auth.ts';
import { LicensesPage } from '../pages/index.ts';

const LICENSE_CONTENT_RE = /terms and conditions|permission is hereby granted|copyright/iu;

test.describe('Licenses Download Journey', () => {
  test('user downloads third-party license text', async ({ page }) => {
    const licensesPage = new LicensesPage(page);
    await licensesPage.goto();
    await expect(licensesPage.downloadButton).toHaveAttribute('href', '/third-party-licenses.txt');
    await expect(licensesPage.downloadButton).toHaveAttribute(
      'download',
      'third-party-licenses.txt',
    );

    const download = await licensesPage.downloadLicenses();

    expect(download.suggestedFilename()).toBe('third-party-licenses.txt');

    const downloadPath = await download.path();
    expect(downloadPath).not.toBeNull();
    if (downloadPath === null) {
      throw new Error('Playwright did not provide a path for the downloaded license file');
    }

    const content = await readFile(downloadPath, 'utf8');
    expect(content.trim().length).toBeGreaterThan(0);
    expect(content).toMatch(LICENSE_CONTENT_RE);
  });
});
