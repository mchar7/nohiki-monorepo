import { type UseMutationResult, useMutation } from '@tanstack/react-query';
import { awaitDocumentReady } from '@/entities/document';
import type { GenerateDocumentRequest } from '@/shared/api';
import { $api, CACHE_CONFIG, fetchClient } from '@/shared/api/index.ts';
import type { ApiErrorDetails } from './types.ts';

export const templateFamiliesQueryOptions = $api.queryOptions(
  'get',
  '/api/v1/template-families',
  { params: { query: { page: 1, page_size: 100 } } },
  { staleTime: CACHE_CONFIG.STATIC.staleTime, gcTime: CACHE_CONFIG.STATIC.gcTime },
);

export function useTemplateFamilies(params?: {
  namespace?: string;
  name?: string;
  page?: number;
  page_size?: number;
}) {
  const query: { page?: number; page_size?: number } = {};
  if (params?.page !== undefined) {
    query.page = params.page;
  }
  if (params?.page_size !== undefined) {
    query.page_size = params.page_size;
  }

  return $api.useQuery(
    'get',
    '/api/v1/template-families',
    { params: { query } },
    { staleTime: CACHE_CONFIG.STATIC.staleTime, gcTime: CACHE_CONFIG.STATIC.gcTime },
  );
}

export function useTemplateFamily(templateId: string | null) {
  return $api.useQuery(
    'get',
    '/api/v1/template-families/{template_id}',
    { params: { path: { template_id: templateId ?? '' } } },
    {
      enabled: Boolean(templateId),
      staleTime: CACHE_CONFIG.STATIC.staleTime,
      gcTime: CACHE_CONFIG.STATIC.gcTime,
    },
  );
}

export function useCreateTemplateFamily() {
  return $api.useMutation('post', '/api/v1/template-families');
}

export function useAddTemplateVersion() {
  return $api.useMutation('post', '/api/v1/template-families/{family_id}/versions');
}

export function useDownloadDocument(): UseMutationResult<
  void,
  ApiErrorDetails,
  GenerateDocumentRequest & { filename?: string }
> {
  return useMutation<void, ApiErrorDetails, GenerateDocumentRequest & { filename?: string }>({
    mutationFn: async ({
      filename,
      ...request
    }: GenerateDocumentRequest & { filename?: string }) => {
      const { data, error } = await fetchClient.POST('/api/v1/documents/generate', {
        body: { ...request, output_format: 'pdf' },
      });
      if (error) {
        throw error as ApiErrorDetails;
      }

      const { downloadUrl } = await awaitDocumentReady(data.request_id);
      const blobResponse = await fetch(downloadUrl);
      if (!blobResponse.ok) {
        throw new Error(`Document download failed with status ${blobResponse.status}`);
      }
      const blob = await blobResponse.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename ?? 'document.pdf';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
  });
}

export function useValidateTemplate() {
  return $api.useMutation('post', '/api/v1/template-families/validate');
}
