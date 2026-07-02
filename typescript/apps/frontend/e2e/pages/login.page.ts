import type { Locator } from '@playwright/test';
import { expect } from '@playwright/test';

import { AUTH_PATHS, SELECTORS, TIMEOUTS } from '../constants.ts';
import { BasePage } from './base.page.ts';

export class LoginPage extends BasePage {
  readonly url = AUTH_PATHS.login;

  get signInTab(): Locator {
    return this.page.getByRole(SELECTORS.tabs.signIn.role, { name: SELECTORS.tabs.signIn.name });
  }

  get signUpTab(): Locator {
    return this.page.getByRole(SELECTORS.tabs.signUp.role, { name: SELECTORS.tabs.signUp.name });
  }

  get emailInput(): Locator {
    return this.page.getByLabel(SELECTORS.inputs.email.label).first();
  }

  get passwordInput(): Locator {
    return this.page.getByLabel(SELECTORS.inputs.password.label).first();
  }

  get submitButton(): Locator {
    return this.page.getByRole(SELECTORS.buttons.signIn.role, {
      name: SELECTORS.buttons.signIn.name,
    });
  }

  get googleOAuthButton(): Locator {
    return this.page.getByRole(SELECTORS.buttons.google.role, {
      name: SELECTORS.buttons.google.name,
    });
  }

  get githubOAuthButton(): Locator {
    return this.page.getByRole(SELECTORS.buttons.github.role, {
      name: SELECTORS.buttons.github.name,
    });
  }

  get termsLink(): Locator {
    return this.page.getByRole(SELECTORS.links.terms.role, { name: SELECTORS.links.terms.name });
  }

  get privacyLink(): Locator {
    return this.page.getByRole(SELECTORS.links.privacy.role, {
      name: SELECTORS.links.privacy.name,
    });
  }

  get errorMessage(): Locator {
    return this.page.locator(SELECTORS.classes.errorMessage);
  }

  get formRootError(): Locator {
    return this.page.getByTestId(SELECTORS.testIds.formRootError);
  }

  async login(email: string, password: string): Promise<void> {
    await expect(this.emailInput).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    await expect(this.emailInput).toBeEditable();

    await this.emailInput.fill(email);
    await this.passwordInput.fill(password);

    await expect(this.submitButton).toBeEnabled({ timeout: TIMEOUTS.shortAction });
    // Retry click-and-verify: submission intermittently no-ops right after render
    // (timing-sensitive; disappears under --trace). Submission took effect once we
    // leave /auth or the form surfaces a root error; both rejecting retries the click.
    await expect(async () => {
      await this.submitButton.click();
      await Promise.any([
        this.page.waitForURL((url) => !url.pathname.startsWith('/auth'), { timeout: 2_500 }),
        this.page.locator('[role="alert"]').first().waitFor({ state: 'visible', timeout: 2_500 }),
      ]);
    }).toPass({ timeout: TIMEOUTS.elementVisible });
  }

  async switchToSignUp(): Promise<void> {
    await expect(this.signUpTab).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    await this.signUpTab.click();
    await expect(this.signUpTab).toHaveAttribute('data-state', 'active');
  }

  async switchToSignIn(): Promise<void> {
    await expect(this.signInTab).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    await this.signInTab.click();
    await expect(this.signInTab).toHaveAttribute('data-state', 'active');
  }
}
