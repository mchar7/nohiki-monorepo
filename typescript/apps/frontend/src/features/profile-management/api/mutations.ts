import { useQueryClient } from '@tanstack/react-query';
import type { PaginatedResponseProfileResponse, ProfileResponse } from '@/shared/api';
import { $api, invalidateByPath } from '@/shared/api/index.ts';
import { profileDetailQueryOptions, profilesListQueryOptions } from './queries.ts';

const DEFAULT_NOTIFICATION_THRESHOLD: number = 70;

export const PENDING_ID_PREFIX: string = '_pending_';

export function useCreateProfile() {
  const queryClient = useQueryClient();

  return $api.useMutation('post', '/api/v1/profiles', {
    onMutate: async (init) => {
      const { body } = init;
      const listKey = profilesListQueryOptions.queryKey;

      await queryClient.cancelQueries({ queryKey: listKey });
      const previousProfiles = queryClient.getQueryData<PaginatedResponseProfileResponse>(listKey);

      const optimisticProfile: ProfileResponse = {
        id: `${PENDING_ID_PREFIX}${crypto.randomUUID()}`,
        user_id: '',
        pref_name: body.pref_name,
        search_keywords: body.search_keywords ?? [],
        disallowed_keywords: body.disallowed_keywords ?? [],
        work_arrangements: body.work_arrangements ?? [],
        notification_threshold: body.notification_threshold ?? DEFAULT_NOTIFICATION_THRESHOLD,
        auto_tailor_threshold: body.auto_tailor_threshold ?? null,
        open_to_relocation: body.open_to_relocation ?? false,
        created_at: new Date().toISOString(),
        updated_at: null,
      };

      queryClient.setQueryData<PaginatedResponseProfileResponse>(listKey, (old) => {
        if (!old) {
          return {
            items: [optimisticProfile],
            total: 1,
            page: 1,
            page_size: 100,
            total_pages: 1,
            has_next: false,
            has_prev: false,
          };
        }
        return {
          ...old,
          items: [optimisticProfile, ...old.items],
          total: old.total + 1,
          total_pages: old.total_pages,
          has_next: old.has_next,
          has_prev: old.has_prev,
        };
      });

      return { previousProfiles };
    },
    onError: (_err, _init, context) => {
      if (context?.previousProfiles) {
        queryClient.setQueryData(profilesListQueryOptions.queryKey, context.previousProfiles);
      }
    },
  });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();

  return $api.useMutation('patch', '/api/v1/profiles/{pref_id}', {
    onMutate: async (init) => {
      const profileId = init.params.path.pref_id;
      const detailKey = profileDetailQueryOptions(profileId).queryKey;

      await queryClient.cancelQueries({ queryKey: detailKey });
      const previousProfile = queryClient.getQueryData<ProfileResponse>(detailKey);
      return { previousProfile, profileId };
    },
    onError: (_error, _init, context) => {
      if (context?.previousProfile) {
        const detailKey = profileDetailQueryOptions(context.profileId).queryKey;
        queryClient.setQueryData(detailKey, context.previousProfile);
      }
    },
    onSettled: () => invalidateByPath(queryClient, '/api/v1/profiles'),
  });
}

export function useDeleteProfile() {
  const queryClient = useQueryClient();

  return $api.useMutation('delete', '/api/v1/profiles/{pref_id}', {
    onMutate: async (init) => {
      const profileId = init.params.path.pref_id;
      const listKey = profilesListQueryOptions.queryKey;

      await queryClient.cancelQueries({ queryKey: listKey });
      const previousProfiles = queryClient.getQueryData<PaginatedResponseProfileResponse>(listKey);

      queryClient.setQueryData<PaginatedResponseProfileResponse>(listKey, (old) => {
        if (!old) {
          return old;
        }
        return {
          ...old,
          items: old.items.filter((p) => p.id !== profileId),
          total: Math.max(0, old.total - 1),
        };
      });
      return { previousProfiles };
    },
    onError: (_err, _init, context) => {
      if (context?.previousProfiles) {
        queryClient.setQueryData(profilesListQueryOptions.queryKey, context.previousProfiles);
      }
    },
    onSettled: () => invalidateByPath(queryClient, '/api/v1/profiles'),
  });
}

export function useSetFeatureImportance() {
  const queryClient = useQueryClient();

  return $api.useMutation('put', '/api/v1/profiles/{pref_id}/feature-importance', {
    onSuccess: () => invalidateByPath(queryClient, '/api/v1/profiles'),
  });
}

export function useSetDefaultFeatureImportance() {
  const queryClient = useQueryClient();

  return $api.useMutation('put', '/api/v1/profiles/settings/feature-importance', {
    onSuccess: () => invalidateByPath(queryClient, '/api/v1/profiles'),
  });
}

export function useAssociateAttachment() {
  const queryClient = useQueryClient();

  return $api.useMutation('post', '/api/v1/profiles/{pref_id}/attachments/{upload_id}', {
    onSuccess: (_data, init) => {
      const profileId = init.params.path.pref_id;
      const detailKey = profileDetailQueryOptions(profileId).queryKey;
      queryClient.invalidateQueries({ queryKey: detailKey });
    },
  });
}

export function useDisassociateAttachment() {
  const queryClient = useQueryClient();

  return $api.useMutation('delete', '/api/v1/profiles/{pref_id}/attachments/{upload_id}', {
    onSuccess: (_data, init) => {
      const profileId = init.params.path.pref_id;
      const detailKey = profileDetailQueryOptions(profileId).queryKey;
      queryClient.invalidateQueries({ queryKey: detailKey });
    },
  });
}
