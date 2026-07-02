import type { Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { APP_PATHS, TIMEOUTS } from '../constants.ts';
import { BasePage } from './base.page.ts';

const DASHBOARD_RE = /dashboard|welcome to nohiki/iu;
const USER_MENU_RE = /user menu/iu;
const SIGN_OUT_RE = /sign out/iu;

export class DashboardPage extends BasePage {
  readonly url = APP_PATHS.home;

  readonly welcomeMessage: Locator;
  readonly userMenu: Locator;
  readonly sidebar: Locator;

  constructor(page: Page) {
    super(page);
    this.welcomeMessage = page.locator('h1').filter({ hasText: DASHBOARD_RE });
    this.userMenu = page.getByRole('button', { name: USER_MENU_RE });
    this.sidebar = page.locator('aside').or(page.getByRole('navigation'));
  }

  private async expandSidebarMenuAndNavigate(menuText: string, targetHref: string): Promise<void> {
    const menuTrigger = this.sidebar
      .locator('button')
      .filter({ hasText: new RegExp(menuText, 'iu') });

    const MENU_TRIGGER_VISIBLE_TIMEOUT_MS = 2000;
    if (
      await menuTrigger.isVisible({ timeout: MENU_TRIGGER_VISIBLE_TIMEOUT_MS }).catch(() => false)
    ) {
      await menuTrigger.click();
    }

    await this.page.goto(targetHref);
  }

  async navigateToProfiles(): Promise<void> {
    await this.expandSidebarMenuAndNavigate('Profiles', '/profiles');
  }

  async navigateToJobs(): Promise<void> {
    await this.expandSidebarMenuAndNavigate('Jobs', '/jobs');
  }

  async navigateToDocuments(): Promise<void> {
    await this.page.goto('/documents');
  }

  async openUserMenu(): Promise<void> {
    await expect(this.userMenu).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    // Retry open-and-verify: a click can land before hydration wires the trigger, and Playwright never retries clicks
    await expect(async () => {
      await this.userMenu.click();
      await expect(this.page.getByRole('menu')).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: TIMEOUTS.elementVisible });
  }

  async logout(): Promise<void> {
    await this.openUserMenu();
    const logoutItem = this.page
      .getByRole('menuitem', { name: SIGN_OUT_RE })
      .or(this.page.locator('[role="menu"]').getByText(SIGN_OUT_RE));
    await expect(logoutItem.first()).toBeVisible({ timeout: 10_000 });
    await logoutItem.first().click();
  }
}
