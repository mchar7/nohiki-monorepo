import { useQuery } from '@tanstack/react-query';
import { $api, CACHE_CONFIG } from '@/shared/api/index.ts';

const DEFAULT_CORRELATIONS_PAGE: number = 1;
const DEFAULT_CORRELATIONS_PAGE_SIZE: number = 20;

interface CorrelationFilters {
  page?: number | undefined;
  pageSize?: number | undefined;
  prefId?: string | undefined;
  minScore?: number | undefined;
}

function correlationsQueryOptions(filters: CorrelationFilters = {}) {
  const {
    page = DEFAULT_CORRELATIONS_PAGE,
    pageSize = DEFAULT_CORRELATIONS_PAGE_SIZE,
    prefId,
    minScore,
  } = filters;

  return $api.queryOptions(
    'get',
    '/api/v1/listings/correlations/mine',
    {
      params: {
        query: {
          page,
          page_size: pageSize,
          pref_id: prefId ?? null,
          min_score: minScore,
        },
      },
    },
    { ...CACHE_CONFIG.DYNAMIC },
  );
}

function useMyCorrelations(filters: CorrelationFilters = {}) {
  return useQuery(correlationsQueryOptions(filters));
}

function correlationDetailQueryOptions(correlationId: string) {
  return $api.queryOptions(
    'get',
    '/api/v1/listings/correlations/{correlation_id}',
    { params: { path: { correlation_id: correlationId } } },
    {
      enabled: Boolean(correlationId),
      ...CACHE_CONFIG.DYNAMIC,
    },
  );
}

function useCorrelation(correlationId: string) {
  return useQuery(correlationDetailQueryOptions(correlationId));
}

export {
  useAdjustScore,
  useRecordFeedback,
  useScoreFeedback,
} from './useCorrelationMutations.ts';

export {
  correlationDetailQueryOptions,
  correlationsQueryOptions,
  useCorrelation,
  useMyCorrelations,
};
