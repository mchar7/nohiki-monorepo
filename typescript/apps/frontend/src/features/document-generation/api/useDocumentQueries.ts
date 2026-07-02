import { $api, CACHE_CONFIG } from '@/shared/api/index.ts';

const DEFAULT_DOCUMENTS_PAGE: number = 1;
const DEFAULT_DOCUMENTS_PAGE_SIZE: number = 20;

const documentsListQueryOptions = $api.queryOptions(
  'get',
  '/api/v1/documents',
  { params: { query: { page: DEFAULT_DOCUMENTS_PAGE, page_size: DEFAULT_DOCUMENTS_PAGE_SIZE } } },
  { staleTime: CACHE_CONFIG.USER_DATA.staleTime, gcTime: CACHE_CONFIG.USER_DATA.gcTime },
);

function useDocuments(
  page: number = DEFAULT_DOCUMENTS_PAGE,
  pageSize: number = DEFAULT_DOCUMENTS_PAGE_SIZE,
) {
  return $api.useQuery(
    'get',
    '/api/v1/documents',
    { params: { query: { page, page_size: pageSize } } },
    {
      staleTime: CACHE_CONFIG.USER_DATA.staleTime,
      gcTime: CACHE_CONFIG.USER_DATA.gcTime,
    },
  );
}

export { documentsListQueryOptions, useDocuments };
