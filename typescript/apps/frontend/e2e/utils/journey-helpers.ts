import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import type { Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { REGEX_PATTERNS, TIMEOUTS } from '../constants.ts';
import { LoginPage } from '../pages/index.ts';

const JOURNEY_USER_FILE: string = join(import.meta.dirname, '..', '.output', 'journey-user.json');

interface JourneyUser {
  email: string;
  password: string;
  profileName: string;
  profileId: string;
}

/** Persist journey credentials so fresh workers and scoped runs can log in. */
export function saveJourneyUser(state: JourneyUser): void {
  mkdirSync(dirname(JOURNEY_USER_FILE), { recursive: true });
  writeFileSync(JOURNEY_USER_FILE, JSON.stringify(state, null, 2));
}

/** Fill empty journey state from disk; module state dies with every worker restart. */
export function hydrateJourneyUser(state: JourneyUser): void {
  if (state.email) {
    return;
  }
  if (!existsSync(JOURNEY_USER_FILE)) {
    throw new Error(
      `No journey user available: the Registration block has not run and ${JOURNEY_USER_FILE} does not exist. Run the full journey spec unfiltered first.`,
    );
  }
  Object.assign(state, JSON.parse(readFileSync(JOURNEY_USER_FILE, 'utf8')));
  if (!(state.email && state.password)) {
    throw new Error(`${JOURNEY_USER_FILE} is incomplete; rerun the full journey spec unfiltered.`);
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
  await page.waitForLoadState('load');
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
