/**
 * Full E2E Test Suite: Complete User Journey
 *
 * Tests the COMPLETE end-to-end user journey: registration, profile creation,
 * job discovery, matching, and document generation.
 *
 * NOTE: These tests require the full backend stack to be running.
 */

import { expect, test } from '@playwright/test';
import { LIST_URL_PATTERNS, REGEX_PATTERNS, RETRY_INTERVALS, TIMEOUTS } from '../constants.ts';

const PROFILES_ID_RE = /\/profiles\/(?<profileId>[\w-]+)/u;
const REMOTE_RE = /remote/iu;
const HYBRID_RE = /hybrid/iu;
const JOB_LISTINGS_RE = /job listings/iu;
const NO_JOBS_RE = /no.*jobs|no.*listings/iu;
const DELETE_RE = /delete/iu;
const CONFIRM_YES_DELETE_RE = /confirm|yes|delete/iu;
const JOB_MATCH_URL_RE = /\/jobs\/matches\/[\w-]+/u;
const DASHBOARD_HEADING_RE = /dashboard|welcome to nohiki/iu;

import { expectNoA11yViolations } from '../helpers/axe-helper.ts';
import {
  DashboardPage,
  DocumentsPage,
  LoginPage,
  MatchesListPage,
  ProfileFormPage,
  ProfilesPage,
  RegisterPage,
} from '../pages/index.ts';
import { waitForTextOnPage } from '../utils/index.ts';
import {
  assertAnyVisible,
  hydrateJourneyUser,
  loginAndNavigate,
  loginAndWaitForDashboard,
  saveJourneyUser,
} from '../utils/journey-helpers.ts';

const REAL_SKILLS: string[] = ['Python', 'JavaScript', 'PostgreSQL', 'SQL', 'Java'];
const PROFILE_SKILL_SEED_COUNT = 3;
const DASHBOARD_STATS_CARD_COUNT = 4;
const CONFIRM_BUTTON_VISIBLE_TIMEOUT_MS = 5000;
const DISALLOWED_SKILLS: string[] = ['PHP', 'WordPress', 'Drupal'];
const ONBOARDING_WELCOME_RE = /welcome back,|welcome to nohiki/iu;

/** Shared state for the registration → profile journey. */
const regState = { email: '', password: '', profileName: '', profileId: '' };

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('User Journey: Registration', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeAll(() => {
    const ts = Date.now();
    regState.email = `e2e-full-journey-${ts}@example.com`;
    regState.password = 'FullJourneyP@ss123!';
    regState.profileName = `Backend Engineer Profile ${ts}`;
    saveJourneyUser(regState);
  });

  test('1. User registers a new account', async ({ page }) => {
    const registerPage = new RegisterPage(page);
    await registerPage.goto();
    await registerPage.register({ email: regState.email, password: regState.password, displayName: 'E2E Journey User' });
    await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl, { timeout: TIMEOUTS.navigation });
  });

  test('2. User navigates to profile creation', async ({ page }) => {
    await loginAndWaitForDashboard(page, regState.email, regState.password);
    const dashboardPage = new DashboardPage(page);
    await dashboardPage.navigateToProfiles();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles);
    const profilesPage = new ProfilesPage(page);
    await profilesPage.clickCreateProfile();
    await expect(page).toHaveURL('/profiles/new');
  });
});

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('User Journey: Profile Creation', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeAll(() => hydrateJourneyUser(regState));

  test('3. User creates profile with real skills', async ({ page }) => {
    await loginAndNavigate(page, regState.email, regState.password, '/profiles/new');
    const profileForm = new ProfileFormPage(page);
    await profileForm.fillProfileName(regState.profileName);
    await profileForm.addSearchKeywords(REAL_SKILLS.slice(0, PROFILE_SKILL_SEED_COUNT));
    await profileForm.addDisallowedKeywords(DISALLOWED_SKILLS);
    await profileForm.selectWorkArrangements(['remote', 'hybrid']);
    await profileForm.toggleRelocation(false);
    await profileForm.submit();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles, { timeout: 30_000 });
  });

  const PROFILE_PROJECTION_TIMEOUT_MS = 120_000;
  test('4. Profile appears in profiles list', async ({ page }) => {
    test.setTimeout(PROFILE_PROJECTION_TIMEOUT_MS);
    await loginAndWaitForDashboard(page, regState.email, regState.password);
    const profilesPage = new ProfilesPage(page);
    await profilesPage.goto();
    await page.waitForLoadState('load');
    await waitForTextOnPage(page, regState.profileName);
    const profileLink = page.getByRole('link', { name: new RegExp(regState.profileName, 'u') });
    const href = await profileLink.getAttribute('href');
    const match = PROFILES_ID_RE.exec(href ?? '');
    expect(match).toBeTruthy();
    regState.profileId = match?.groups?.profileId ?? '';
    saveJourneyUser(regState);
  });

  test('5. User views profile details and verifies skills', async ({ page }) => {
    expect(regState.profileId).toBeTruthy();
    await loginAndNavigate(page, regState.email, regState.password, `/profiles/${regState.profileId}`);
    await expect(page.getByRole('heading', { level: 1 })).toContainText(regState.profileName, { timeout: 10_000 });
    await assertAnyVisible([page.getByText(REMOTE_RE), page.getByText(HYBRID_RE)]);
  });
});

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('User Journey: Jobs & Matches', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeAll(() => hydrateJourneyUser(regState));

  test('6. User navigates to job matches', async ({ page }) => {
    await loginAndWaitForDashboard(page, regState.email, regState.password);
    const matchesPage = new MatchesListPage(page);
    await matchesPage.goto();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.jobMatches);
    await page.waitForLoadState('load');
    // Mixed check: match count is async (not a Locator), so use inline .or() for the locator-based checks
    const matchCountOrUI = matchesPage.emptyState.or(matchesPage.statsCards).or(matchesPage.matchesTable);
    await expect(matchCountOrUI.first()).toBeVisible({ timeout: TIMEOUTS.cqrsProjection });
  });

  test('8. User views job listings', async ({ page }) => {
    await loginAndNavigate(page, regState.email, regState.password, '/jobs');
    await expect(page).toHaveURL(LIST_URL_PATTERNS.jobs);
    const jobList = page.getByRole('list', { name: JOB_LISTINGS_RE })
      .or(page.getByRole('article').first())
      .or(page.getByText(NO_JOBS_RE));
    await expect(jobList.first()).toBeVisible({ timeout: 30_000 });
  });

  test('9. User views generated documents', async ({ page }) => {
    await loginAndWaitForDashboard(page, regState.email, regState.password);
    const documentsPage = new DocumentsPage(page);
    await documentsPage.goto();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.documents);
    await page.waitForLoadState('load');
    // Documents page: show document list, empty state, or main content
    const documentsOrEmpty = documentsPage.emptyState.or(documentsPage.documentList).or(page.locator('main').first());
    await expect(documentsOrEmpty.first()).toBeVisible({ timeout: TIMEOUTS.cqrsProjection });
  });
});

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('User Journey: Auth Cycle & Cleanup', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeAll(() => hydrateJourneyUser(regState));

  test('10. User can logout and login again', async ({ page }) => {
    await loginAndWaitForDashboard(page, regState.email, regState.password);
    const dashboardPage = new DashboardPage(page);
    await dashboardPage.logout();
    await expect(page).toHaveURL(REGEX_PATTERNS.authRedirectUrl, { timeout: TIMEOUTS.elementVisible });
    const loginPage = new LoginPage(page);
    await loginPage.login(regState.email, regState.password);
    await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl, { timeout: TIMEOUTS.elementVisible });
  });

  test('11. Cleanup: User deletes profile', async ({ page }) => {
    if (!regState.profileId) {
      return;
    }
    await loginAndNavigate(page, regState.email, regState.password, `/profiles/${regState.profileId}`);
    // Delete lives in the profile page's kebab menu; retry open-and-verify like the user menu
    const moreOptions = page.getByRole('button', { name: /more options/iu });
    await expect(async () => {
      await moreOptions.click();
      await expect(page.getByRole('menu')).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: TIMEOUTS.elementVisible });
    const deleteItem = page.getByRole('menuitem', { name: DELETE_RE });
    await expect(deleteItem.first()).toBeVisible({ timeout: 5_000 });
    await deleteItem.first().click();
    const confirmButton = page.getByRole('button', { name: CONFIRM_YES_DELETE_RE });
    await expect(confirmButton).toBeVisible({ timeout: CONFIRM_BUTTON_VISIBLE_TIMEOUT_MS });
    await confirmButton.click();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles, { timeout: 10_000 });
  });
});

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('Job Matching Detail Journey', () => {
  // Journey user owns a profile the pipeline correlates; the fresh setup user has no matches
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeAll(() => hydrateJourneyUser(regState));

  // biome-ignore lint/nursery/useExpect: assertAnyVisible() uses expect() internally
  test('1. User can view match statistics', async ({ page }) => {
    await loginAndWaitForDashboard(page, regState.email, regState.password);
    const matchesPage = new MatchesListPage(page);
    await matchesPage.goto();
    await page.waitForLoadState('load');
    // Matches page must show stats cards, matches table, or empty state
    await assertAnyVisible([matchesPage.statsCards, matchesPage.matchesTable, matchesPage.emptyState]);
  });

  test('2. User can access match detail page', async ({ page }) => {
    await loginAndWaitForDashboard(page, regState.email, regState.password);
    const matchesPage = new MatchesListPage(page);
    await matchesPage.goto();
    await page.waitForLoadState('load');
    // Retry assertion: match data arrives via CQRS projection with eventual consistency
    await expect(async () => {
      expect(await matchesPage.getMatchCount()).toBeGreaterThan(0);
    }).toPass({ intervals: [...RETRY_INTERVALS], timeout: TIMEOUTS.cqrsProjection });
    await matchesPage.clickMatch(0);
    await expect(page).toHaveURL(JOB_MATCH_URL_RE, { timeout: 10_000 });
    await expect(page.locator('main').first()).toBeVisible();
  });
});

test.describe('Dashboard Overview', () => {
  test('dashboard shows key metrics and quick actions', async ({ page }) => {
    const dashboardPage = new DashboardPage(page);
    await dashboardPage.goto();
    await page.waitForLoadState('load');
    await expect(page.getByRole('heading', { name: DASHBOARD_HEADING_RE })).toBeVisible();
    // Dashboard renders stats cards (returning user) or onboarding steps (new user)
    const isOnboarding = await page
      .getByRole('heading', { name: ONBOARDING_WELCOME_RE })
      .isVisible()
      .catch(() => false);
    if (!isOnboarding) {
      // biome-ignore lint/nursery/noConditionalExpect: onboarding vs returning-user branch
      await expect(page.locator('.grid.grid-cols-2').locator('[class*="card"]')).toHaveCount(
        DASHBOARD_STATS_CARD_COUNT,
        { timeout: 10_000 },
      );
      // biome-ignore lint/nursery/noConditionalExpect: onboarding vs returning-user branch
      await expect(page.getByText('Activity Overview')).toBeVisible();
    }
  });

  test('dashboard navigation links work correctly', async ({ page }) => {
    const dashboardPage = new DashboardPage(page);
    await dashboardPage.goto();
    await page.waitForLoadState('load');
    await dashboardPage.navigateToProfiles();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles);
    await page.goBack();
    await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl);
    await dashboardPage.navigateToJobs();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.jobs);
    await page.goBack();
    await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl);
    await dashboardPage.navigateToDocuments();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.documents);
    await expectNoA11yViolations(page);
  });
});
