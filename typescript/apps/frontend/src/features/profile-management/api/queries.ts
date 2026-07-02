import { useQuery } from '@tanstack/react-query';
import { $api, CACHE_CONFIG } from '@/shared/api/index.ts';

interface UseProfilesOptions {
  refetchInterval?: number | false;
}
export const profilesListQueryOptions = $api.queryOptions(
  'get',
  '/api/v1/profiles',
  { params: { query: { page: 1, page_size: 100 } } },
  { staleTime: CACHE_CONFIG.USER_DATA.staleTime, gcTime: CACHE_CONFIG.USER_DATA.gcTime },
);

export function useProfiles(options?: UseProfilesOptions) {
  return useQuery({ ...profilesListQueryOptions, ...options });
}

export function profileDetailQueryOptions(profileId: string) {
  return $api.queryOptions(
    'get',
    '/api/v1/profiles/{pref_id}',
    { params: { path: { pref_id: profileId } } },
    {
      enabled: Boolean(profileId),
      staleTime: CACHE_CONFIG.USER_DATA.staleTime,
      gcTime: CACHE_CONFIG.USER_DATA.gcTime,
    },
  );
}

export function useProfile(profileId: string) {
  return useQuery(profileDetailQueryOptions(profileId));
}

export function useResolvedFeatureImportance(profileId: string) {
  return $api.useQuery(
    'get',
    '/api/v1/profiles/{pref_id}/resolved-importance',
    { params: { path: { pref_id: profileId } } },
    {
      enabled: Boolean(profileId),
      staleTime: CACHE_CONFIG.USER_DATA.staleTime,
      gcTime: CACHE_CONFIG.USER_DATA.gcTime,
    },
  );
}
