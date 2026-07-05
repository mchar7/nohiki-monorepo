/**
 * OpenAPI fetch client and query integration.
 *
 * Single source of truth for all HTTP communication with the backend.
 * Uses openapi-fetch for type-safe requests and openapi-react-query
 * for TanStack Query integration.
 *
 * Authentication uses HttpOnly cookies - no manual token management.
 * The backend (Traefik → services) sets/clears auth cookies automatically.
 */
import createFetchClient, { type Client } from 'openapi-fetch';
import createQueryClient, { type OpenapiQueryClient } from 'openapi-react-query';
import type { paths } from '@/api/schema.d.ts';
import { attachErrorStatusMiddleware } from './middleware.ts';

function buildClient(baseUrl: string): Client<paths> {
  const c = createFetchClient<paths>({ baseUrl, credentials: 'include' });
  attachErrorStatusMiddleware(c);
  return c;
}

export const fetchClient: Client<paths> = buildClient(
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '',
);

/**
 * Recreate the fetch client base URL at runtime.
 * Dev-only: used by the Omakase endpoint switcher.
 * Returns a new client instance configured with the given base URL.
 */
export function createDevClient(baseUrl: string): Client<paths> {
  return buildClient(baseUrl);
}

/**
 * Type-safe query integration. Use `$api.useQuery`, `$api.useMutation`,
 * `$api.queryOptions`, and `$api.useInfiniteQuery` throughout the app.
 */
export const $api: OpenapiQueryClient<paths> = createQueryClient<paths>(fetchClient);
