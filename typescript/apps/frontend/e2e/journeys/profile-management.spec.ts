import { LIST_URL_PATTERNS, TIMEOUTS } from '../constants.ts';
import { expect, test } from '../fixtures/auth.ts';
import { expectNoA11yViolations } from '../helpers/axe-helper.ts';
import { DashboardPage, ProfileCreatePage, ProfilesPage } from '../pages/index.ts';
import { waitForProfile, waitForProjection } from '../utils/api-helpers.ts';
import { waitForTextOnPage } from '../utils/index.ts';
import { deleteCurrentProfile, extractProfileId } from '../utils/profile-helpers.ts';

const PYTHON_RE = /python/iu;
const JAVASCRIPT_RE = /javascript/iu;
const HTTP_ACCEPTED = 202;
const CQRS_POLL_INTERVAL_MS = 2000;
const EXPERIENCE_YEARS_RE = /5 years of experience/iu;
const MID_LEVEL_RE = /mid level/iu;
const MID_RE = /mid/iu;
const SENIOR_RE = /senior/iu;
const MIN_SALARY_RE = /80[,.]?000/u;
const TARGET_SALARY_RE = /120[,.]?000/u;
const ENRICHMENT_PIPELINE_TIMEOUT_MS = 120_000;
const SKILL_RETRY_INTERVAL_MS = 2000;
const CQRS_UPDATE_TIMEOUT_MS = 60_000;
/** Shared state across the serial profile-management journey. */
const shared: { profileId: string; profileName: string; updatedProfileName: string } = {
  profileId: '',
  profileName: '',
  updatedProfileName: '',
};

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('Profile Management - CRUD', () => {
  test.beforeAll(() => {
    shared.profileName = `E2E Profile ${Date.now()}`;
    shared.updatedProfileName = `${shared.profileName} - Updated`;
  });

  test('1. User navigates to profiles page', async ({ page }) => {
    const dashboardPage = new DashboardPage(page);
    await dashboardPage.goto();
    await dashboardPage.navigateToProfiles();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles);
  });
  test('2. User sees create button', async ({ page }) => {
    const profilesPage = new ProfilesPage(page);
    await profilesPage.goto();
    await page.waitForLoadState('load');
    await expect(profilesPage.createButton).toBeVisible({ timeout: 10_000 });
  });
  test('3. User creates a new profile', async ({ page }) => {
    const profilesPage = new ProfilesPage(page);
    await profilesPage.goto();
    await profilesPage.clickCreateProfile();
    await expect(page).toHaveURL('/profiles/new');
    const createPage = new ProfileCreatePage(page);
    await createPage.fillAndSubmit({
      name: shared.profileName,
      keywords: ['Python', 'JavaScript', 'SQL'],
      experienceYears: 5,
      seniorityLevels: ['MID', 'SENIOR'],
      currency: 'USD',
      paymentFrequency: 'Annually',
      minSalary: 80_000,
      targetSalary: 120_000,
    });
    await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles, { timeout: 30_000 });
  });

  test('4. Profile appears in profiles list', async ({ page, request }) => {
    test.setTimeout(ENRICHMENT_PIPELINE_TIMEOUT_MS);
    // Poll BFF API directly to wait for the two-stage enrichment pipeline
    shared.profileId = await waitForProfile(request, shared.profileName, {
      timeout: ENRICHMENT_PIPELINE_TIMEOUT_MS - TIMEOUTS.elementVisible,
    });
    expect(shared.profileId).toBeTruthy();
    await expect(async () => {
      const detailResponse = await request.get(`/api/v1/profiles/${shared.profileId}`);
      expect(detailResponse.ok()).toBeTruthy();
      const profile = (await detailResponse.json()) as {
        experience_preference?: { experience_years?: number };
      };
      expect(profile.experience_preference?.experience_years).toBe(5);
    }).toPass({ intervals: [CQRS_POLL_INTERVAL_MS], timeout: TIMEOUTS.cqrsProjection });
    // Now verify the UI reflects the projection
    const profilesPage = new ProfilesPage(page);
    await profilesPage.goto();
    await page.waitForLoadState('load');
    await waitForTextOnPage(page, shared.profileName, { timeout: TIMEOUTS.elementVisible });
    const uiProfileId = await extractProfileId(page, shared.profileName);
    expect(uiProfileId).toBe(shared.profileId);
  });
  test('5. User can view profile details', async ({ page }) => {
    await page.goto(`/profiles/${shared.profileId}`);
    await page.waitForLoadState('load');
    await expect(page.getByRole('heading', { level: 1 })).toContainText(shared.profileName, { timeout: 10_000 });
    // Skills resolved asynchronously - use retry
    await expect(async () => {
      await expect(page.getByText(PYTHON_RE)).toBeVisible();
      await expect(page.getByText(JAVASCRIPT_RE)).toBeVisible();
    }).toPass({ intervals: [SKILL_RETRY_INTERVAL_MS], timeout: TIMEOUTS.cqrsProjection });
    // Verify experience and salary fields
    await expect(page.getByText(EXPERIENCE_YEARS_RE)).toBeVisible();
    await expect(page.getByText(MID_LEVEL_RE).or(page.getByText(MID_RE))).toBeVisible();
    await expect(page.getByText(SENIOR_RE)).toBeVisible();
    await expect(page.getByText(MIN_SALARY_RE)).toBeVisible();
    await expect(page.getByText(TARGET_SALARY_RE)).toBeVisible();
  });

  test('6. User can edit profile name', async ({ page, request }) => {
    test.setTimeout(CQRS_UPDATE_TIMEOUT_MS);
    const patchResponse = await request.patch(`/api/v1/profiles/${shared.profileId}`, {
      data: { pref_name: shared.updatedProfileName },
    });
    expect(patchResponse.status()).toBe(HTTP_ACCEPTED);
    await waitForProjection(
      request,
      `/api/v1/profiles/${shared.profileId}`,
      (profile: { pref_name: string }) => profile.pref_name === shared.updatedProfileName,
      { timeout: CQRS_UPDATE_TIMEOUT_MS - TIMEOUTS.elementVisible },
    );
    await page.goto(`/profiles/${shared.profileId}`);
    await page.waitForLoadState('load');
    await expect(page.getByRole('heading', { level: 1 })).toContainText(shared.updatedProfileName, { timeout: TIMEOUTS.elementVisible });
  });

  test('7. Updated name appears in profiles list', async ({ page }) => {
    const profilesPage = new ProfilesPage(page);
    await profilesPage.goto();
    await page.waitForLoadState('load');
    await expect(page.getByText(shared.updatedProfileName)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(shared.profileName, { exact: true }).first()).not.toBeVisible();
  });

  test('8. User can delete profile', async ({ page }) => {
    await page.goto(`/profiles/${shared.profileId}`);
    await page.waitForLoadState('load');
    await deleteCurrentProfile(page);
    await expect(page).toHaveURL(LIST_URL_PATTERNS.profiles, { timeout: 10_000 });
    await expect(async () => {
      await page.reload();
      await page.waitForLoadState('load');
      await expect(page.getByText(shared.updatedProfileName, { exact: true })).not.toBeVisible();
    }).toPass({ intervals: [CQRS_POLL_INTERVAL_MS], timeout: TIMEOUTS.cqrsProjection });
    await expectNoA11yViolations(page);
  });
});
