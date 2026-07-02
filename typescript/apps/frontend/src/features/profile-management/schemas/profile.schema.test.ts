import type { TFunction } from 'i18next';
import { describe, expect } from 'vitest';
import enProfiles from '../../../../public/locales/en/profiles.json';
import frProfiles from '../../../../public/locales/fr-CA/profiles.json';
import { createProfileSchema, KEYWORDS_MAX_ITEMS } from './profile.schema.ts';

const mockT = ((key: string) => key) as TFunction<readonly ['profiles', 'common'], undefined>;
const schema = createProfileSchema(mockT);

/** Threshold range boundaries (percentage scale) */
const THRESHOLD_MIN = 50;
const THRESHOLD_MAX = 99;
const BELOW_THRESHOLD_MIN = 49;
const ABOVE_THRESHOLD_MAX = 100;
const PREF_NAME_MIN_LENGTH = 2;
const PREF_NAME_MAX_LENGTH = 100;
const PREF_NAME_OVER_MAX = 101;
/** Expected default notification threshold percentage */
const DEFAULT_NOTIFICATION_THRESHOLD = 70;
/** A valid auto-tailor threshold within the allowed range */
const VALID_AUTO_TAILOR = 75;

const VALID_KEYWORD = 'backend engineer';
const VALID_SKILL = { id: 'skill-react', name: 'React', display_name: 'React' };

const VALID_FORM_VALUES = {
  pref_name: 'Frontend Engineer',
  search_keywords: [VALID_KEYWORD],
  disallowed_keywords: [],
  user_skills: [],
  work_arrangements: ['REMOTE'],
  notification_threshold: DEFAULT_NOTIFICATION_THRESHOLD,
  auto_tailor_threshold: null,
  open_to_relocation: false,
  salary_preference: {
    min_salary: { minor_units: 5_000_000, currency: 'USD' },
    target_salary: { minor_units: 8_000_000, currency: 'USD' },
  },
  experience_preference: {
    experience_years: 3,
    seniority_levels: ['MID'],
  },
};

describe('search_keywords term validation', () => {
  test('accepts trimmed human job discovery terms', () => {
    expect(schema.safeParse(VALID_FORM_VALUES).success).toBe(true);
  });

  test.each(['x', 'x'.repeat(101), '  '])('rejects invalid term %j', (term) => {
    expect(schema.safeParse({ ...VALID_FORM_VALUES, search_keywords: [term] }).success).toBe(false);
  });

  test('trims terms at the schema boundary', () => {
    const result = schema.parse({ ...VALID_FORM_VALUES, search_keywords: [' backend engineer '] });
    expect(result.search_keywords).toEqual(['backend engineer']);
  });

  test('rejects duplicate terms', () => {
    expect(
      schema.safeParse({
        ...VALID_FORM_VALUES,
        search_keywords: ['backend engineer', 'backend engineer'],
      }).success,
    ).toBe(false);
  });

  test('rejects empty and over-limit arrays', () => {
    expect(schema.safeParse({ ...VALID_FORM_VALUES, search_keywords: [] }).success).toBe(false);
    const tooMany = Array.from(
      { length: KEYWORDS_MAX_ITEMS + 1 },
      (_, index) => `platform developer ${String(index)}`,
    );
    expect(schema.safeParse({ ...VALID_FORM_VALUES, search_keywords: tooMany }).success).toBe(
      false,
    );
  });

  test('accepts exactly 20 unique terms of 2-100 characters', () => {
    const terms = Array.from(
      { length: KEYWORDS_MAX_ITEMS },
      (_, index) => `distributed systems ${String(index)}`,
    );
    expect(schema.safeParse({ ...VALID_FORM_VALUES, search_keywords: terms }).success).toBe(true);
    expect(
      schema.safeParse({ ...VALID_FORM_VALUES, search_keywords: ['ab', 'x'.repeat(100)] }).success,
    ).toBe(true);
  });
});

describe('disallowed_keywords term validation', () => {
  test('trims each term before returning profile values', () => {
    const result = schema.parse({
      ...VALID_FORM_VALUES,
      disallowed_keywords: [' legacy framework ', '\tphp\n'],
    });

    expect(result.disallowed_keywords).toEqual(['legacy framework', 'php']);
  });

  test.each(['x', 'x'.repeat(101), '  '])('matches search keyword term bounds for %j', (term) => {
    const result = schema.safeParse({
      ...VALID_FORM_VALUES,
      search_keywords: [term],
      disallowed_keywords: [term],
    });

    expect(result.success).toBe(false);
  });

  test('accepts disallowed terms at both length boundaries', () => {
    const result = schema.safeParse({
      ...VALID_FORM_VALUES,
      disallowed_keywords: ['ab', 'x'.repeat(100)],
    });

    expect(result.success).toBe(true);
  });

  test('rejects duplicate disallowed terms after trimming', () => {
    const result = schema.safeParse({
      ...VALID_FORM_VALUES,
      disallowed_keywords: ['legacy framework', ' legacy framework '],
    });

    expect(result.success).toBe(false);
  });
  test('rejects more than the shared keyword item limit', () => {
    const terms = Array.from(
      { length: KEYWORDS_MAX_ITEMS + 1 },
      (_, index) => `legacy framework ${String(index)}`,
    );

    expect(schema.safeParse({ ...VALID_FORM_VALUES, disallowed_keywords: terms }).success).toBe(
      false,
    );
  });
});

describe('search_keywords localized minimum contract', () => {
  test('states the same one-keyword minimum in English and French', () => {
    expect(enProfiles.validation.searchKeywords.required).toBe(
      'At least one search keyword is required',
    );
    expect(frProfiles.validation.searchKeywords.required).toBe(
      'Au moins un mot-clé de recherche est requis',
    );
  });
});

describe('pref_name validation', () => {
  test('rejects name shorter than min length', () => {
    const values = { ...VALID_FORM_VALUES, pref_name: 'X'.repeat(PREF_NAME_MIN_LENGTH - 1) };
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
  });

  test('accepts name at min length', () => {
    const values = { ...VALID_FORM_VALUES, pref_name: 'X'.repeat(PREF_NAME_MIN_LENGTH) };
    const result = schema.safeParse(values);
    expect(result.success).toBe(true);
  });

  test('rejects name exceeding max length', () => {
    const values = { ...VALID_FORM_VALUES, pref_name: 'X'.repeat(PREF_NAME_OVER_MAX) };
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
  });

  test('accepts name at max length', () => {
    const values = { ...VALID_FORM_VALUES, pref_name: 'X'.repeat(PREF_NAME_MAX_LENGTH) };
    const result = schema.safeParse(values);
    expect(result.success).toBe(true);
  });
});

describe('notification_threshold validation', () => {
  test('rejects null (notification threshold is required)', () => {
    const values = { ...VALID_FORM_VALUES, notification_threshold: null };
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
  });

  test('accepts valid threshold within range', () => {
    const result = schema.safeParse(VALID_FORM_VALUES);
    expect(result.success).toBe(true);
  });

  test('rejects value below minimum', () => {
    const values = { ...VALID_FORM_VALUES, notification_threshold: BELOW_THRESHOLD_MIN };
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
  });

  test('accepts value at minimum', () => {
    const values = { ...VALID_FORM_VALUES, notification_threshold: THRESHOLD_MIN };
    const result = schema.safeParse(values);
    expect(result.success).toBe(true);
  });

  test('rejects value above maximum', () => {
    const values = { ...VALID_FORM_VALUES, notification_threshold: ABOVE_THRESHOLD_MAX };
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
  });

  test('accepts value at maximum', () => {
    const values = { ...VALID_FORM_VALUES, notification_threshold: THRESHOLD_MAX };
    const result = schema.safeParse(values);
    expect(result.success).toBe(true);
  });
});

describe('auto_tailor_threshold validation', () => {
  test('accepts null', () => {
    const values = { ...VALID_FORM_VALUES, auto_tailor_threshold: null };
    const result = schema.safeParse(values);
    expect(result.success).toBe(true);
  });

  test('accepts valid threshold within range', () => {
    const values = { ...VALID_FORM_VALUES, auto_tailor_threshold: VALID_AUTO_TAILOR };
    const result = schema.safeParse(values);
    expect(result.success).toBe(true);
  });

  test('rejects value below minimum', () => {
    const values = { ...VALID_FORM_VALUES, auto_tailor_threshold: BELOW_THRESHOLD_MIN };
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
  });

  test('rejects value above maximum', () => {
    const values = { ...VALID_FORM_VALUES, auto_tailor_threshold: ABOVE_THRESHOLD_MAX };
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
  });
});

describe('experience_preference validation', () => {
  test('rejects an empty seniority selection', () => {
    const values = {
      ...VALID_FORM_VALUES,
      experience_preference: { experience_years: 3, seniority_levels: [] },
    };

    expect(schema.safeParse(values).success).toBe(false);
  });
});

describe('user_skills array constraints', () => {
  test('accepts empty user_skills array (no minimum required)', () => {
    const values = { ...VALID_FORM_VALUES, user_skills: [] };
    const result = schema.safeParse(values);
    expect(result.success).toBe(true);
  });

  test('accepts valid skill objects in user_skills', () => {
    const values = { ...VALID_FORM_VALUES, user_skills: [VALID_SKILL] };
    const result = schema.safeParse(values);
    expect(result.success).toBe(true);
  });

  test('rejects exceeding max items in user_skills', () => {
    const tooMany = Array.from({ length: KEYWORDS_MAX_ITEMS + 1 }, (_, i) => ({
      ...VALID_SKILL,
      id: `skill-${String(i)}`,
    }));
    const values = { ...VALID_FORM_VALUES, user_skills: tooMany };
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
  });

  test('accepts exactly max items in user_skills', () => {
    const maxSkills = Array.from({ length: KEYWORDS_MAX_ITEMS }, (_, i) => ({
      ...VALID_SKILL,
      id: `skill-${String(i)}`,
    }));
    const values = { ...VALID_FORM_VALUES, user_skills: maxSkills };
    const result = schema.safeParse(values);
    expect(result.success).toBe(true);
  });
});
