/**
 * Test helpers for constructing fake TanStack Query results without scattering
 * structural casts across individual test files.
 *
 * Why a centralized cast: `UseQueryResult<T>` is a 3-state discriminated union
 * (pending / success / error) with 30+ fields whose discriminants must agree
 * (e.g. `status: 'success'` requires `error === null`, `isPending === false`,
 * etc.). Hand-building one inline from a partial object always requires
 * `as unknown as UseQueryResult<T>` at the call site because TypeScript cannot
 * verify the union arm structurally: the discriminant booleans are
 * runtime-computed and TS treats them as `boolean` not `true`/`false` literals.
 * This module performs the cast exactly once per state factory, with the union
 * semantics enforced by the factory shape (success / loading / error / empty).
 */
import type { UseQueryResult } from '@tanstack/react-query';

type QueryStatus = 'pending' | 'success' | 'error';

interface BuildOptions<TData, TError = Error> {
  readonly data: TData | undefined;
  readonly error: TError | null;
  readonly status: QueryStatus;
  readonly refetch?: UseQueryResult<TData, TError>['refetch'];
}

/**
 * Assembles a full UseQueryResult-shaped object from a status discriminator.
 * The body builds the 24-field object literal natively, then performs the one
 * cast required to satisfy the discriminated union (TS treats `isError`,
 * `isSuccess`, `isPending` as `boolean`, not the literal types each arm of the
 * union demands). All four public helpers go through this function so the
 * shape and the cast are defined in one place.
 */
function buildQueryResult<TData, TError>(
  options: BuildOptions<TData, TError>,
): UseQueryResult<TData, TError> {
  const { data, error, status } = options;
  const refetch: UseQueryResult<TData, TError>['refetch'] =
    options.refetch ??
    ((): ReturnType<UseQueryResult<TData, TError>['refetch']> =>
      Promise.resolve(buildQueryResult<TData, TError>({ ...options, refetch })));
  const isSuccess = status === 'success';
  const isError = status === 'error';
  const isPending = status === 'pending';

  return {
    data,
    error,
    status,
    fetchStatus: 'idle' as const,
    isError,
    isPending,
    isLoading: isPending,
    isLoadingError: false,
    isRefetchError: isError,
    isSuccess,
    isInitialLoading: false,
    isFetched: !isPending,
    isFetchedAfterMount: !isPending,
    isFetching: false,
    isPaused: false,
    isPlaceholderData: false,
    isRefetching: false,
    isStale: false,
    dataUpdatedAt: isSuccess ? Date.now() : 0,
    errorUpdatedAt: isError ? Date.now() : 0,
    failureCount: isError ? 1 : 0,
    failureReason: error,
    errorUpdateCount: isError ? 1 : 0,
    refetch,
    promise: Promise.resolve(data),
  } as unknown as UseQueryResult<TData, TError>;
}

/**
 * Merges a UseQueryResult base with caller overrides. Spreading a discriminated
 * union widens its discriminant fields (e.g. `error` to `TError | null`), so
 * the result no longer narrows back to a single arm. We cast at this single
 * boundary so the four public helpers don't repeat the cast.
 */
function mergedAs<TData, TError>(
  base: UseQueryResult<TData, TError>,
  overrides: Partial<UseQueryResult<TData, TError>>,
): UseQueryResult<TData, TError> {
  return { ...base, ...overrides } as unknown as UseQueryResult<TData, TError>;
}

/**
 * Build a successful UseQueryResult for the given data.
 */
export function makeQuerySuccess<TData, TError = Error>(
  data: TData,
  overrides: Partial<UseQueryResult<TData, TError>> = {},
): UseQueryResult<TData, TError> {
  return mergedAs<TData, TError>(
    buildQueryResult<TData, TError>({ data, error: null, status: 'success' }),
    overrides,
  );
}

/**
 * Build a loading / pending UseQueryResult (no data, no error).
 */
export function makeQueryLoading<TData, TError = Error>(
  overrides: Partial<UseQueryResult<TData, TError>> = {},
): UseQueryResult<TData, TError> {
  return mergedAs<TData, TError>(
    buildQueryResult<TData, TError>({ data: undefined, error: null, status: 'pending' }),
    overrides,
  );
}

/**
 * Build an errored UseQueryResult.
 */
export function makeQueryError<TData, TError = Error>(
  error: TError,
  overrides: Partial<UseQueryResult<TData, TError>> = {},
): UseQueryResult<TData, TError> {
  return mergedAs<TData, TError>(
    buildQueryResult<TData, TError>({ data: undefined, error, status: 'error' }),
    overrides,
  );
}

/**
 * Build a UseQueryResult where the query has settled with `undefined` data
 * (e.g. an unauthenticated session check that returns no user). Equivalent to
 * makeQuerySuccess(undefined as TData).
 */
export function makeQueryEmpty<TData, TError = Error>(
  overrides: Partial<UseQueryResult<TData | undefined, TError>> = {},
): UseQueryResult<TData | undefined, TError> {
  return mergedAs<TData | undefined, TError>(
    buildQueryResult<TData | undefined, TError>({
      data: undefined,
      error: null,
      status: 'success',
    }),
    overrides,
  );
}
