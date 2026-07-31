import { describe, expect } from 'vitest';
import { PROFILE_FORM_DEFAULTS } from './profile.schema.ts';

/** Expected default notification threshold percentage */
const DEFAULT_NOTIFICATION_THRESHOLD = 70;

describe('PROFILE_FORM_DEFAULTS', () => {
  test('has notification_threshold of 70', () => {
    expect(PROFILE_FORM_DEFAULTS.notification_threshold).toBe(DEFAULT_NOTIFICATION_THRESHOLD);
  });

  test('has auto_tailor_threshold of null', () => {
    expect(PROFILE_FORM_DEFAULTS.auto_tailor_threshold).toBeNull();
  });

  test('has empty search_keywords', () => {
    expect(PROFILE_FORM_DEFAULTS.search_keywords).toEqual([]);
  });

  test('has empty user_skills', () => {
    expect(PROFILE_FORM_DEFAULTS.user_skills).toEqual([]);
  });

  test('has empty pref_name', () => {
    expect(PROFILE_FORM_DEFAULTS.pref_name).toBe('');
  });

  test('has open_to_relocation as false', () => {
    expect(PROFILE_FORM_DEFAULTS.open_to_relocation).toBe(false);
  });

  test('has a non-empty default seniority selection', () => {
    expect(PROFILE_FORM_DEFAULTS.experience_preference.seniority_levels.length).toBeGreaterThan(0);
  });
});
