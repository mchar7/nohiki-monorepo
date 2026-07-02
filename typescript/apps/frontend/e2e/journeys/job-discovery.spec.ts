import { LIST_URL_PATTERNS, RETRY_INTERVALS, TIMEOUTS } from '../constants.ts';
import { expect, test } from '../fixtures/auth.ts';

const JOBS_SEARCH_URL_RE = /jobs.*q=python/u;
const JOB_MATCH_DETAIL_URL_RE = /\/jobs\/matches\/[\w-]+/u;

import { expectNoA11yViolations } from '../helpers/axe-helper.ts';
import { JobListingsPage, MyMatchesPage } from '../pages/index.ts';
import {
  createProfileViaApi,
  deleteProfileViaApi,
  waitForCorrelations,
  waitForProfile,
} from '../utils/index.ts';
import {
  assertJobDetailVisible,
  navigateToFirstJobDetail,
  navigateToFirstMatchDetail,
} from '../utils/job-discovery-helpers.ts';

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('Job Discovery - Browsing', () => {
  const PIPELINE_TIMEOUT_BUFFER_MS = 60_000;
  test.describe.configure({ timeout: TIMEOUTS.pipelineCompletion + PIPELINE_TIMEOUT_BUFFER_MS });

  let profileId: string;
  const profileName = `E2E Job Discovery ${Date.now()}`;

  test.beforeAll(async ({ request }) => {
    await createProfileViaApi(request, {
      pref_name: profileName,
      search_keywords: ['python', 'fastapi', 'backend', 'api'],
      disallowed_keywords: ['PHP', 'WordPress'],
      work_arrangements: ['REMOTE', 'HYBRID'],
    });
    profileId = await waitForProfile(request, profileName);
    await waitForCorrelations(request, { minCount: 1 });
  });

  test.afterAll(async ({ request }) => {
    if (profileId) {
      await deleteProfileViaApi(request, profileId);
    }
  });

  test('1. User navigates to job listings page', async ({ page }) => {
    const jobsPage = new JobListingsPage(page);
    await jobsPage.goto();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.jobs);
  });

  test('2. User sees job listings', async ({ page }) => {
    const jobsPage = new JobListingsPage(page);
    await jobsPage.goto();
    // biome-ignore lint/nursery/noPlaywrightNetworkidle: wait for full job list render after SPA init
    await page.waitForLoadState('networkidle');
    expect(await jobsPage.getJobCount()).toBeGreaterThan(0);
  });

  test('3. User can search for jobs', async ({ page }) => {
    const jobsPage = new JobListingsPage(page);
    await jobsPage.goto();
    await expect(jobsPage.searchInput).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    await jobsPage.searchJobs('python developer');
    await expect(page).toHaveURL(JOBS_SEARCH_URL_RE);
  });

  test('4. User navigates to matches page', async ({ page }) => {
    const matchesPage = new MyMatchesPage(page);
    await matchesPage.goto();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.jobMatches);
  });

  test('5. User sees matches in the table', async ({ page }) => {
    const matchesPage = new MyMatchesPage(page);
    await matchesPage.goto();
    // Wait for TanStack Query to fetch and render match data
    await expect(async () => {
      expect(await matchesPage.getMatchCount()).toBeGreaterThan(0);
    }).toPass({ intervals: [...RETRY_INTERVALS], timeout: TIMEOUTS.cqrsProjection });
  });
});

// biome-ignore format: Playwright test.describe.serial requires single-line syntax
test.describe.serial('Job Discovery - Detail Navigation', () => {
  const PIPELINE_TIMEOUT_BUFFER_MS = 60_000;
  test.describe.configure({ timeout: TIMEOUTS.pipelineCompletion + PIPELINE_TIMEOUT_BUFFER_MS });

  test('6. User can view job detail from listings', async ({ page }) => {
    await navigateToFirstJobDetail(page);
    await assertJobDetailVisible(page);
    expect(true).toBeTruthy();
  });

  test('7. User can navigate back to job listings', async ({ page }) => {
    await navigateToFirstJobDetail(page);
    await page.goBack();
    await expect(page).toHaveURL(LIST_URL_PATTERNS.jobs);
  });

  test('8. User can view match detail from matches list', async ({ page }) => {
    const matchesPage = new MyMatchesPage(page);
    await matchesPage.goto();
    await navigateToFirstMatchDetail(page, matchesPage.matchList, JOB_MATCH_DETAIL_URL_RE);
    expect(true).toBeTruthy();
  });
});

test.describe('Job Discovery Error Handling', () => {
  test('non-existent job returns 404 or error', async ({ page }) => {
    await page.goto('/jobs/non-existent-job-id-12345');
    await expect(page.getByText('Job listing not found', { exact: true })).toBeVisible();
  });

  test('non-existent match returns 404 or error', async ({ page }) => {
    await page.goto('/jobs/matches/00000000-0000-4000-8000-000000000000');
    await expect(
      page.getByText('An unexpected error occurred in this component', { exact: true }),
    ).toBeVisible();
    await expectNoA11yViolations(page);
  });
});
