/**
 * Skill batch lookup utilities.
 *
 * Provides both a reactive TanStack Query hook and an imperative
 * function for resolving skill IDs to full SkillSearchResult objects
 * via POST /api/v1/skills/batch.
 *
 * Placement: shared/api - skill resolution is not feature-specific;
 * any feature displaying skill names from IDs can reuse these.
 */
import { useQuery } from '@tanstack/react-query';
import { fetchClient } from './client.ts';
import { CACHE_CONFIG } from './config.ts';
import type { SkillSearchResult } from './types.ts';

const SKILL_BATCH_SIZE: number = 100;

/**
 * Reactive hook for batch skill resolution.
 *
 * Fetches full skill objects from an array of skill IDs.
 * Automatically disabled when the ID array is empty.
 */
export function useSkillBatch(
  skillIds: readonly string[],
  options?: { readonly enabled?: boolean },
) {
  const uniqueIds = [...new Set(skillIds)];

  return useQuery({
    queryKey: ['skills', 'batch', uniqueIds],
    queryFn: async () => ({ skills: await hydrateSkillIds(uniqueIds) }),
    enabled: uniqueIds.length > 0 && (options?.enabled ?? true),
    staleTime: CACHE_CONFIG.STATIC.staleTime,
    gcTime: CACHE_CONFIG.STATIC.gcTime,
  });
}

/**
 * Imperatively hydrate skill IDs into full SkillSearchResult objects.
 *
 * Uses fetchClient.POST for type-safe batch lookup. This function is
 * intentionally imperative (not a React hook) because it is called from
 * async form initialisation code outside the React render cycle
 * (see useProfileEditForm.ts). $api.useQuery cannot be used here.
 * The server-side Redis cache (10 min TTL) handles repeat calls efficiently.
 * Skills that fail to resolve are silently dropped by the API.
 *
 * @param skillIds - Skill UUIDs to resolve. Duplicate IDs are ignored.
 * @returns Resolved skills in first-requested ID order.
 */
export async function hydrateSkillIds(skillIds: readonly string[]): Promise<SkillSearchResult[]> {
  const uniqueIds = [...new Set(skillIds)];
  if (uniqueIds.length === 0) {
    return [];
  }

  const requests: Promise<SkillSearchResult[]>[] = [];
  for (let offset = 0; offset < uniqueIds.length; offset += SKILL_BATCH_SIZE) {
    const chunk = uniqueIds.slice(offset, offset + SKILL_BATCH_SIZE);
    requests.push(
      fetchClient
        .POST('/api/v1/skills/batch', { body: { skill_ids: chunk } })
        .then(({ data, error }) => {
          if (error) {
            throw error;
          }
          return data.skills;
        }),
    );
  }

  const resolvedById = new Map(
    (await Promise.all(requests)).flat().map((skill) => [skill.id, skill] as const),
  );
  return uniqueIds.flatMap((id) => {
    const skill = resolvedById.get(id);
    return skill === undefined ? [] : [skill];
  });
}
