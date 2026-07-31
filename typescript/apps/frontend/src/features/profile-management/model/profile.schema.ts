import type { TFunction } from 'i18next';
import { z } from 'zod';
import type { SkillSearchResult } from '@/shared/api';

const PREF_NAME_MIN_LENGTH: number = 2;
const PREF_NAME_MAX_LENGTH: number = 100;
const KEYWORDS_MIN_ITEMS: number = 1;
const KEYWORDS_MAX_ITEMS: number = 20;
const KEYWORD_MIN_LENGTH: number = 2;
const KEYWORD_MAX_LENGTH: number = 100;
/** Minimum valid threshold percentage - scores below this are not actionable */
const THRESHOLD_MIN: number = 50;
/** Maximum valid threshold percentage - 100% match is unrealistic */
const THRESHOLD_MAX: number = 99;
/** Default notification threshold (70%) applied to new profiles */
const DEFAULT_NOTIFICATION_THRESHOLD: number = 70;

function isSkillObject(val: unknown): val is SkillSearchResult {
  return (
    typeof val === 'object' &&
    val !== null &&
    'id' in val &&
    typeof val.id === 'string' &&
    'name' in val &&
    typeof val.name === 'string'
  );
}

type KeywordField = 'searchKeywords' | 'disallowedKeywords';

function createKeywordArraySchema(
  t: TFunction<readonly ['profiles', 'common'], undefined>,
  field: KeywordField,
  required: boolean,
) {
  const keywordSchema = z
    .string()
    .trim()
    .min(
      KEYWORD_MIN_LENGTH,
      t(`profiles:validation.${field}.minLength`, { min: KEYWORD_MIN_LENGTH }),
    )
    .max(
      KEYWORD_MAX_LENGTH,
      t(`profiles:validation.${field}.maxLength`, { max: KEYWORD_MAX_LENGTH }),
    );
  const keywords = z
    .array(keywordSchema)
    .max(
      KEYWORDS_MAX_ITEMS,
      t(`profiles:validation.${field}.maxItems`, { max: KEYWORDS_MAX_ITEMS }),
    )
    .refine((values) => new Set(values).size === values.length, {
      message: t(`profiles:validation.${field}.unique`),
    });

  return required
    ? keywords.min(KEYWORDS_MIN_ITEMS, t(`profiles:validation.${field}.required`))
    : keywords;
}

/**
 * Factory function to create profile form schema with localized validation messages.
 *
 */
export function createProfileSchema(t: TFunction<readonly ['profiles', 'common'], undefined>) {
  return z.object({
    pref_name: z
      .string()
      .min(
        PREF_NAME_MIN_LENGTH,
        t('profiles:validation.prefName.minLength', { min: PREF_NAME_MIN_LENGTH }),
      )
      .max(
        PREF_NAME_MAX_LENGTH,
        t('profiles:validation.prefName.maxLength', { max: PREF_NAME_MAX_LENGTH }),
      ),
    search_keywords: createKeywordArraySchema(t, 'searchKeywords', true),
    disallowed_keywords: createKeywordArraySchema(t, 'disallowedKeywords', false),
    user_skills: z
      .array(z.custom<SkillSearchResult>(isSkillObject))
      .max(
        KEYWORDS_MAX_ITEMS,
        t('profiles:validation.userSkills.maxItems', { max: KEYWORDS_MAX_ITEMS }),
      ),
    work_arrangements: z
      .array(z.string())
      .min(1, t('profiles:validation.workArrangements.required')),
    notification_threshold: z.number().min(THRESHOLD_MIN).max(THRESHOLD_MAX),
    auto_tailor_threshold: z.number().min(THRESHOLD_MIN).max(THRESHOLD_MAX).nullable(),
    open_to_relocation: z.boolean(),
    salary_preference: z.object({
      min_salary: z.object({ minor_units: z.number().int().min(0), currency: z.string() }),
      target_salary: z.object({ minor_units: z.number().int().min(0), currency: z.string() }),
      preferred_frequency: z.string().default('ANNUALLY'),
    }),
    experience_preference: z.object({
      experience_years: z.number().int().min(0).max(50),
      seniority_levels: z
        .array(z.string())
        .min(1, t('profiles:validation.experience.seniorityRequired')),
    }),
  });
}

/** Input type matches zodResolver's parameterization. Defaults are always provided via PROFILE_FORM_DEFAULTS. */
export type ProfileFormValues = z.input<ReturnType<typeof createProfileSchema>>;

/** Default values for creating a new profile */
export const PROFILE_FORM_DEFAULTS: ProfileFormValues = {
  pref_name: '',
  search_keywords: [],
  disallowed_keywords: [],
  user_skills: [],
  work_arrangements: ['REMOTE'],
  notification_threshold: DEFAULT_NOTIFICATION_THRESHOLD,
  auto_tailor_threshold: null,
  open_to_relocation: false,
  salary_preference: {
    min_salary: { minor_units: 0, currency: 'USD' },
    target_salary: { minor_units: 0, currency: 'USD' },
    preferred_frequency: 'ANNUALLY',
  },
  experience_preference: {
    experience_years: 0,
    seniority_levels: ['MID'],
  },
};

export { KEYWORDS_MAX_ITEMS };
