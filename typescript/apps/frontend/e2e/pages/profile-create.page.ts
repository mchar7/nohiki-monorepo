import type { Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { TIMEOUTS } from '../constants.ts';
import { BasePage } from './base.page.ts';

const PROFILE_NAME_RE = /profile name|name/iu;
const EXCLUDED_KEYWORDS_RE = /excluded keywords/iu;
const CREATE_SAVE_RE = /create|save/iu;
const CANCEL_RE = /cancel/iu;
const YEARS_OF_EXPERIENCE_RE = /years of experience/iu;
const CURRENCY_RE = /currency/iu;
const PAYMENT_FREQUENCY_RE = /payment frequency/iu;
const MINIMUM_SALARY_RE = /minimum salary/iu;
const TARGET_SALARY_RE = /target salary/iu;

export class ProfileCreatePage extends BasePage {
  readonly url = '/profiles/new';

  readonly nameInput: Locator;
  readonly searchKeywordsInput: Locator;
  readonly excludedKeywordsInput: Locator;
  readonly submitButton: Locator;
  readonly cancelButton: Locator;

  // Experience fields
  readonly experienceYearsInput: Locator;

  // Salary fields
  readonly currencySelect: Locator;
  readonly paymentFrequencySelect: Locator;
  readonly minSalaryInput: Locator;
  readonly targetSalaryInput: Locator;

  constructor(page: Page) {
    super(page);
    this.nameInput = page.getByRole('textbox', { name: PROFILE_NAME_RE });
    this.searchKeywordsInput = page.getByRole('textbox', { name: /^Search Keywords$/iu });
    this.excludedKeywordsInput = page.getByRole('textbox', { name: EXCLUDED_KEYWORDS_RE });
    this.submitButton = page.getByRole('button', { name: CREATE_SAVE_RE });
    this.cancelButton = page.getByRole('button', { name: CANCEL_RE });

    // Experience
    this.experienceYearsInput = page.getByRole('spinbutton', { name: YEARS_OF_EXPERIENCE_RE });
    // Salary
    this.currencySelect = page.getByLabel(CURRENCY_RE);
    this.paymentFrequencySelect = page.getByLabel(PAYMENT_FREQUENCY_RE);
    this.minSalaryInput = page.getByLabel(MINIMUM_SALARY_RE);
    this.targetSalaryInput = page.getByLabel(TARGET_SALARY_RE);
  }

  async fillName(name: string): Promise<void> {
    await this.nameInput.fill(name);
  }

  async addSearchKeyword(keyword: string): Promise<void> {
    await this.searchKeywordsInput.fill(keyword);
    await this.searchKeywordsInput.press('Enter');

    const normalizedKeyword = keyword.trim().toLowerCase();
    const tags = this.searchKeywordsInput.locator('xpath=preceding-sibling::ul');
    await expect(tags.getByText(normalizedKeyword, { exact: true })).toBeVisible();
  }

  async addExcludedKeyword(keyword: string): Promise<void> {
    await this.excludedKeywordsInput.fill(keyword);
    await this.excludedKeywordsInput.press('Enter');
  }

  async addSearchKeywords(keywords: string[]): Promise<void> {
    await keywords.reduce(
      (chain, keyword) => chain.then(() => this.addSearchKeyword(keyword)),
      Promise.resolve(),
    );
  }

  async submit(): Promise<void> {
    await this.submitButton.click();
  }

  async cancel(): Promise<void> {
    await this.cancelButton.click();
  }

  async selectWorkArrangement(arrangement: string): Promise<void> {
    const checkbox = this.page.getByRole('checkbox', { name: new RegExp(arrangement, 'iu') });
    await checkbox.check();
  }

  async setExperienceYears(years: number): Promise<void> {
    await this.experienceYearsInput.fill(String(years));
  }

  async selectSeniorityLevel(level: string): Promise<void> {
    const checkbox = this.page.locator(`#seniority-${level}`);
    await expect(checkbox).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    await checkbox.check();
  }

  async selectCurrency(currency: string): Promise<void> {
    await this.currencySelect.click();
    await this.page.getByRole('option', { name: new RegExp(`^${currency}$`, 'iu') }).click();
  }

  async selectPaymentFrequency(frequency: string): Promise<void> {
    await this.paymentFrequencySelect.click();
    await this.page.getByRole('option', { name: new RegExp(frequency, 'iu') }).click();
  }

  async setMinSalary(amount: number): Promise<void> {
    await this.minSalaryInput.fill(String(amount));
  }

  async setTargetSalary(amount: number): Promise<void> {
    await this.targetSalaryInput.fill(String(amount));
  }

  async fillAndSubmit(data: {
    name: string;
    keywords: string[];
    workArrangements?: string[];
    experienceYears?: number;
    seniorityLevels?: string[];
    currency?: string;
    paymentFrequency?: string;
    minSalary?: number;
    targetSalary?: number;
  }): Promise<void> {
    await this.fillName(data.name);
    await this.addSearchKeywords(data.keywords);
    // Work arrangements are required by the BFF (min 1)
    const arrangements = data.workArrangements ?? ['Remote'];
    await arrangements.reduce(
      (chain, arrangement) => chain.then(() => this.selectWorkArrangement(arrangement)),
      Promise.resolve(),
    );

    if (data.experienceYears !== undefined) {
      await this.setExperienceYears(data.experienceYears);
    }

    if (data.seniorityLevels && data.seniorityLevels.length > 0) {
      for (const level of data.seniorityLevels) {
        await this.selectSeniorityLevel(level);
      }
    }

    if (data.currency) {
      await this.selectCurrency(data.currency);
    }

    if (data.paymentFrequency) {
      await this.selectPaymentFrequency(data.paymentFrequency);
    }

    if (data.minSalary !== undefined) {
      await this.setMinSalary(data.minSalary);
    }

    if (data.targetSalary !== undefined) {
      await this.setTargetSalary(data.targetSalary);
    }

    await this.submit();
  }
}
