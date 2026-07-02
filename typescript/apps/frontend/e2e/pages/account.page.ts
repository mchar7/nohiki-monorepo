import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const DISPLAY_NAME_RE = /display name/iu;
const FIRST_NAME_RE = /first name/iu;
const LAST_NAME_RE = /last name/iu;
const EMAIL_RE = /email/iu;
const SAVE_OR_UPDATE_RE = /save|update/iu;
const CANCEL_RE = /cancel/iu;
const CHANGE_PASSWORD_RE = /change password/iu;
const DELETE_ACCOUNT_RE = /delete account/iu;
const CURRENT_PASSWORD_RE = /current password/iu;
const NEW_PASSWORD_RE = /^new password$/iu;
const CONFIRM_PASSWORD_RE = /confirm.*password/iu;
const CHANGE_OR_UPDATE_RE = /change|update|save/iu;
const CONFIRM_OR_DELETE_RE = /confirm|yes|delete/iu;

export class AccountSettingsPage extends BasePage {
  readonly url = '/account';

  readonly displayNameInput: Locator;
  readonly firstNameInput: Locator;
  readonly lastNameInput: Locator;
  readonly emailInput: Locator;
  readonly saveButton: Locator;
  readonly cancelButton: Locator;
  readonly changePasswordButton: Locator;
  readonly deleteAccountButton: Locator;

  constructor(page: Page) {
    super(page);
    this.displayNameInput = page.getByLabel(DISPLAY_NAME_RE);
    this.firstNameInput = page.getByLabel(FIRST_NAME_RE);
    this.lastNameInput = page.getByLabel(LAST_NAME_RE);
    this.emailInput = page.getByLabel(EMAIL_RE);
    this.saveButton = page.getByRole('button', { name: SAVE_OR_UPDATE_RE });
    this.cancelButton = page.getByRole('button', { name: CANCEL_RE });
    this.changePasswordButton = page.getByRole('button', { name: CHANGE_PASSWORD_RE });
    this.deleteAccountButton = page.getByRole('button', { name: DELETE_ACCOUNT_RE });
  }

  async updateDisplayName(name: string): Promise<void> {
    await this.displayNameInput.clear();
    await this.displayNameInput.fill(name);
  }

  async updateFirstName(name: string): Promise<void> {
    await this.firstNameInput.clear();
    await this.firstNameInput.fill(name);
  }

  async updateLastName(name: string): Promise<void> {
    await this.lastNameInput.clear();
    await this.lastNameInput.fill(name);
  }

  async saveChanges(): Promise<void> {
    await this.saveButton.click();
  }

  async cancelChanges(): Promise<void> {
    await this.cancelButton.click();
  }

  async openChangePasswordDialog(): Promise<void> {
    await this.changePasswordButton.click();
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await this.openChangePasswordDialog();
    await this.page.getByLabel(CURRENT_PASSWORD_RE).fill(currentPassword);
    await this.page.getByLabel(NEW_PASSWORD_RE).fill(newPassword);
    await this.page.getByLabel(CONFIRM_PASSWORD_RE).fill(newPassword);
    await this.page.getByRole('button', { name: CHANGE_OR_UPDATE_RE }).click();
  }

  async initiateDeleteAccount(): Promise<void> {
    await this.deleteAccountButton.click();
  }

  async confirmDeleteAccount(): Promise<void> {
    await this.page.getByRole('button', { name: CONFIRM_OR_DELETE_RE }).click();
  }

  async getDisplayName(): Promise<string> {
    return (await this.displayNameInput.inputValue()) || '';
  }

  async getFirstName(): Promise<string> {
    return (await this.firstNameInput.inputValue()) || '';
  }

  async getLastName(): Promise<string> {
    return (await this.lastNameInput.inputValue()) || '';
  }

  async getEmail(): Promise<string> {
    return (await this.emailInput.inputValue()) || '';
  }
}
