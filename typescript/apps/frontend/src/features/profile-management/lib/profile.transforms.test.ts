import { describe, expect } from 'vitest';
import type { ProfileResponse, SkillSearchResult } from '@/shared/api';
import type { ProfileFormValues } from '../model/index.ts';
import {
  formValuesToCreatePayload,
  formValuesToUpdatePayload,
  profileToFormValues,
} from './profile.transforms.ts';

const MOCK_USER_SKILL: SkillSearchResult = {
  id: 'skill-react',
  name: 'React',
  display_name: 'React',
  description: 'UI library',
  category: 'Frameworks',
};

/** API ratio for 70% threshold */
const NOTIFICATION_RATIO = 0.7;
/** API ratio for 85% threshold */
const AUTO_TAILOR_RATIO = 0.85;
/** UI percentage for 70% threshold */
const NOTIFICATION_PERCENTAGE = 70;
/** UI percentage for 85% threshold */
const AUTO_TAILOR_PERCENTAGE = 85;
/** Precision digits for floating-point comparison */
const FLOAT_PRECISION = 5;

const MOCK_PROFILE_RESPONSE: ProfileResponse = {
  id: 'profile-1',
  user_id: 'user-1',
  pref_name: 'Backend Engineer',
  search_keywords: ['backend engineer', 'distributed systems'],
  disallowed_keywords: ['php'],
  work_arrangements: ['REMOTE', 'HYBRID'],
  notification_threshold: NOTIFICATION_RATIO,
  auto_tailor_threshold: AUTO_TAILOR_RATIO,
  open_to_relocation: false,
  salary_preference: {
    min_salary: { minor_units: 8_000_000, currency: 'USD' },
    target_salary: { minor_units: 12_000_000, currency: 'USD' },
    preferred_frequency: 'ANNUALLY',
  },
  experience_preference: {
    experience_years: 5,
    seniority_levels: ['SENIOR', 'STAFF'],
  },
};

const BASE_FORM_VALUES: ProfileFormValues = {
  pref_name: 'Backend Engineer',
  search_keywords: ['backend engineer', 'distributed systems'],
  disallowed_keywords: ['php'],
  user_skills: [MOCK_USER_SKILL],
  work_arrangements: ['REMOTE', 'HYBRID'],
  notification_threshold: NOTIFICATION_PERCENTAGE,
  auto_tailor_threshold: AUTO_TAILOR_PERCENTAGE,
  open_to_relocation: false,
  salary_preference: {
    min_salary: { minor_units: 8_000_000, currency: 'USD' },
    target_salary: { minor_units: 12_000_000, currency: 'USD' },
  },
  experience_preference: {
    experience_years: 5,
    seniority_levels: ['SENIOR', 'STAFF'],
  },
};

describe('formValuesToCreatePayload', () => {
  test('preserves exact search keyword strings in create payloads', () => {
    const result = formValuesToCreatePayload(BASE_FORM_VALUES);
    expect(result.search_keywords).toEqual(['backend engineer', 'distributed systems']);
  });

  test.each([0, 5, 50])('preserves %i experience years in create payloads', (experienceYears) => {
    const values: ProfileFormValues = {
      ...BASE_FORM_VALUES,
      experience_preference: {
        ...BASE_FORM_VALUES.experience_preference,
        experience_years: experienceYears,
      },
    };

    expect(formValuesToCreatePayload(values).experience_preference.experience_years).toBe(
      experienceYears,
    );
  });

  test.each([0, 5, 50])('preserves %i experience years in update payloads', (experienceYears) => {
    const values: ProfileFormValues = {
      ...BASE_FORM_VALUES,
      experience_preference: {
        ...BASE_FORM_VALUES.experience_preference,
        experience_years: experienceYears,
      },
    };

    expect(formValuesToUpdatePayload(values).experience_preference?.experience_years).toBe(
      experienceYears,
    );
  });

  test('extracts user_skills IDs from SkillSearchResult objects', () => {
    const result = formValuesToCreatePayload(BASE_FORM_VALUES);
    expect(result.user_skills).toEqual(['skill-react']);
  });

  test('maps empty user_skills to empty array', () => {
    const values: ProfileFormValues = { ...BASE_FORM_VALUES, user_skills: [] };
    const result = formValuesToCreatePayload(values);
    expect(result.user_skills).toEqual([]);
  });

  test('converts notification_threshold from percentage to fraction', () => {
    const result = formValuesToCreatePayload(BASE_FORM_VALUES);
    expect(result.notification_threshold).toBeCloseTo(NOTIFICATION_RATIO, FLOAT_PRECISION);
  });

  test('converts auto_tailor_threshold from percentage to fraction', () => {
    const result = formValuesToCreatePayload(BASE_FORM_VALUES);
    expect(result.auto_tailor_threshold).toBeCloseTo(AUTO_TAILOR_RATIO, FLOAT_PRECISION);
  });

  test('preserves auto_tailor_threshold of 0 as 0 (not null)', () => {
    const values: ProfileFormValues = { ...BASE_FORM_VALUES, auto_tailor_threshold: 0 };
    const result = formValuesToCreatePayload(values);
    expect(result.auto_tailor_threshold).toBe(0);
  });

  test('maps null auto_tailor_threshold to null', () => {
    const values: ProfileFormValues = { ...BASE_FORM_VALUES, auto_tailor_threshold: null };
    const result = formValuesToCreatePayload(values);
    expect(result.auto_tailor_threshold).toBeNull();
  });

  test('preserves notification_threshold of 0 as 0 (not null)', () => {
    const values: ProfileFormValues = {
      ...BASE_FORM_VALUES,
      notification_threshold: 0,
    } as ProfileFormValues;
    const result = formValuesToCreatePayload(values);
    expect(result.notification_threshold).toBe(0);
  });

  test('maps null notification_threshold to null', () => {
    const values = {
      ...BASE_FORM_VALUES,
      notification_threshold: null,
    } as unknown as ProfileFormValues;
    const result = formValuesToCreatePayload(values);
    expect(result.notification_threshold).toBeNull();
  });

  test('passes disallowed_keywords as-is', () => {
    const result = formValuesToCreatePayload(BASE_FORM_VALUES);
    expect(result.disallowed_keywords).toEqual(['php']);
  });

  test('passes work_arrangements as-is', () => {
    const result = formValuesToCreatePayload(BASE_FORM_VALUES);
    expect(result.work_arrangements).toEqual(['REMOTE', 'HYBRID']);
  });
});

describe('profileToFormValues - search terms and skill hydration', () => {
  test('round-trips search terms literally without hydration', () => {
    const result = profileToFormValues(MOCK_PROFILE_RESPONSE);
    expect(result.search_keywords).toEqual(['backend engineer', 'distributed systems']);
  });

  test('uses hydratedUserSkills for user_skills only', () => {
    const userSkills = [MOCK_USER_SKILL];
    const result = profileToFormValues(MOCK_PROFILE_RESPONSE, userSkills);
    expect(result.search_keywords).toEqual(MOCK_PROFILE_RESPONSE.search_keywords);
    expect(result.user_skills).toEqual(userSkills);
  });

  test('defaults user_skills to empty array when hydratedUserSkills omitted', () => {
    const result = profileToFormValues(MOCK_PROFILE_RESPONSE);
    expect(result.user_skills).toEqual([]);
  });
});

describe('profileToFormValues - experience preference defaults', () => {
  test('supplies a valid non-empty experience preference when the API omits it', () => {
    const profile = {
      ...MOCK_PROFILE_RESPONSE,
      experience_preference: undefined,
    } as unknown as ProfileResponse;

    const result = profileToFormValues(profile);

    expect(result.experience_preference.experience_years).toBeGreaterThanOrEqual(0);
    expect(result.experience_preference.seniority_levels.length).toBeGreaterThan(0);
  });
});

describe('profileToFormValues - field mapping', () => {
  test('converts notification_threshold from fraction to percentage', () => {
    const result = profileToFormValues(MOCK_PROFILE_RESPONSE);
    expect(result.notification_threshold).toBe(NOTIFICATION_PERCENTAGE);
  });

  test('converts auto_tailor_threshold from fraction to percentage', () => {
    const result = profileToFormValues(MOCK_PROFILE_RESPONSE);
    expect(result.auto_tailor_threshold).toBe(AUTO_TAILOR_PERCENTAGE);
  });

  test('preserves auto_tailor_threshold of 0 as 0 (not null)', () => {
    const profile: ProfileResponse = { ...MOCK_PROFILE_RESPONSE, auto_tailor_threshold: 0 };
    const result = profileToFormValues(profile);
    expect(result.auto_tailor_threshold).toBe(0);
  });

  test('maps null auto_tailor_threshold to null', () => {
    const profile: ProfileResponse = { ...MOCK_PROFILE_RESPONSE, auto_tailor_threshold: null };
    const result = profileToFormValues(profile);
    expect(result.auto_tailor_threshold).toBeNull();
  });

  test('preserves notification_threshold of 0 as 0 (not null)', () => {
    const profile: ProfileResponse = { ...MOCK_PROFILE_RESPONSE, notification_threshold: 0 };
    const result = profileToFormValues(profile);
    expect(result.notification_threshold).toBe(0);
  });

  test('maps null notification_threshold to null', () => {
    const profile = {
      ...MOCK_PROFILE_RESPONSE,
      notification_threshold: null,
    } as unknown as ProfileResponse;
    const result = profileToFormValues(profile);
    expect(result.notification_threshold).toBeNull();
  });

  test('copies disallowed_keywords into a new array', () => {
    const result = profileToFormValues(MOCK_PROFILE_RESPONSE);
    expect(result.disallowed_keywords).toEqual(['php']);
    expect(result.disallowed_keywords).not.toBe(MOCK_PROFILE_RESPONSE.disallowed_keywords);
  });

  test('copies work_arrangements into a new array', () => {
    const result = profileToFormValues(MOCK_PROFILE_RESPONSE);
    expect(result.work_arrangements).toEqual(['REMOTE', 'HYBRID']);
    expect(result.work_arrangements).not.toBe(MOCK_PROFILE_RESPONSE.work_arrangements);
  });
});
