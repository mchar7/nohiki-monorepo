import { expect, test } from '@playwright/test';

import {
  AUTH_PATHS,
  EXTERNAL_URLS,
  REGEX_PATTERNS,
  SELECTORS,
  TEST_USER,
  TIMEOUTS,
} from '../constants.ts';
import { TestData } from '../fixtures/test-data.ts';
import { expectNoA11yViolations } from '../helpers/axe-helper.ts';
import { LoginPage } from '../pages/login.page.ts';
import { fillAndSubmitSignUpForm, fillSignUpFormFields } from '../utils/auth-test-helpers.ts';

const EMAIL_RE = /email/iu;
const PASSWORD_RE = /^password$/iu;
const CONFIRM_PASSWORD_RE = /confirm password/iu;
const TERMS_OF_SERVICE_RE = /terms of service/iu;
const PRIVACY_POLICY_RE = /privacy policy/iu;
const VALID_EMAIL_ERROR_RE = /please enter a valid email address/iu;
const PASSWORD_LENGTH_ERROR_RE = /password must be at least/iu;
const PASSWORDS_MISMATCH_RE = /passwords do not match/iu;
const SIGN_UP_BUTTON_RE = /sign up/iu;

const FORGOT_PASSWORD_RE = /forgot password/iu;
const NOT_YET_AVAILABLE_RE = /not yet available/iu;
const CLOSE_RE = /close/iu;
const TOO_MANY_ATTEMPTS_RE = /too many attempts/iu;
const ERROR_PERSIST_TIMEOUT_MS = 10_000;
test.describe('Authentication - Unified Auth Page', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('displays login tab by default when visiting /auth', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    await expect(loginPage.signInTab).toBeVisible();
    await expect(loginPage.signUpTab).toBeVisible();
    await expect(loginPage.signInTab).toHaveAttribute('data-state', 'active');
  });

  test('displays register tab when clicking sign up tab', async ({ page }) => {
    await page.goto(AUTH_PATHS.login);
    const signUpTab = page.getByRole(SELECTORS.tabs.signUp.role, {
      name: SELECTORS.tabs.signUp.name,
    });
    await signUpTab.click();
    await expect(signUpTab).toHaveAttribute('data-state', 'active');
  });

  test('can switch between login and register tabs', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    await expect(loginPage.signInTab).toHaveAttribute('data-state', 'active');
    await loginPage.switchToSignUp();
    await expect(loginPage.signUpTab).toHaveAttribute('data-state', 'active');
    await loginPage.switchToSignIn();
    await expect(loginPage.signInTab).toHaveAttribute('data-state', 'active');
  });
});

test.describe('Authentication - Field Persistence', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('preserves email value when switching between tabs', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    const testEmail = 'test@example.com';
    await loginPage.emailInput.fill(testEmail);
    await loginPage.switchToSignUp();

    const signUpEmailInput = page.getByLabel(EMAIL_RE).first();
    await expect(signUpEmailInput).toHaveValue(testEmail);
  });

  test('preserves password value when switching between tabs', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    const testPassword = 'TestPassword123!';
    await loginPage.passwordInput.fill(testPassword);
    await loginPage.switchToSignUp();

    const signUpPasswordInput = page.getByLabel(PASSWORD_RE).first();
    await expect(signUpPasswordInput).toHaveValue(testPassword);
  });
});

test.describe('Authentication - OAuth Buttons', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('Google OAuth button is visible', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await expect(loginPage.googleOAuthButton).toBeVisible();
  });

  test('GitHub OAuth button is visible', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await expect(loginPage.githubOAuthButton).toBeVisible();
  });

  test('disabled OAuth button shows tooltip on hover', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    const googleButton = loginPage.googleOAuthButton;
    const isDisabled = await googleButton.isDisabled();
    test.skip(!isDisabled, 'OAuth providers are enabled in this environment');

    const buttonWrapper = googleButton.locator('..');
    await buttonWrapper.hover();
    await expect(page.getByRole('tooltip')).toBeVisible({ timeout: TIMEOUTS.shortAction });
  });

  test('enabled OAuth button navigates to authorize endpoint', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    const googleButton = loginPage.googleOAuthButton;
    const isDisabled = await googleButton.isDisabled();
    test.skip(isDisabled, 'OAuth not configured in this environment');

    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().includes('/api/v1/auth/oauth/google/authorize')),
      googleButton.click(),
    ]);
    expect(request.url()).toContain('/api/v1/auth/oauth/google/authorize');
  });
});

test.describe('Authentication - Terms and Privacy Links', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('Terms of Service link is visible and points to correct URL', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    const termsLink = page.getByRole('link', { name: TERMS_OF_SERVICE_RE });
    await expect(termsLink).toBeVisible();
    await expect(termsLink).toHaveAttribute('href', EXTERNAL_URLS.termsOfService);
    await expect(termsLink).toHaveAttribute('target', '_blank');
  });

  test('Privacy Policy link is visible and points to correct URL', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    const privacyLink = page.getByRole('link', { name: PRIVACY_POLICY_RE });
    await expect(privacyLink).toBeVisible();
    await expect(privacyLink).toHaveAttribute('href', EXTERNAL_URLS.privacyPolicy);
    await expect(privacyLink).toHaveAttribute('target', '_blank');
  });
});

test.describe('Authentication - Login Flow', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('shows inline validation error for invalid email', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    await loginPage.emailInput.fill('invalid-email');
    await loginPage.emailInput.blur();

    await expect(page.getByText(VALID_EMAIL_ERROR_RE)).toBeVisible();
    await expect(loginPage.submitButton).toBeDisabled();
  });

  test('shows inline validation error for short password', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    await loginPage.emailInput.fill('test@example.com');
    await loginPage.passwordInput.fill('short');
    await loginPage.passwordInput.blur();

    await expect(page.getByText(PASSWORD_LENGTH_ERROR_RE)).toBeVisible();
    await expect(loginPage.submitButton).toBeDisabled();
  });

  test('successful login redirects to home', async ({ page, request }) => {
    const testEmail = TestData.generateUniqueEmail('e2e-login');
    const testPassword = TEST_USER.password;

    await request.post(AUTH_PATHS.registerApi, {
      data: {
        email: testEmail,
        password: testPassword,
        display_name: TEST_USER.displayName,
      },
    });

    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login(testEmail, testPassword);
    await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl, { timeout: TIMEOUTS.navigation });
  });

  test('failed login shows error message', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login('nonexistent@example.com', 'wrongpassword');
    await expect(loginPage.errorMessage).toBeVisible({ timeout: TIMEOUTS.shortAction });
  });
});

test.describe('Authentication - Registration Flow', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('can register a new user', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.switchToSignUp();

    const uniqueEmail = TestData.generateUniqueEmail('e2e-register');
    await fillAndSubmitSignUpForm(page, {
      email: uniqueEmail,
      password: 'TestPassword123!',
      displayName: 'E2E Test User',
    });

    await expect(page).toHaveURL(REGEX_PATTERNS.dashboardUrl, { timeout: TIMEOUTS.navigation });
  });

  test('shows inline error for mismatched passwords', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.switchToSignUp();

    await fillSignUpFormFields(page, {
      email: 'test@example.com',
      password: 'TestPassword123!',
      confirmPassword: 'DifferentPassword!',
    });
    await page.getByLabel(CONFIRM_PASSWORD_RE).first().blur();

    await expect(page.getByText(PASSWORDS_MISMATCH_RE)).toBeVisible();
    await expect(page.getByRole('button', { name: SIGN_UP_BUTTON_RE })).toBeDisabled();
  });

  test('shows error for duplicate email', async ({ page, request }) => {
    const existingEmail = TEST_USER.email;

    await request.post(AUTH_PATHS.registerApi, {
      data: {
        email: existingEmail,
        password: TEST_USER.password,
        display_name: TEST_USER.displayName,
      },
    });

    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.switchToSignUp();

    await fillAndSubmitSignUpForm(page, {
      email: existingEmail,
      password: 'TestPassword123!',
      displayName: TEST_USER.displayName,
    });

    await expect(page.locator(SELECTORS.classes.errorMessage)).toBeVisible({
      timeout: TIMEOUTS.shortAction,
    });
  });
});

test.describe('Authentication - Error Persistence', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('error persists beyond 10 seconds until user edits a field', async ({ page }) => {
    await page.clock.install();
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login('wrong@example.com', 'WrongPassword123!');

    const alert = page.locator('[role="alert"]');
    await expect(alert).toBeVisible({
      timeout: TIMEOUTS.shortAction,
    });

    await page.clock.fastForward(ERROR_PERSIST_TIMEOUT_MS);
    await expect(alert).toBeVisible();

    await loginPage.passwordInput.fill('corrected');
    await expect(alert).toBeHidden();
  });

  test('error clears immediately on resubmit', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login('wrong@example.com', 'WrongPassword123!');

    const alert = page.locator('[role="alert"]');
    await expect(alert).toBeVisible({
      timeout: TIMEOUTS.shortAction,
    });

    const responseReleased = Promise.withResolvers<void>();
    await page.route('**/api/v1/auth/login', async (route) => {
      await responseReleased.promise;
      await route.continue();
    });

    await loginPage.submitButton.click();
    await expect(alert).toBeHidden();

    responseReleased.resolve();
    await expect(alert).toBeVisible({ timeout: TIMEOUTS.shortAction });
  });
});

test.describe('Authentication - Visual Emphasis', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('error alert has icon, role, and proper styling', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login('wrong@example.com', 'WrongPassword123!');

    const alert = page.locator('[role="alert"]');
    await expect(alert).toBeVisible({ timeout: TIMEOUTS.shortAction });
    await expect(page.locator('.text-destructive')).toBeVisible();
    await expect(page.getByTestId('form-root-error')).toBeVisible();
  });

  test('submit button shows spinner during API call', async ({ page }) => {
    const responseReleased = Promise.withResolvers<void>();
    await page.route('**/api/v1/auth/login', async (route) => {
      await responseReleased.promise;
      await route.continue();
    });

    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.emailInput.fill('test@example.com');
    await loginPage.passwordInput.fill('Password123!');
    await loginPage.submitButton.click();

    const spinner = page.locator('.animate-spin');
    await expect(spinner).toBeVisible();

    responseReleased.resolve();
    await expect(spinner).toBeHidden({ timeout: TIMEOUTS.shortAction });
  });
});

test.describe('Authentication - Forgot Password', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('forgot password link opens not-available dialog', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    const forgotLink = page.getByRole('button', { name: FORGOT_PASSWORD_RE });
    await expect(forgotLink).toBeVisible();
    await forgotLink.click();

    await expect(page.getByRole('alertdialog')).toBeVisible();
    await expect(page.getByText(NOT_YET_AVAILABLE_RE)).toBeVisible();

    await page.getByRole('button', { name: CLOSE_RE }).click();
    await expect(page.getByRole('alertdialog')).toBeHidden();
  });

  test('forgot password link is not visible on signup tab', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.switchToSignUp();

    await expect(page.getByRole('button', { name: FORGOT_PASSWORD_RE })).toBeHidden();
  });
});

test.describe('Authentication - Rate Limiting', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('shows countdown on 429 response', async ({ page }) => {
    await page.route('**/api/v1/auth/login', (route) =>
      route.fulfill({
        status: 429,
        headers: { 'Retry-After': '30' },
        body: JSON.stringify({ detail: 'Too many requests' }),
      }),
    );

    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login('test@example.com', 'Password123!');

    await expect(page.getByText(TOO_MANY_ATTEMPTS_RE)).toBeVisible({
      timeout: TIMEOUTS.shortAction,
    });
    await expectNoA11yViolations(page);
  });
});
