import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const APPEARANCE_RE = /appearance/iu;
const LIGHT_RE = /light/iu;
const DARK_RE = /dark/iu;
const SYSTEM_RE = /system/iu;
const LANGUAGE_RE = /language/iu;
const API_ENDPOINT_RE = /api.*endpoint|base.*url/iu;
const SAVE_RE = /save/iu;
const RESET_RE = /reset/iu;

export class SettingsPage extends BasePage {
  readonly url = '/settings';

  readonly appearanceSection: Locator;
  readonly lightThemeButton: Locator;
  readonly darkThemeButton: Locator;
  readonly systemThemeButton: Locator;
  readonly languageDropdown: Locator;
  readonly apiEndpointInput: Locator;
  readonly saveButton: Locator;
  readonly resetButton: Locator;

  constructor(page: Page) {
    super(page);
    this.appearanceSection = page.getByRole('heading', { name: APPEARANCE_RE });
    this.lightThemeButton = page.getByRole('button', { name: LIGHT_RE });
    this.darkThemeButton = page.getByRole('button', { name: DARK_RE });
    this.systemThemeButton = page.getByRole('button', { name: SYSTEM_RE });
    this.languageDropdown = page.getByLabel(LANGUAGE_RE);
    this.apiEndpointInput = page.getByLabel(API_ENDPOINT_RE);
    this.saveButton = page.getByRole('button', { name: SAVE_RE });
    this.resetButton = page.getByRole('button', { name: RESET_RE });
  }

  async selectLightTheme(): Promise<void> {
    await this.lightThemeButton.click();
  }

  async selectDarkTheme(): Promise<void> {
    await this.darkThemeButton.click();
  }

  async selectSystemTheme(): Promise<void> {
    await this.systemThemeButton.click();
  }

  async selectLanguage(language: string): Promise<void> {
    await this.languageDropdown.click();
    await this.page.getByRole('option', { name: language }).click();
  }

  async setApiEndpoint(endpoint: string): Promise<void> {
    await this.apiEndpointInput.clear();
    await this.apiEndpointInput.fill(endpoint);
  }

  async saveSettings(): Promise<void> {
    await this.saveButton.click();
  }

  async resetSettings(): Promise<void> {
    await this.resetButton.click();
  }

  async getCurrentTheme(): Promise<string> {
    const html = this.page.locator('html');
    const classList = await html.getAttribute('class');
    return classList?.includes('dark') ? 'dark' : 'light';
  }
}
