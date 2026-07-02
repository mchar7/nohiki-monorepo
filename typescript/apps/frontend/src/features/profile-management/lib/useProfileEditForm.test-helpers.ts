import { vi } from 'vitest';
import type { ProfileResponse, SkillSearchResult } from '@/shared/api';
import type { useUpdateProfile } from '../api/index.ts';

export const MOCK_PROFILE: ProfileResponse = {
  id: 'profile-1',
  user_id: 'user-1',
  pref_name: 'Frontend Engineer',
  search_keywords: ['platform developer', 'distributed systems'],
  user_skills: ['skill-ts'],
  disallowed_keywords: [],
  work_arrangements: ['REMOTE'],
  notification_threshold: 0.7,
  auto_tailor_threshold: 0.85,
  open_to_relocation: false,
  salary_preference: null,
  experience_preference: null,
};

export const MOCK_HYDRATED_USER_SKILLS: SkillSearchResult[] = [
  { id: 'skill-ts', name: 'TypeScript', display_name: 'TypeScript', category: 'Languages' },
];

/**
 * Builds a mock UseMutationResult with idle-state defaults.
 *
 * Cast required because spreading Partial<DiscriminatedUnion> overrides
 * prevents TypeScript from narrowing the status discriminant.
 */
export function mockMutationResult(
  overrides: Partial<ReturnType<typeof useUpdateProfile>>,
): ReturnType<typeof useUpdateProfile> {
  return {
    mutateAsync: vi.fn(),
    mutate: vi.fn(),
    isPending: false,
    isIdle: true,
    isSuccess: false,
    isError: false,
    isPaused: false,
    status: 'idle' as const,
    data: undefined,
    error: null,
    variables: undefined,
    failureCount: 0,
    failureReason: null,
    reset: vi.fn(),
    context: undefined,
    submittedAt: 0,
    ...overrides,
  } as ReturnType<typeof useUpdateProfile>;
}
