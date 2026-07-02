import type { ProfileResponse } from '@/shared/api';

/** Default notification threshold set by the backend */
const DEFAULT_NOTIFICATION_THRESHOLD: number = 0.7;

/** Minimum search keywords for full score on that criterion */
const MIN_SEARCH_KEYWORDS: number = 3;

/** Maximum achievable score (remaining 15% reserved for future fields) */
const MAX_SCORE: number = 85;

interface ProfileCompleteness {
  readonly score: number;
  readonly maxScore: number;
  readonly suggestions: readonly string[];
}

interface CompletenessRule {
  readonly weight: number;
  readonly suggestionKey: string;
  readonly isMet: (profile: ProfileResponse) => boolean;
}

const COMPLETENESS_RULES: readonly CompletenessRule[] = [
  {
    weight: 10,
    suggestionKey: 'completeness.suggestions.prefName',
    isMet: (p: ProfileResponse): boolean => p.pref_name.trim().length > 0,
  },
  {
    weight: 20,
    suggestionKey: 'completeness.suggestions.searchKeywords',
    isMet: (p: ProfileResponse): boolean => p.search_keywords.length >= MIN_SEARCH_KEYWORDS,
  },
  {
    weight: 15,
    suggestionKey: 'completeness.suggestions.userSkills',
    isMet: (p: ProfileResponse): boolean => (p.user_skills ?? []).length > 0,
  },
  {
    weight: 10,
    suggestionKey: 'completeness.suggestions.workArrangements',
    isMet: (p: ProfileResponse): boolean => p.work_arrangements.length > 0,
  },
  {
    weight: 15,
    suggestionKey: 'completeness.suggestions.salaryPreference',
    isMet: (p: ProfileResponse): boolean =>
      p.salary_preference !== null && p.salary_preference !== undefined,
  },
  {
    weight: 10,
    suggestionKey: 'completeness.suggestions.experiencePreference',
    isMet: (p: ProfileResponse): boolean =>
      p.experience_preference !== null && p.experience_preference !== undefined,
  },
  {
    weight: 5,
    suggestionKey: 'completeness.suggestions.notificationThreshold',
    isMet: (p: ProfileResponse): boolean =>
      p.notification_threshold !== DEFAULT_NOTIFICATION_THRESHOLD,
  },
];

function useProfileCompleteness(profile: ProfileResponse): ProfileCompleteness {
  let score = 0;
  const suggestions: string[] = [];

  for (const rule of COMPLETENESS_RULES) {
    if (rule.isMet(profile)) {
      score += rule.weight;
    } else {
      suggestions.push(rule.suggestionKey);
    }
  }

  return { score, maxScore: MAX_SCORE, suggestions };
}

export { useProfileCompleteness };
