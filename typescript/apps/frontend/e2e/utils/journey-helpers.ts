import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import process from 'node:process';
import type { Locator, Page, TestInfo } from '@playwright/test';
import { expect } from '@playwright/test';

import { REGEX_PATTERNS, TIMEOUTS } from '../constants.ts';
import { LoginPage } from '../pages/index.ts';

function getJourneyUserFile(): string {
  return join(import.meta.dirname, '..', '.output', `journey-user-${process.ppid}.json`);
}

interface JourneyUser {
  email: string;
  password: string;
  profileName: string;
  profileId: string;
}

/** Persist journey credentials within this run. */
export function saveJourneyUser(state: JourneyUser, _testInfo: TestInfo): void {
  const journeyUserFile = getJourneyUserFile();
  mkdirSync(dirname(journeyUserFile), { recursive: true });
  writeFileSync(journeyUserFile, JSON.stringify(state, null, 2));
}

/** Fill empty journey state from this run's handoff. */
export function hydrateJourneyUser(state: JourneyUser, _testInfo: TestInfo): void {
  if (state.email) {
    return;
  }
  const journeyUserFile = getJourneyUserFile();
  if (!existsSync(journeyUserFile)) {
    throw new Error(
      `No journey user available: the Registration block has not run and ${journeyUserFile} does not exist. Run the full journey spec unfiltered first.`,
    );
  }
  Object.assign(state, JSON.parse(readFileSync(journeyUserFile, 'utf8')));
  if (!(state.email && state.password)) {
    throw new Error(`${journeyUserFile} is incomplete; rerun the full journey spec unfiltered.`);
  }
}

/** Log in with provided credentials and wait for the dashboard. */
export async function loginAndWaitForDashboard(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  const loginPage = new LoginPage(page);
  await loginPage.goto();
  await loginPage.login(email, password);

  await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl, { timeout: TIMEOUTS.navigation });
}

/** Navigate to a path after login. */
export async function loginAndNavigate(
  page: Page,
  email: string,
  password: string,
  path: string,
): Promise<void> {
  await loginAndWaitForDashboard(page, email, password);
  await page.goto(path);
}

/**
 * Assert at least one of the provided locators is visible.
 * Playwright's .or() is strict and fails when several alternatives are visible
 * at once, so assert on .first() of the combined locator instead.
 */
export async function assertAnyVisible(locators: Locator[]): Promise<void> {
  if (locators.length === 0) {
    throw new Error('assertAnyVisible requires at least one locator');
  }
  const combined = locators.reduce((acc, loc) => acc.or(loc));
  await expect(combined.first()).toBeVisible({ timeout: TIMEOUTS.cqrsProjection });
}
