import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { TIMEOUTS } from '../constants.ts';
import { JobDetailPage, JobListingsPage } from '../pages/index.ts';

const JOB_DETAIL_URL_RE = /\/jobs\/[\w-]+/u;

/** Navigate to a job's detail page from the listings page. */
export async function navigateToFirstJobDetail(page: Page): Promise<void> {
  const jobsPage = new JobListingsPage(page);
  await jobsPage.goto();

  const firstJobCard = jobsPage.jobList.getByRole('article').first();
  const jobLink = firstJobCard.getByRole('link').first();
  await jobLink.click();

  await expect(page).toHaveURL(JOB_DETAIL_URL_RE);
}

/** Assert the job detail page shows a title heading. */
export async function assertJobDetailVisible(page: Page): Promise<void> {
  const detailPage = new JobDetailPage(page);
  await expect(detailPage.jobTitle.or(page.getByRole('heading', { level: 1 }))).toBeVisible({
    timeout: TIMEOUTS.elementVisible,
  });
}

/** Navigate to first match detail from matches list table. */
export async function navigateToFirstMatchDetail(
  page: Page,
  matchListLocator: { locator: (sel: string) => ReturnType<Page['locator']> },
  urlPattern: RegExp,
): Promise<void> {
  const firstDataRow = matchListLocator
    .locator('tbody tr')
    .filter({
      has: page.getByRole('link'),
    })
    .first();
  const matchLink = firstDataRow.getByRole('link').first();
  await matchLink.click();

  await expect(page).toHaveURL(urlPattern);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible({
    timeout: TIMEOUTS.elementVisible,
  });
}
