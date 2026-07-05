/**
 * Query cache invalidation helpers.
 *
 * openapi-react-query uses `[method, path, init?]` as query keys.
 * These helpers provide path-prefix invalidation for cache management.
 */
import type { Query, QueryClient } from '@tanstack/react-query';

/**
 * Invalidate all queries whose path starts with the given prefix.
 * Handles the `[method, path, init?]` key structure from openapi-react-query.
 */
function invalidateByPath(queryClient: QueryClient, pathPrefix: string): Promise<void> {
  return queryClient.invalidateQueries({
    predicate: (query: Query) => {
      const key = query.queryKey;
      // openapi-react-query keys: [method, path] or [method, path, init]
      return Array.isArray(key) && key.length >= 2 && typeof key[1] === 'string'
        ? key[1].startsWith(pathPrefix)
        : false;
    },
  });
}

export { invalidateByPath };
