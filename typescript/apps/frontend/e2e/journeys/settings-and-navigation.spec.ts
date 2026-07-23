import { LIST_URL_PATTERNS } from '../constants.ts';
import { expect, test } from '../fixtures/auth.ts';
import { expectNoA11yViolations } from '../helpers/axe-helper.ts';
import { DashboardPage, LicensesPage, SettingsPage } from '../pages/index.ts';

const ERROR_FAILED_RE = /error|failed|unable to load/iu;
const ERROR_STATUS_RE = /error/iu;
const PROFILES_LINK_RE = /profiles/iu;
const BREADCRUMB_RE = /breadcrumb/iu;
const TOGGLE_SIDEBAR_RE = /toggle sidebar/iu;
const NOHIKI_RE = /nohiki/iu;
const SOURCE_LINKEDIN_RE = /source=LINKEDIN/u;
const SORT_DATE_RE = /sort=date/u;

test.describe
  .parallel('Settings and Navigation Journey', () => {
    test('1. User navigates to settings page', async ({ page }) => {
      const settingsPage = new SettingsPage(page);
      await settingsPage.goto();

      await expect(page).toHaveURL('/settings');
    });

    test('2. Settings page loads without errors', async ({ page }) => {
      const settingsPage = new SettingsPage(page);
      await settingsPage.goto();

      const errorIndicator = page
        .getByText(ERROR_FAILED_RE)
        .or(page.getByRole('status', { name: ERROR_STATUS_RE }));

      const hasError = await errorIndicator.isVisible({ timeout: 5000 }).catch(() => false);
      expect(hasError).toBeFalsy();
    });

    test('3. Theme selection is accessible', async ({ page }) => {
      const settingsPage = new SettingsPage(page);
      await settingsPage.goto();

      await expect(settingsPage.appearanceSection).toBeVisible();
      await expect(settingsPage.lightThemeButton).toBeVisible();
      await expect(settingsPage.darkThemeButton).toBeVisible();
      await expect(settingsPage.systemThemeButton).toBeVisible();
    });

    test('4. User navigates to licenses page', async ({ page }) => {
      const licensesPage = new LicensesPage(page);
      await licensesPage.goto();

      await expect(page).toHaveURL('/licenses');
    });

    test('5. Licenses page shows license information', async ({ page }) => {
      const licensesPage = new LicensesPage(page);
      await licensesPage.goto();

      await expect(licensesPage.pageHeading).toBeVisible();
      await expect(licensesPage.licenseSummaryTab).toBeVisible();
      await expect(licensesPage.downloadButton).toBeVisible();
    });
  });

test.describe
  .parallel('Navigation Flow', () => {
    test('sidebar navigation works correctly', async ({ page }) => {
      const dashboardPage = new DashboardPage(page);
      await dashboardPage.goto();

      await dashboardPage.navigateToProfiles();
      await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles);
    });

    test('user menu navigation works', async ({ page }) => {
      const dashboardPage = new DashboardPage(page);
      await dashboardPage.goto();

      await dashboardPage.openUserMenu();

      const menuItems = page.getByRole('menuitem');
      await expect(menuItems.first()).toBeVisible();
    });

    test('breadcrumb navigation works if present', async ({ page }) => {
      await page.goto('/profiles');

      const breadcrumb = page.getByRole('navigation', { name: BREADCRUMB_RE });
      await expect(breadcrumb).toBeVisible();

      // First breadcrumb is app name "Nohiki" rendered as disabled span (not a link)
      await expect(breadcrumb.getByText(NOHIKI_RE)).toBeVisible();
      // Active page appears as the last breadcrumb item
      await expect(breadcrumb.getByText(PROFILES_LINK_RE)).toBeVisible();
    });

    const MOBILE_VIEWPORT_WIDTH = 375;
    const MOBILE_VIEWPORT_HEIGHT = 667;
    test('mobile menu works on small viewports', async ({ page }) => {
      await page.setViewportSize({ width: MOBILE_VIEWPORT_WIDTH, height: MOBILE_VIEWPORT_HEIGHT });

      await page.goto('/');

      const menuButton = page.getByRole('button', { name: TOGGLE_SIDEBAR_RE });
      await menuButton.click();

      const mobileNav = page.locator('[data-sidebar="sidebar"][data-mobile="true"]');
      await expect(mobileNav).toBeVisible({ timeout: 5000 });
    });
  });

test.describe
  .parallel('Theme Switching', () => {
    test('can switch between light and dark theme', async ({ page }) => {
      const settingsPage = new SettingsPage(page);
      await settingsPage.goto();

      await settingsPage.selectDarkTheme();

      const darkTheme = await settingsPage.getCurrentTheme();
      expect(darkTheme).toBe('dark');

      await settingsPage.selectLightTheme();

      const lightTheme = await settingsPage.getCurrentTheme();
      expect(lightTheme).toBe('light');
    });

    test('theme preference persists across navigation', async ({ page }) => {
      const settingsPage = new SettingsPage(page);
      await settingsPage.goto();

      const initialTheme = await settingsPage.getCurrentTheme();

      await page.goto('/profiles');

      const themeAfterNav = await settingsPage.getCurrentTheme();

      expect(themeAfterNav).toBe(initialTheme);
    });

    test('URL search params survive back/forward navigation', async ({ page }) => {
      await page.goto('/jobs?source=LINKEDIN&sort=date');

      await expect(page).toHaveURL(SOURCE_LINKEDIN_RE);

      await page.goto('/profiles');

      await expect(page).toHaveURL('/profiles');

      await page.goBack();

      await expect(page).toHaveURL(SOURCE_LINKEDIN_RE);
      await expect(page).toHaveURL(SORT_DATE_RE);
      await expectNoA11yViolations(page);
    });
  });
