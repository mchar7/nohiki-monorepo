import type { Page } from '@playwright/test';

const EMAIL_RE = /email/iu;
const PASSWORD_RE = /^password$/iu;
const DISPLAY_NAME_RE = /display name/iu;
const CONFIRM_PASSWORD_RE = /confirm password/iu;
const SIGN_UP_BUTTON_RE = /sign up/iu;

/** Fill the Sign Up form with the given details and submit. */
export async function fillAndSubmitSignUpForm(
  page: Page,
  opts: { email: string; password: string; displayName?: string },
): Promise<void> {
  if (opts.displayName) {
    await page.getByLabel(DISPLAY_NAME_RE).first().fill(opts.displayName);
  }
  await page.getByLabel(EMAIL_RE).first().fill(opts.email);
  await page.getByLabel(PASSWORD_RE).first().fill(opts.password);
  await page.getByLabel(CONFIRM_PASSWORD_RE).first().fill(opts.password);

  await page.getByRole('button', { name: SIGN_UP_BUTTON_RE }).click();
}

/** Fill the Sign Up form email + passwords only (no submit). */
export async function fillSignUpFormFields(
  page: Page,
  opts: { email: string; password: string; confirmPassword: string },
): Promise<void> {
  await page.getByLabel(EMAIL_RE).first().fill(opts.email);
  await page.getByLabel(PASSWORD_RE).first().fill(opts.password);
  await page.getByLabel(CONFIRM_PASSWORD_RE).first().fill(opts.confirmPassword);
}
