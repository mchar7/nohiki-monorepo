import { useQueryClient } from '@tanstack/react-query';
import { $api, invalidateByPath } from '@/shared/api/index.ts';

function useGenerateDocument() {
  const queryClient = useQueryClient();
  return $api.useMutation('post', '/api/v1/documents/generate', {
    onSuccess: () => invalidateByPath(queryClient, '/api/v1/documents'),
  });
}

function useGenerateTailoredDocument() {
  const queryClient = useQueryClient();
  return $api.useMutation('post', '/api/v1/documents/generate-tailored', {
    onSuccess: () => invalidateByPath(queryClient, '/api/v1/documents'),
  });
}

export { useGenerateDocument, useGenerateTailoredDocument };
