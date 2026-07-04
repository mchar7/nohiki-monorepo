/** Tab values matching the route search param schema. */
type DocumentTab = 'all' | 'uploaded' | 'generated';

/** Page size for each data source. */
const PAGE_SIZE: number = 10;

interface QueryResult<T> {
  data: { items: T[]; total: number } | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}

export type { DocumentTab, QueryResult };
export { PAGE_SIZE };
