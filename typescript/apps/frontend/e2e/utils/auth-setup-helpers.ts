import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { SELECTORS, TEST_USER, TIMEOUTS } from '../constants.ts';

/** Navigate to the Sign Up tab and wait for it to be active. */
export async function navigateToSignUpTab(page: Page): Promise<void> {
  const signUpTab = page.getByRole(SELECTORS.tabs.signUp.role, {
    name: SELECTORS.tabs.signUp.name,
  });
  await expect(signUpTab).toBeVisible({ timeout: TIMEOUTS.elementVisible });
  await signUpTab.click();
  await expect(signUpTab).toHaveAttribute('data-state', 'active', {
    timeout: TIMEOUTS.shortAction,
  });
}

/** Fill the registration form fields and submit. */
export async function fillRegistrationForm(page: Page, email: string): Promise<void> {
  const displayNameInput = page.getByLabel(SELECTORS.inputs.displayName.label);
  await expect(displayNameInput).toBeVisible({ timeout: TIMEOUTS.shortAction });
  await expect(displayNameInput).toBeEditable();
  await displayNameInput.fill(TEST_USER.displayName);
  await expect(displayNameInput).toHaveValue(TEST_USER.displayName);

  const emailInput = page.getByLabel(SELECTORS.inputs.email.label).first();
  await expect(emailInput).toBeVisible();
  await expect(emailInput).toBeEditable();
  await emailInput.fill(email);
  await expect(emailInput).toHaveValue(email);

  const passwordInput = page.getByLabel(SELECTORS.inputs.password.label).first();
  await expect(passwordInput).toBeVisible();
  await expect(passwordInput).toBeEditable();
  await passwordInput.fill(TEST_USER.password);
  await expect(passwordInput).toHaveValue(TEST_USER.password);

  const confirmPasswordInput = page.getByLabel(SELECTORS.inputs.confirmPassword.label).first();
  await expect(confirmPasswordInput).toBeVisible();
  await expect(confirmPasswordInput).toBeEditable();
  await confirmPasswordInput.fill(TEST_USER.password);
  await expect(confirmPasswordInput).toHaveValue(TEST_USER.password);
}

/** Click the submit button and wait for registration redirect. */
export async function submitRegistrationAndWait(page: Page, urlPattern: RegExp): Promise<void> {
  const submitButton = page.getByRole(SELECTORS.buttons.signUp.role, {
    name: SELECTORS.buttons.signUp.name,
  });
  await expect(submitButton).toBeVisible({ timeout: TIMEOUTS.shortAction });
  await expect(submitButton).toBeEnabled();
  await Promise.all([
    page.waitForURL(urlPattern, { timeout: TIMEOUTS.formSubmit }),
    submitButton.click(),
  ]);
}
