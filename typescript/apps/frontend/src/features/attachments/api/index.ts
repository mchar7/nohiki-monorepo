import { useQueryClient } from '@tanstack/react-query';
import type { PaginatedResponseAttachmentResponse } from '@/shared/api';
import { $api, CACHE_CONFIG, invalidateByPath } from '@/shared/api/index.ts';

const DEFAULT_ATTACHMENTS_PAGE: number = 1;
const DEFAULT_ATTACHMENTS_PAGE_SIZE: number = 100;

const attachmentsListQueryOptions = $api.queryOptions(
  'get',
  '/api/v1/attachments',
  {
    params: { query: { page: DEFAULT_ATTACHMENTS_PAGE, page_size: DEFAULT_ATTACHMENTS_PAGE_SIZE } },
  },
  { staleTime: CACHE_CONFIG.STATIC.staleTime, gcTime: CACHE_CONFIG.STATIC.gcTime },
);

function useAttachments(
  page: number = DEFAULT_ATTACHMENTS_PAGE,
  pageSize: number = DEFAULT_ATTACHMENTS_PAGE_SIZE,
) {
  return $api.useQuery(
    'get',
    '/api/v1/attachments',
    { params: { query: { page, page_size: pageSize } } },
    {
      staleTime: CACHE_CONFIG.STATIC.staleTime,
      gcTime: CACHE_CONFIG.STATIC.gcTime,
    },
  );
}

function useAttachment(uploadId: string) {
  return $api.useQuery(
    'get',
    '/api/v1/attachments/{upload_id}',
    { params: { path: { upload_id: uploadId } } },
    {
      enabled: Boolean(uploadId),
      staleTime: CACHE_CONFIG.STATIC.staleTime,
      gcTime: CACHE_CONFIG.STATIC.gcTime,
    },
  );
}

function useInitiateUpload() {
  return $api.useMutation('post', '/api/v1/attachments/initiate');
}

function useCompleteUpload() {
  const queryClient = useQueryClient();
  return $api.useMutation('post', '/api/v1/attachments/{upload_id}/complete', {
    onSuccess: () => invalidateByPath(queryClient, '/api/v1/attachments'),
  });
}

function useDeleteAttachment() {
  const queryClient = useQueryClient();
  const listKey = attachmentsListQueryOptions.queryKey;

  return $api.useMutation('delete', '/api/v1/attachments/{upload_id}', {
    onMutate: async (init) => {
      const uploadId = init.params.path.upload_id;
      await queryClient.cancelQueries({ queryKey: listKey });
      const previousList = queryClient.getQueryData<PaginatedResponseAttachmentResponse>(listKey);

      if (previousList) {
        queryClient.setQueryData<PaginatedResponseAttachmentResponse>(listKey, {
          ...previousList,
          items: previousList.items.filter((a) => a.id !== uploadId),
          total: previousList.total - 1,
        });
      }
      return { previousList };
    },
    onError: (_err, _init, context) => {
      if (context?.previousList) {
        queryClient.setQueryData(listKey, context.previousList);
      }
    },
    onSettled: () => invalidateByPath(queryClient, '/api/v1/attachments'),
  });
}

function useLinkAttachmentToProfile() {
  const queryClient = useQueryClient();
  return $api.useMutation('post', '/api/v1/profiles/{pref_id}/attachments/{upload_id}', {
    onSuccess: async () => {
      await Promise.all([
        invalidateByPath(queryClient, '/api/v1/attachments'),
        invalidateByPath(queryClient, '/api/v1/profiles'),
      ]);
    },
  });
}

function useUnlinkAttachmentFromProfile() {
  const queryClient = useQueryClient();
  return $api.useMutation('delete', '/api/v1/profiles/{pref_id}/attachments/{upload_id}', {
    onSuccess: async () => {
      await Promise.all([
        invalidateByPath(queryClient, '/api/v1/attachments'),
        invalidateByPath(queryClient, '/api/v1/profiles'),
      ]);
    },
  });
}

export {
  attachmentsListQueryOptions,
  useAttachment,
  useAttachments,
  useCompleteUpload,
  useDeleteAttachment,
  useInitiateUpload,
  useLinkAttachmentToProfile,
  useUnlinkAttachmentFromProfile,
};
