import type {
  CurrencyCode,
  PaymentFrequency,
  ProfileCreate,
  ProfileResponse,
  ProfileUpdate,
  SkillSearchResult,
} from '@/shared/api';
import type { ProfileFormValues } from '../model/index.ts';

/** Factor for converting between API 0-1 fraction and UI 0-100 percentage */
const PERCENTAGE_SCALE: number = 100;

/**
 * Converts a UI percentage (0-100) to an API ratio (0-1), preserving null.
 * Uses explicit null check so that 0 is correctly preserved as 0 (not collapsed to null).
 */
function percentageToRatio(value: number): number;
function percentageToRatio(value: number | null): number | null;
function percentageToRatio(value: number | null): number | null {
  if (value === null) {
    return null;
  }
  return value / PERCENTAGE_SCALE;
}

/**
 * Converts a raw API threshold (0-1 scale) to a UI percentage (0-100), preserving null.
 * Uses explicit null/undefined check so that 0 is correctly preserved as 0 (not null).
 */
function ratioToPercentage(value: number): number;
function ratioToPercentage(value: number | null | undefined): number | null;
function ratioToPercentage(value: number | null | undefined): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  return Math.round(value * PERCENTAGE_SCALE);
}

/**
 * Transforms form values to API create payload.
 * Handles percentage conversion (UI uses 0-100, API uses 0-1).
 */
export function formValuesToCreatePayload(values: ProfileFormValues): ProfileCreate {
  return {
    pref_name: values.pref_name,
    search_keywords: values.search_keywords.map((keyword) => keyword.trim()),
    user_skills: values.user_skills.map((skill) => skill.id),
    disallowed_keywords: values.disallowed_keywords,
    work_arrangements: values.work_arrangements as Array<'ON_SITE' | 'HYBRID' | 'REMOTE'>,
    notification_threshold: percentageToRatio(values.notification_threshold),
    auto_tailor_threshold: percentageToRatio(values.auto_tailor_threshold),
    open_to_relocation: values.open_to_relocation,
    salary_preference: {
      min_salary: {
        minor_units: values.salary_preference.min_salary.minor_units,
        currency: values.salary_preference.min_salary.currency as CurrencyCode,
      },
      target_salary: {
        minor_units: values.salary_preference.target_salary.minor_units,
        currency: values.salary_preference.target_salary.currency as CurrencyCode,
      },
      preferred_frequency: values.salary_preference.preferred_frequency as PaymentFrequency,
    },
    experience_preference: {
      experience_years: values.experience_preference.experience_years,
      seniority_levels: (values.experience_preference.seniority_levels.length > 0
        ? values.experience_preference.seniority_levels
        : ['MID']) as Array<
        | 'INTERN'
        | 'ENTRY'
        | 'MID'
        | 'SENIOR'
        | 'STAFF'
        | 'MANAGER'
        | 'DIRECTOR'
        | 'VP'
        | 'EXECUTIVE'
      >,
    },
  };
}

/**
 * Transforms form values to API update payload.
 * Same conversion logic as create.
 */
export function formValuesToUpdatePayload(values: ProfileFormValues): ProfileUpdate {
  return formValuesToCreatePayload(values);
}

/**
 * Transforms API profile response to form values for editing.
 * Handles percentage conversion (API uses 0-1, UI uses 0-100).
 *
 * @param profile - API profile response containing literal search terms and user skill IDs.
 * @param hydratedUserSkills - Pre-resolved user skill objects from hydrateSkillIds().
 *   Defaults to empty - caller (useProfileEditForm) is responsible for async hydration.
 */
export function profileToFormValues(
  profile: ProfileResponse,
  hydratedUserSkills: SkillSearchResult[] = [],
): ProfileFormValues {
  return {
    pref_name: profile.pref_name,
    search_keywords: [...profile.search_keywords],
    user_skills: hydratedUserSkills,
    disallowed_keywords: [...profile.disallowed_keywords],
    work_arrangements: [...profile.work_arrangements],
    notification_threshold: ratioToPercentage(profile.notification_threshold),
    auto_tailor_threshold: ratioToPercentage(profile.auto_tailor_threshold),
    open_to_relocation: profile.open_to_relocation,
    salary_preference: {
      min_salary: {
        minor_units: profile.salary_preference?.min_salary?.minor_units ?? 0,
        currency: profile.salary_preference?.min_salary?.currency ?? 'USD',
      },
      target_salary: {
        minor_units: profile.salary_preference?.target_salary?.minor_units ?? 0,
        currency: profile.salary_preference?.target_salary?.currency ?? 'USD',
      },
      preferred_frequency: profile.salary_preference?.preferred_frequency ?? 'ANNUALLY',
    },
    experience_preference: {
      experience_years: profile.experience_preference?.experience_years ?? 0,
      seniority_levels: [
        ...(profile.experience_preference?.seniority_levels?.length
          ? profile.experience_preference.seniority_levels
          : ['MID']),
      ],
    },
  };
}
