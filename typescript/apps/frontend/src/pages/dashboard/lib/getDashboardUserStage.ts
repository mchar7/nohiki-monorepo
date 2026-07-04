export type UserStage = 'new' | 'getting-started' | 'active';

interface UserStageInput {
  profileCount: number;
  correlationCount: number;
  documentCount: number;
}

/**
 * Determines the user's onboarding stage based on their data counts.
 * Pure function with no side effects or hooks.
 *
 * - `'new'`: No profiles created yet
 * - `'getting-started'`: Has profiles but missing correlations or documents
 * - `'active'`: Has profiles, correlations, and documents
 */
export function getDashboardUserStage(input: UserStageInput): UserStage {
  if (input.profileCount === 0) {
    return 'new';
  }
  if (input.correlationCount === 0 || input.documentCount === 0) {
    return 'getting-started';
  }
  return 'active';
}
