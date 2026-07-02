import { expect, type Page, type TestInfo, test } from '@playwright/test';

import { E2E_CONFIG, TIMEOUTS } from '../constants.ts';

const AUTH_PATH = '/auth/login';
const WORKER_ENDPOINT = 'http://auth-listings.e2e/auth-listings';
const CANVAS_LOCATOR = 'div[aria-hidden="true"].fixed.inset-0:has(> style)';
const CARD_LOCATOR = `${CANVAS_LOCATOR} > div`;

const LISTINGS_RESPONSE = {
  country: 'USA',
  listings: [
    {
      title: 'Senior Python Engineer',
      company_name: 'Acme',
      location_raw: 'Remote',
      work_arrangement: 'REMOTE',
      required_skills: ['Python', 'PostgreSQL'],
      posted_at: '2026-04-16T00:00:00Z',
      language: 'en',
    },
    {
      title: 'Frontend Engineer',
      company_name: 'Northstar',
      location_raw: 'New York, NY',
      work_arrangement: 'HYBRID',
      required_skills: ['TypeScript', 'React'],
      posted_at: '2026-04-15T00:00:00Z',
      language: 'en',
    },
    {
      title: 'Platform Engineer',
      company_name: 'Orbit',
      location_raw: 'Austin, TX',
      work_arrangement: 'ONSITE',
      required_skills: ['Kubernetes', 'Go'],
      posted_at: '2026-04-14T00:00:00Z',
      language: 'en',
    },
  ],
} as const;

test.skip(
  E2E_CONFIG.authListingsLane !== 'on',
  'Runs only in the explicit feature-on lane (pnpm test:e2e:auth-listings)',
);
test.use({ storageState: { cookies: [], origins: [] } });

async function mockListings(page: Page): Promise<void> {
  await page.route(WORKER_ENDPOINT, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', json: LISTINGS_RESPONSE }),
  );
}

async function waitForCanvasReady(page: Page): Promise<void> {
  await page
    .locator(CARD_LOCATOR)
    .first()
    .waitFor({ state: 'attached', timeout: TIMEOUTS.networkIdle });
}

async function attachScreenshot(
  page: Page,
  testInfo: TestInfo,
  name: string,
  fullPage = false,
): Promise<void> {
  const body = await page.screenshot({ fullPage });
  await testInfo.attach(name, { body, contentType: 'image/png' });
}

test.describe('auth-listings canvas (feature flag ON)', () => {
  test.beforeEach(async ({ page }) => {
    await mockListings(page);
  });

  test('renders drifting cards sourced from the edge worker', async ({ page }, testInfo) => {
    await page.goto(AUTH_PATH);
    await waitForCanvasReady(page);

    await expect(page.locator(CANVAS_LOCATOR)).toBeAttached();
    const cardCount = await page.locator(CARD_LOCATOR).count();
    expect(cardCount, 'at least one card must render').toBeGreaterThan(0);

    await attachScreenshot(page, testInfo, 'canvas-rendered.png', true);
  });

  test('canvas root is aria-hidden and non-interactive', async ({ page }, testInfo) => {
    await page.goto(AUTH_PATH);
    await waitForCanvasReady(page);

    const canvas = page.locator(CANVAS_LOCATOR);
    await expect(canvas).toHaveAttribute('aria-hidden', 'true');
    await expect(canvas).toHaveCSS('pointer-events', 'none');

    await attachScreenshot(page, testInfo, 'a11y-attributes.png');
  });

  test('pool manager keeps DOM card count at or below the documented ceiling', async ({
    page,
  }, testInfo) => {
    const MAX_CARDS = 30;

    await page.goto(AUTH_PATH);
    await waitForCanvasReady(page);

    const cardCount = await page.locator(CARD_LOCATOR).count();
    expect(cardCount).toBeLessThanOrEqual(MAX_CARDS);

    await attachScreenshot(page, testInfo, 'card-count.png');
  });

  test('prefers-reduced-motion disables the drift keyframe animation', async ({
    page,
  }, testInfo) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(AUTH_PATH);
    await waitForCanvasReady(page);

    await expect(page.locator(CARD_LOCATOR).first()).toHaveCSS('animation-name', 'none');

    await attachScreenshot(page, testInfo, 'reduced-motion.png', true);
  });

  test('auth form still renders when the edge worker is unreachable', async ({
    page,
  }, testInfo) => {
    await page.route(WORKER_ENDPOINT, (route) => route.abort('failed'));
    const uncaughtErrors: string[] = [];
    page.on('pageerror', (error) => uncaughtErrors.push(error.message));

    await page.goto(AUTH_PATH);

    await expect(page.locator('form').first()).toBeVisible();
    await expect(page.locator(CARD_LOCATOR)).toHaveCount(0);
    expect(uncaughtErrors).toEqual([]);

    await attachScreenshot(page, testInfo, 'worker-unreachable.png', true);
  });

  test('cards expose no interactive controls', async ({ page }, testInfo) => {
    await page.goto(AUTH_PATH);
    await waitForCanvasReady(page);

    await expect(page.locator(`${CANVAS_LOCATOR} a`)).toHaveCount(0);
    await expect(page.locator(`${CANVAS_LOCATOR} button`)).toHaveCount(0);

    await attachScreenshot(page, testInfo, 'non-interactive.png');
  });
});
