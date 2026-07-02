import type { Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { APP_PATHS, TIMEOUTS } from '../constants.ts';
import { BasePage } from './base.page.ts';

const CREATE_NEW_RE = /create new/iu;
const NO_YET_START_RE = /no.*yet|create.*to start/iu;
const LOADING_RE = /loading/iu;

export class ProfilesPage extends BasePage {
  readonly url = APP_PATHS.profiles;

  readonly createButton: Locator;
  readonly profileList: Locator;
  readonly emptyState: Locator;
  readonly loadingSpinner: Locator;

  constructor(page: Page) {
    super(page);
    this.createButton = page.locator('a, button').filter({ hasText: CREATE_NEW_RE }).first();
    this.profileList = page.locator('main');
    this.emptyState = page.getByText(NO_YET_START_RE);
    this.loadingSpinner = page.getByRole('status', { name: LOADING_RE });
  }

  async waitForProfilesLoaded(): Promise<void> {
    await this.loadingSpinner.waitFor({ state: 'hidden', timeout: TIMEOUTS.cqrsProjection });
  }

  async clickCreateProfile(): Promise<void> {
    await expect(this.createButton).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    await this.createButton.click();
  }

  async getProfileCount(): Promise<number> {
    await this.waitForProfilesLoaded();
    return this.profileList.getByRole('article').count();
  }

  async clickProfile(name: string): Promise<void> {
    await this.waitForProfilesLoaded();
    const profileLink = this.profileList.getByRole('link', { name });
    await expect(profileLink).toBeVisible();
    await profileLink.click();
  }

  async assertProfileExists(name: string): Promise<void> {
    await this.waitForProfilesLoaded();
    await expect(this.profileList.getByText(name)).toBeVisible({
      timeout: TIMEOUTS.cqrsProjection,
    });
  }

  async assertProfileNotExists(name: string): Promise<void> {
    await this.waitForProfilesLoaded();
    await expect(this.profileList.getByText(name)).not.toBeVisible({
      timeout: TIMEOUTS.elementVisible,
    });
  }

  getProfileCard(name: string): Locator {
    return this.profileList.getByRole('article').filter({ hasText: name });
  }
}
