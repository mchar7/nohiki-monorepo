import { expect, test } from '../fixtures/auth.ts';
import { expectNoA11yViolations } from '../helpers/axe-helper';

const TEMPLATE_STUDIO_HEADING_RE = /template studio/iu;
const VALIDATE_TEMPLATE_RE = /validate template/iu;
const TEMPLATE_NAME_INPUT_RE = /template name/iu;
// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('Template Studio Workflow Journey', () => {
  test('1. User navigates to template studio', async ({ page }) => {
    await page.goto('/documents/templates/studio');
    await expect(page).toHaveURL('/documents/templates/studio');
    await page.waitForLoadState('load');
  });

  test('2. User can view template studio editor', async ({ page }) => {
    await page.goto('/documents/templates/studio');
    await page.waitForLoadState('load');

    const pageHeading = page.getByRole('heading', { name: TEMPLATE_STUDIO_HEADING_RE });
    const validateButton = page.getByRole('button', { name: VALIDATE_TEMPLATE_RE });
    const templateNameInput = page.getByRole('textbox', { name: TEMPLATE_NAME_INPUT_RE });

    await expect(pageHeading).toBeVisible();
    await expect(validateButton).toBeVisible();
    await expect(templateNameInput).toBeVisible();
  });

  test('3. User can browse the template gallery', async ({ page }) => {
    await page.goto('/documents/templates');
    await expect(page).toHaveURL('/documents/templates');
    await page.waitForLoadState('load');
    await expect(page.getByRole('heading', { name: /^templates$/iu, level: 1 })).toBeVisible();
    await expect(page.getByRole('searchbox', { name: /search templates/iu })).toBeVisible();
  });

  test('4. User can access the generate wizard', async ({ page }) => {
    await page.goto('/documents/generate');
    await expect(page).toHaveURL(/\/documents\/generate/u);
    await page.waitForLoadState('load');
    await expect(page.getByRole('heading', { name: /generate document/iu })).toBeVisible();
    await expectNoA11yViolations(page);
  });
});
