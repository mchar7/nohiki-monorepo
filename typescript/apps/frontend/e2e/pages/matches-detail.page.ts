import type { Locator, Page } from '@playwright/test';
import { BasePage } from './base.page.ts';

const SCORE_BREAKDOWN_RE = /score breakdown/iu;
const SKILL_MATCH_RE = /skill.*match/iu;
const LOCATION_RE = /location/iu;
const EXPERIENCE_RE = /experience/iu;
const WORK_ARRANGEMENT_RE = /work.*arrangement/iu;
const SALARY_RE = /salary/iu;
const RECENCY_RE = /recency/iu;
const SAVE_RE = /save/iu;
const APPLY_RE = /apply/iu;
const DISMISS_RE = /dismiss/iu;
const FEEDBACK_RE = /feedback/iu;
const ACCURATE_GOOD_RE = /accurate|good/iu;
const TOO_HIGH_RE = /too high|overstated/iu;
const TOO_LOW_RE = /too low|understated/iu;
const ADJUSTED_SCORE_RE = /adjusted.*score|new.*score/iu;
const REASON_EXPLANATION_RE = /reason|explanation/iu;
const REASON_EXPLAIN_RE = /reason|explain/iu;
const SUBMIT_ADJUSTMENT_RE = /submit.*adjustment|adjust/iu;
const GENERATE_RESUME_RE = /generate.*resume/iu;
const GENERATE_COVER_RE = /generate.*cover/iu;
const SCORE_DIGITS_RE = /(?<score>\d+(?:\.\d+)?)/gu;
const PERCENT_RE = /%/u;

export class MatchDetailPageV2 extends BasePage {
  readonly url = '/jobs/matches';

  readonly jobTitle: Locator;
  readonly companyName: Locator;
  readonly fitScore: Locator;
  readonly scoreBreakdown: Locator;

  readonly skillMatchScore: Locator;
  readonly locationScore: Locator;
  readonly experienceScore: Locator;
  readonly workArrangementScore: Locator;
  readonly salaryScore: Locator;
  readonly recencyScore: Locator;

  readonly saveButton: Locator;
  readonly applyButton: Locator;
  readonly dismissButton: Locator;

  readonly scoreFeedbackSection: Locator;
  readonly goodScoreButton: Locator;
  readonly tooHighButton: Locator;
  readonly tooLowButton: Locator;

  readonly scoreAdjustmentInput: Locator;
  readonly adjustmentReasonInput: Locator;
  readonly submitAdjustmentButton: Locator;

  readonly generateResumeButton: Locator;
  readonly generateCoverLetterButton: Locator;

  constructor(page: Page) {
    super(page);
    this.jobTitle = page.getByRole('heading', { level: 1 });
    this.companyName = page
      .locator('[aria-label*="company"]')
      .or(page.getByRole('heading', { level: 2 }));
    this.fitScore = page
      .locator('[aria-label*="fit score"]')
      .or(page.getByText(PERCENT_RE).first());
    this.scoreBreakdown = page.getByRole('region', { name: SCORE_BREAKDOWN_RE });

    this.skillMatchScore = page.getByText(SKILL_MATCH_RE).locator('..');
    this.locationScore = page.getByText(LOCATION_RE).locator('..');
    this.experienceScore = page.getByText(EXPERIENCE_RE).locator('..');
    this.workArrangementScore = page.getByText(WORK_ARRANGEMENT_RE).locator('..');
    this.salaryScore = page.getByText(SALARY_RE).locator('..');
    this.recencyScore = page.getByText(RECENCY_RE).locator('..');

    this.saveButton = page.getByRole('button', { name: SAVE_RE });
    this.applyButton = page.getByRole('button', { name: APPLY_RE });
    this.dismissButton = page.getByRole('button', { name: DISMISS_RE });

    this.scoreFeedbackSection = page.getByRole('group', { name: FEEDBACK_RE });
    this.goodScoreButton = page.getByRole('button', { name: ACCURATE_GOOD_RE });
    this.tooHighButton = page.getByRole('button', { name: TOO_HIGH_RE });
    this.tooLowButton = page.getByRole('button', { name: TOO_LOW_RE });

    this.scoreAdjustmentInput = page.getByLabel(ADJUSTED_SCORE_RE);
    this.adjustmentReasonInput = page
      .getByLabel(REASON_EXPLANATION_RE)
      .or(page.getByPlaceholder(REASON_EXPLAIN_RE));
    this.submitAdjustmentButton = page.getByRole('button', { name: SUBMIT_ADJUSTMENT_RE });

    this.generateResumeButton = page.getByRole('button', { name: GENERATE_RESUME_RE });
    this.generateCoverLetterButton = page.getByRole('button', { name: GENERATE_COVER_RE });
  }

  async gotoMatch(correlationId: string): Promise<void> {
    await this.page.goto(`/jobs/matches/${correlationId}`);
    await this.waitForPageLoad();
  }

  async getFitScore(): Promise<number> {
    const text = (await this.fitScore.textContent()) ?? '0';
    const match = SCORE_DIGITS_RE.exec(text);
    const scoreStr = match?.groups?.score;
    if (scoreStr) {
      return Number.parseFloat(scoreStr);
    }
    return 0;
  }

  async saveMatch(): Promise<void> {
    await this.saveButton.click();
  }

  async applyToJob(): Promise<void> {
    await this.applyButton.click();
  }

  async dismissMatch(): Promise<void> {
    await this.dismissButton.click();
  }

  async submitScoreFeedback(type: 'good' | 'too_high' | 'too_low'): Promise<void> {
    const button = {
      good: this.goodScoreButton,
      too_high: this.tooHighButton,
      too_low: this.tooLowButton,
    }[type];
    await button.click();
  }

  async adjustScore(newScore: number, reason: string): Promise<void> {
    await this.scoreAdjustmentInput.fill(String(newScore));
    await this.adjustmentReasonInput.fill(reason);
    await this.submitAdjustmentButton.click();
  }

  async generateResume(): Promise<void> {
    await this.generateResumeButton.click();
  }

  async generateCoverLetter(): Promise<void> {
    await this.generateCoverLetterButton.click();
  }

  isScoreBreakdownVisible(): Promise<boolean> {
    return this.scoreBreakdown.isVisible();
  }

  async getScoreBreakdownValues(): Promise<Record<string, number>> {
    const breakdown: Record<string, number> = {};

    const extractScore = async (locator: Locator, key: string): Promise<void> => {
      if (await locator.isVisible()) {
        const text = (await locator.textContent()) ?? '0';
        const match = SCORE_DIGITS_RE.exec(text);
        const scoreStr = match?.groups?.score;
        breakdown[key] = scoreStr ? Number.parseFloat(scoreStr) : 0;
      }
    };

    await extractScore(this.skillMatchScore, 'skillMatch');
    await extractScore(this.locationScore, 'location');
    await extractScore(this.experienceScore, 'experience');
    await extractScore(this.workArrangementScore, 'workArrangement');
    await extractScore(this.salaryScore, 'salary');
    await extractScore(this.recencyScore, 'recency');

    return breakdown;
  }
}
