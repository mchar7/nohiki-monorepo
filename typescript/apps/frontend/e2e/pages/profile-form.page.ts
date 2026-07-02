import type { Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';

import { APP_PATHS, TIMEOUTS } from '../constants.ts';
import { BasePage } from './base.page.ts';

const PROFILE_NAME_LABEL_RE = /profile name|name/iu;
const EXCLUDED_KEYWORDS_RE = /excluded keywords/iu;
const REMOTE_RE = /remote/iu;
const HYBRID_RE = /hybrid/iu;
const ONSITE_RE = /onsite|on-site/iu;
const FLEXIBLE_RE = /flexible/iu;
const RELOCATION_RE = /relocation/iu;
const NOTIFICATION_THRESHOLD_RE = /notification.*threshold/iu;
const AUTO_TAILOR_THRESHOLD_RE = /auto.*tailor.*threshold/iu;
const CREATE_SAVE_SUBMIT_RE = /create|save|submit/iu;
const CANCEL_RE = /cancel/iu;
const YEARS_OF_EXPERIENCE_RE = /years of experience/iu;
const CURRENCY_RE = /currency/iu;
const PAYMENT_FREQUENCY_RE = /payment frequency/iu;
const MINIMUM_SALARY_RE = /minimum salary/iu;
const TARGET_SALARY_RE = /target salary/iu;
const YOUR_SKILLS_RE = /your skills/iu;

type WorkArrangement = 'remote' | 'hybrid' | 'onsite' | 'flexible';

interface ProfileFormData {
  name: string;
  searchKeywords: string[];
  disallowedKeywords?: string[];
  workArrangements?: WorkArrangement[];
  openToRelocation?: boolean;
  experienceYears?: number;
  seniorityLevels?: string[];
  currency?: string;
  paymentFrequency?: string;
  minSalary?: number;
  targetSalary?: number;
}

export class ProfileFormPage extends BasePage {
  readonly url = APP_PATHS.profileNew;

  readonly profileNameInput: Locator;
  readonly searchKeywordsInput: Locator;
  readonly disallowedKeywordsInput: Locator;

  readonly remoteCheckbox: Locator;
  readonly hybridCheckbox: Locator;
  readonly onsiteCheckbox: Locator;
  readonly flexibleCheckbox: Locator;

  readonly openToRelocationSwitch: Locator;

  readonly notificationThresholdSlider: Locator;
  readonly autoTailorThresholdSlider: Locator;

  // Experience fields
  readonly experienceYearsInput: Locator;

  // Salary fields
  readonly currencySelect: Locator;
  readonly paymentFrequencySelect: Locator;
  readonly minSalaryInput: Locator;
  readonly targetSalaryInput: Locator;

  // Skills field
  readonly skillsInput: Locator;

  readonly submitButton: Locator;
  readonly cancelButton: Locator;

  constructor(page: Page) {
    super(page);
    this.profileNameInput = page.getByLabel(PROFILE_NAME_LABEL_RE).first();
    this.searchKeywordsInput = page.getByRole('textbox', { name: /^Search Keywords$/iu });
    this.disallowedKeywordsInput = page.getByRole('textbox', { name: EXCLUDED_KEYWORDS_RE });

    this.remoteCheckbox = page.getByRole('checkbox', { name: REMOTE_RE });
    this.hybridCheckbox = page.getByRole('checkbox', { name: HYBRID_RE });
    this.onsiteCheckbox = page.getByRole('checkbox', { name: ONSITE_RE });
    this.flexibleCheckbox = page.getByRole('checkbox', { name: FLEXIBLE_RE });

    this.openToRelocationSwitch = page
      .getByRole('switch', { name: RELOCATION_RE })
      .or(page.getByLabel(RELOCATION_RE));

    this.notificationThresholdSlider = page.getByLabel(NOTIFICATION_THRESHOLD_RE);
    this.autoTailorThresholdSlider = page.getByLabel(AUTO_TAILOR_THRESHOLD_RE);

    // Experience
    this.experienceYearsInput = page.getByRole('spinbutton', { name: YEARS_OF_EXPERIENCE_RE });

    // Salary
    this.currencySelect = page.getByLabel(CURRENCY_RE);
    this.paymentFrequencySelect = page.getByLabel(PAYMENT_FREQUENCY_RE);
    this.minSalaryInput = page.getByLabel(MINIMUM_SALARY_RE);
    this.targetSalaryInput = page.getByLabel(TARGET_SALARY_RE);

    // Skills
    this.skillsInput = page
      .locator('label')
      .filter({ hasText: YOUR_SKILLS_RE })
      .locator('xpath=..')
      .getByRole('button')
      .first();

    this.submitButton = page.getByRole('button', { name: CREATE_SAVE_SUBMIT_RE });
    this.cancelButton = page.getByRole('button', { name: CANCEL_RE });
  }

  async fillProfileName(name: string): Promise<void> {
    await this.profileNameInput.clear();
    await this.profileNameInput.fill(name);
  }

  async addSearchKeyword(keyword: string): Promise<void> {
    await this.searchKeywordsInput.fill(keyword);
    await this.searchKeywordsInput.press('Enter');

    const normalizedKeyword = keyword.trim().toLowerCase();
    const tags = this.searchKeywordsInput.locator('xpath=preceding-sibling::ul');
    await expect(tags.getByText(normalizedKeyword, { exact: true })).toBeVisible();
  }

  async addSearchKeywords(keywords: string[]): Promise<void> {
    await keywords.reduce(
      (chain, keyword) => chain.then(() => this.addSearchKeyword(keyword)),
      Promise.resolve(),
    );
  }

  async addDisallowedKeyword(keyword: string): Promise<void> {
    await this.disallowedKeywordsInput.fill(keyword);
    await this.disallowedKeywordsInput.press('Enter');
  }

  async addDisallowedKeywords(keywords: string[]): Promise<void> {
    await keywords.reduce(
      (chain, keyword) => chain.then(() => this.addDisallowedKeyword(keyword)),
      Promise.resolve(),
    );
  }

  async selectWorkArrangement(arrangement: WorkArrangement): Promise<void> {
    const checkboxMap: Record<string, Locator> = {
      remote: this.remoteCheckbox,
      hybrid: this.hybridCheckbox,
      onsite: this.onsiteCheckbox,
      flexible: this.flexibleCheckbox,
    };
    const checkbox = checkboxMap[arrangement];
    if (!checkbox) {
      throw new Error(`Unknown work arrangement: ${arrangement}`);
    }
    await expect(checkbox).toBeVisible({ timeout: TIMEOUTS.elementVisible });
    await checkbox.check();
  }

  async selectWorkArrangements(arrangements: WorkArrangement[]): Promise<void> {
    await arrangements.reduce(
      (chain, arrangement) => chain.then(() => this.selectWorkArrangement(arrangement)),
      Promise.resolve(),
    );
  }

  async toggleRelocation(enabled: boolean): Promise<void> {
    const isChecked = await this.openToRelocationSwitch.isChecked();
    if (isChecked !== enabled) {
      await this.openToRelocationSwitch.click();
    }
  }

  async submit(): Promise<void> {
    await expect(this.submitButton).toBeEnabled({ timeout: TIMEOUTS.shortAction });
    await this.submitButton.click();
  }

  async cancel(): Promise<void> {
    await this.cancelButton.click();
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

  async addSkill(skill: string): Promise<void> {
    await this.skillsInput.click();
    const commandInput = this.page.locator('[cmdk-input]');
    await commandInput.pressSequentially(skill, { delay: 20 });
    const firstResult = this.page.locator('[cmdk-item]').first();
    await firstResult.waitFor({ state: 'visible', timeout: 10_000 });
    await commandInput.press('Enter');
  }

  async addSkills(skills: string[]): Promise<void> {
    await skills.reduce(
      (chain, skill) => chain.then(() => this.addSkill(skill)),
      Promise.resolve(),
    );
  }

  async fillCompleteProfile(data: ProfileFormData): Promise<void> {
    await this.fillProfileName(data.name);
    await this.addSearchKeywords(data.searchKeywords);

    if (data.disallowedKeywords && data.disallowedKeywords.length > 0) {
      await this.addDisallowedKeywords(data.disallowedKeywords);
    }

    if (data.workArrangements && data.workArrangements.length > 0) {
      await this.selectWorkArrangements(data.workArrangements);
    }

    if (data.openToRelocation !== undefined) {
      await this.toggleRelocation(data.openToRelocation);
    }

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
  }
}
