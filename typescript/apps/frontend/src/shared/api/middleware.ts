/**
 * openapi-fetch middleware.
 *
 * openapi-fetch returns { data, error, response } tuples for non-2xx responses -
 * it does NOT throw by default. `onError` is only invoked for network-level
 * failures (when `fetch()` itself throws, e.g. DNS failure or CORS rejection).
 *
 * The onResponse middleware below converts every non-2xx response into a thrown
 * ApiError so that TanStack Query's `retry` function receives an error with a
 * numeric `status` field, enabling 401-triggered token refresh and smart backoff.
 * Query/mutation functions can still destructure { data, error, response } if
 * they bypass the middleware (but they should prefer throwing for consistency).
 */
import type { Client, Middleware, MiddlewareCallbackParams } from 'openapi-fetch';
import type { paths } from '@/api/schema.d.ts';

/**
 * Typed API error that carries the HTTP status code.
 * Thrown by the response middleware for all non-2xx HTTP responses.
 */
class ApiError extends Error {
  readonly status: number;
  readonly retryAfter: number | null;

  constructor(message: string, status: number, retryAfter: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

/** Middleware that converts non-2xx responses into thrown ApiErrors. */
/** HTTP 429 Too Many Requests status code. */
const HTTP_TOO_MANY_REQUESTS = 429;

const errorStatusMiddleware: Middleware = {
  async onResponse(
    options: MiddlewareCallbackParams & { response: Response },
  ): Promise<Response | undefined> {
    const { response } = options;
    if (!response.ok) {
      // Clone before reading to avoid consuming the body
      const body = await response.clone().text();
      let message = `HTTP ${response.status}`;
      try {
        const parsed: unknown = JSON.parse(body);
        if (typeof parsed === 'object' && parsed !== null && 'detail' in parsed) {
          message = String((parsed as { detail: unknown }).detail);
        }
      } catch {
        // Body is not JSON - use status message
      }
      const retryAfter =
        response.status === HTTP_TOO_MANY_REQUESTS
          ? Number.parseInt(response.headers.get('Retry-After') ?? '', 10) || null
          : null;
      throw new ApiError(message, response.status, retryAfter);
    }
    return response;
  },
};

/**
 * Attach the error status middleware to an openapi-fetch client instance.
 * Call once during client initialization.
 */
function attachErrorStatusMiddleware(client: Client<paths>): void {
  client.use(errorStatusMiddleware);
}

export { ApiError, attachErrorStatusMiddleware };
