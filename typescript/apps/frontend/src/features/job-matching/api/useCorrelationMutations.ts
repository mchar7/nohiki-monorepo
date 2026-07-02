import { useQueryClient } from '@tanstack/react-query';
import type {
  CorrelationStatus,
  FeedbackType,
  JobCorrelationResponse,
  PaginatedResponseJobCorrelationResponse,
} from '@/shared/api';
import { $api, invalidateByPath } from '@/shared/api/index.ts';

/** Map from feedback action to the resulting correlation status for optimistic updates. */
const feedbackToStatus: Partial<Record<FeedbackType, CorrelationStatus>> = {
  VIEWED: 'VIEWED',
  SAVED: 'SAVED',
  APPLIED: 'APPLIED',
  DISMISSED: 'DISMISSED',
};

const correlationsListKey = ['get', '/api/v1/listings/correlations/mine'] as const;

interface FeedbackMutationContext {
  correlationId: string;
  previousCorrelation: JobCorrelationResponse | undefined;
  previousLists: [readonly unknown[], PaginatedResponseJobCorrelationResponse | undefined][];
}

function useRecordFeedback() {
  const queryClient = useQueryClient();

  return $api.useMutation('post', '/api/v1/correlations/{correlation_id}/feedback', {
    onMutate: async (init): Promise<FeedbackMutationContext> => {
      const correlationId = init.params.path.correlation_id;
      const detailKey = $api.queryOptions('get', '/api/v1/listings/correlations/{correlation_id}', {
        params: { path: { correlation_id: correlationId } },
      }).queryKey;
      const newStatus = feedbackToStatus[init.body.feedback_type];

      await Promise.all([
        queryClient.cancelQueries({ queryKey: detailKey }),
        queryClient.cancelQueries({ queryKey: correlationsListKey }),
      ]);
      const previousCorrelation = queryClient.getQueryData<JobCorrelationResponse>(detailKey);
      const previousLists = queryClient.getQueriesData<PaginatedResponseJobCorrelationResponse>({
        queryKey: correlationsListKey,
      });

      if (newStatus) {
        queryClient.setQueryData<JobCorrelationResponse>(detailKey, (old) =>
          old ? { ...old, status: newStatus } : old,
        );
        queryClient.setQueriesData<PaginatedResponseJobCorrelationResponse>(
          { queryKey: correlationsListKey },
          (old) =>
            old
              ? {
                  ...old,
                  items: old.items.map((item) =>
                    item.id === correlationId ? { ...item, status: newStatus } : item,
                  ),
                }
              : old,
        );
      }
      return { previousCorrelation, previousLists, correlationId };
    },
    onError: (_err, _init, context) => {
      if (!context) {
        return;
      }
      const detailKey = $api.queryOptions('get', '/api/v1/listings/correlations/{correlation_id}', {
        params: { path: { correlation_id: context.correlationId } },
      }).queryKey;
      queryClient.setQueryData(detailKey, context.previousCorrelation);
      for (const [queryKey, data] of context.previousLists) {
        queryClient.setQueryData(queryKey, data);
      }
    },
    onSettled: () => invalidateByPath(queryClient, '/api/v1/listings/correlations'),
  });
}

function useScoreFeedback() {
  const queryClient = useQueryClient();

  return $api.useMutation('post', '/api/v1/correlations/{correlation_id}/score-feedback', {
    onSuccess: () => invalidateByPath(queryClient, '/api/v1/listings/correlations'),
  });
}

function useAdjustScore() {
  const queryClient = useQueryClient();

  return $api.useMutation('post', '/api/v1/correlations/{correlation_id}/adjust-score', {
    onSettled: () => invalidateByPath(queryClient, '/api/v1/listings/correlations'),
  });
}

export { useAdjustScore, useRecordFeedback, useScoreFeedback };
