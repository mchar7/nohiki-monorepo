/**
 * Secure fetch wrapper with built-in security features.
 *
 * Features:
 * - Request timeout with AbortController
 * - CSRF token injection for state-changing requests
 * - Credentials handling
 * - Error normalization
 */

import { HTTP_STATUS } from '@/shared/config/constants.ts';
import { config } from '@/shared/config/index.ts';

/** Options for secure fetch requests */
interface SecureFetchOptions extends Omit<RequestInit, 'signal'> {
  /** Request timeout in milliseconds (default: from config) */
  readonly timeout?: number;
  /** Whether to include CSRF token (default: true for POST/PUT/DELETE/PATCH) */
  readonly includeCSRF?: boolean;
  /** Base URL override */
  readonly baseUrl?: string;
}

/** Structured error from secure fetch */
interface SecureFetchError {
  readonly type: 'network' | 'timeout' | 'http' | 'parse';
  readonly status?: number | undefined;
  readonly statusText?: string | undefined;
  readonly message: string;
  readonly url: string;
}

/** HTTP methods that require CSRF protection */
const CSRF_METHODS: Set<string> = new Set(['POST', 'PUT', 'DELETE', 'PATCH']);

/** CSRF token storage key */
const CSRF_TOKEN_KEY = 'nohiki-csrf-token';

/**
 * Type guard to check if an error is a SecureFetchError
 */
function isSecureFetchError(error: unknown): error is SecureFetchError {
  if (typeof error !== 'object' || error === null) {
    return false;
  }
  const candidate = error as Record<string, unknown>;
  return (
    typeof candidate.type === 'string' &&
    typeof candidate.message === 'string' &&
    typeof candidate.url === 'string'
  );
}

/**
 * Gets the stored CSRF token
 */
function getCSRFToken(): string | null {
  try {
    return globalThis.sessionStorage?.getItem(CSRF_TOKEN_KEY) ?? null;
  } catch {
    return null;
  }
}

/**
 * Creates an AbortController with timeout
 */
function createTimeoutController(timeoutMs: number): {
  controller: AbortController;
  timeoutId: ReturnType<typeof setTimeout>;
} {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  return { controller, timeoutId };
}

const TRAILING_SLASH_RE = /\/$/u;

/**
 * Builds the full URL from base and path
 */
function buildUrl(path: string, baseUrl?: string): string {
  const base = baseUrl ?? config.api.baseUrl;
  const cleanBase = base.replace(TRAILING_SLASH_RE, '');
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${cleanBase}${cleanPath}`;
}

/**
 * Determines if CSRF token should be included
 */
function shouldIncludeCSRF(method: string, includeCSRF?: boolean): boolean {
  if (includeCSRF !== undefined) {
    return includeCSRF;
  }
  return CSRF_METHODS.has(method.toUpperCase());
}

/**
 * Prepares headers with security enhancements
 */
function prepareHeaders(
  existingHeaders: HeadersInit | undefined,
  method: string,
  includeCSRF?: boolean,
): Headers {
  const headers = new Headers(existingHeaders);

  // Set default content type for JSON if not already set
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  // Add CSRF token for state-changing requests
  if (shouldIncludeCSRF(method, includeCSRF)) {
    const csrfToken = getCSRFToken();
    if (csrfToken) {
      headers.set('X-CSRF-Token', csrfToken);
    }
  }

  return headers;
}

/** Parameters for creating a SecureFetchError */
interface CreateErrorParams {
  type: SecureFetchError['type'];
  message: string;
  url: string;
  status?: number;
  statusText?: string;
}

/**
 * Creates a SecureFetchError from various error types
 */
function createError({
  type,
  message,
  url,
  status,
  statusText,
}: CreateErrorParams): SecureFetchError {
  return { type, message, url, status, statusText };
}

/**
 * Performs a secure fetch request with timeout, CSRF protection, and error handling.
 *
 * @param url - The URL path (will be prefixed with base URL)
 * @param options - Fetch options with security enhancements
 * @returns Promise resolving to the parsed JSON response
 * @throws SecureFetchError on any failure
 *
 * @example
 * ```ts
 * const data = await secureFetch<UserProfile>('/api/profile', {
 *   method: 'GET',
 *   timeout: 5000,
 * });
 * ```
 */
/**
 * Parses the response body, handling empty and JSON responses.
 */
async function parseResponseBody<T>(response: Response, fullUrl: string): Promise<T> {
  const contentLength = response.headers.get('content-length');
  if (contentLength === '0' || response.status === HTTP_STATUS.NO_CONTENT) {
    return undefined as T;
  }

  try {
    return (await response.json()) as T;
  } catch (error) {
    throw createError({
      type: 'parse',
      message: `Failed to parse response as JSON: ${error instanceof Error ? error.message : String(error)}`,
      url: fullUrl,
    });
  }
}

/**
 * Maps caught errors to SecureFetchError types.
 */
function handleFetchError(error: unknown, fullUrl: string, timeout: number): never {
  if (isSecureFetchError(error)) {
    throw error;
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    throw createError({
      type: 'timeout',
      message: `Request timed out after ${timeout}ms`,
      url: fullUrl,
    });
  }
  const message = error instanceof Error ? error.message : 'Network request failed';
  throw createError({ type: 'network', message, url: fullUrl });
}

async function secureFetch<T>(url: string, options: SecureFetchOptions = {}): Promise<T> {
  const { timeout = config.api.timeout, includeCSRF, baseUrl, headers, ...fetchOptions } = options;
  const fullUrl = buildUrl(url, baseUrl);
  const method = (options.method ?? 'GET').toUpperCase();
  const { controller, timeoutId } = createTimeoutController(timeout);

  try {
    const response = await fetch(fullUrl, {
      ...fetchOptions,
      method,
      headers: prepareHeaders(headers, method, includeCSRF),
      signal: controller.signal,
      credentials: 'include',
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw createError({
        type: 'http',
        message: `HTTP ${response.status}: ${response.statusText}`,
        url: fullUrl,
        status: response.status,
        statusText: response.statusText,
      });
    }

    return await parseResponseBody<T>(response, fullUrl);
  } catch (error) {
    clearTimeout(timeoutId);
    handleFetchError(error, fullUrl, timeout);
  }
}

export { isSecureFetchError, secureFetch };
