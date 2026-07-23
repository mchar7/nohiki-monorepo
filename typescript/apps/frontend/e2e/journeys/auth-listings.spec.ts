import { expect, type Page, test } from '@playwright/test';

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

test.describe
  .parallel('auth-listings canvas (feature flag ON)', () => {
    test.beforeEach(async ({ page }) => {
      await mockListings(page);
    });

    test('renders an accessible, bounded, non-interactive canvas from the edge worker', async ({
      page,
    }) => {
      const MAX_CARDS = 30;

      await page.goto(AUTH_PATH);
      await waitForCanvasReady(page);

      const canvas = page.locator(CANVAS_LOCATOR);
      const cards = page.locator(CARD_LOCATOR);
      const cardCount = await cards.count();
      await expect(canvas).toBeAttached();
      await expect(canvas).toHaveAttribute('aria-hidden', 'true');
      await expect(canvas).toHaveCSS('pointer-events', 'none');
      expect(cardCount, 'card pool must stay within its documented bounds').toBeGreaterThan(0);
      expect(cardCount).toBeLessThanOrEqual(MAX_CARDS);
      await expect(page.locator(`${CANVAS_LOCATOR} a`)).toHaveCount(0);
      await expect(page.locator(`${CANVAS_LOCATOR} button`)).toHaveCount(0);
    });

    test('prefers-reduced-motion disables the drift keyframe animation', async ({ page }) => {
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.goto(AUTH_PATH);
      await waitForCanvasReady(page);

      await expect(page.locator(CARD_LOCATOR).first()).toHaveCSS('animation-name', 'none');
    });

    test('auth form still renders when the edge worker is unreachable', async ({ page }) => {
      await page.route(WORKER_ENDPOINT, (route) => route.abort('failed'));
      const uncaughtErrors: string[] = [];
      page.on('pageerror', (error) => uncaughtErrors.push(error.message));

      await page.goto(AUTH_PATH);

      await expect(page.locator('form').first()).toBeVisible();
      await expect(page.locator(CARD_LOCATOR)).toHaveCount(0);
      expect(uncaughtErrors).toEqual([]);
    });
  });
