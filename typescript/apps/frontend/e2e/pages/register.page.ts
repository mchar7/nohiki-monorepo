import type { Locator } from '@playwright/test';
import { expect } from '@playwright/test';

import { AUTH_PATHS, SELECTORS, TIMEOUTS } from '../constants.ts';
import { BasePage } from './base.page.ts';

interface RegisterData {
  email: string;
  password: string;
  displayName: string;
}

export class RegisterPage extends BasePage {
  readonly url = AUTH_PATHS.register;

  get signInTab(): Locator {
    return this.page.getByRole(SELECTORS.tabs.signIn.role, { name: SELECTORS.tabs.signIn.name });
  }

  get signUpTab(): Locator {
    return this.page.getByRole(SELECTORS.tabs.signUp.role, { name: SELECTORS.tabs.signUp.name });
  }

  get displayNameInput(): Locator {
    return this.page.getByLabel(SELECTORS.inputs.displayName.label).first();
  }

  get emailInput(): Locator {
    return this.page.getByLabel(SELECTORS.inputs.email.label).first();
  }

  get passwordInput(): Locator {
    return this.page.getByLabel(SELECTORS.inputs.password.label).first();
  }

  get confirmPasswordInput(): Locator {
    return this.page.getByLabel(SELECTORS.inputs.confirmPassword.label).first();
  }

  get submitButton(): Locator {
    return this.page.getByRole(SELECTORS.buttons.signUp.role, {
      name: SELECTORS.buttons.signUp.name,
    });
  }

  get errorMessage(): Locator {
    return this.page.locator(SELECTORS.classes.errorMessage);
  }

  async register(data: RegisterData): Promise<void> {
    await expect(this.signUpTab).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    await this.signUpTab.click();
    await expect(this.signUpTab).toHaveAttribute('data-state', 'active');

    await expect(this.displayNameInput).toBeVisible();
    await this.displayNameInput.fill(data.displayName);

    await expect(this.emailInput).toBeVisible();
    await this.emailInput.fill(data.email);

    await expect(this.passwordInput).toBeVisible();
    await this.passwordInput.fill(data.password);

    await expect(this.confirmPasswordInput).toBeVisible();
    await this.confirmPasswordInput.fill(data.password);

    await expect(this.submitButton).toBeEnabled({ timeout: TIMEOUTS.shortAction });
    await this.submitButton.click();
  }

  async switchToSignIn(): Promise<void> {
    await expect(this.signInTab).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    await this.signInTab.click();
    await expect(this.signInTab).toHaveAttribute('data-state', 'active');
  }
}
