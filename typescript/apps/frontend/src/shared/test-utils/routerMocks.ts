/**
 * Test helpers for constructing fake TanStack Router primitives without
 * scattering structural casts across individual test files.
 *
 * TanStack Router's `RouteMatch` type aggregates ~20 fields (id, search, params,
 * loaderData, status, abortController, fetchedAt, etc.) that components in
 * practice never read in unit tests. Constructing a partial inline always
 * requires `as unknown as ReturnType<typeof useMatches>` at the call site
 * because TS cannot recover the full match shape from the small subset tests
 * provide. These factories centralize the cast.
 */
import type { useMatches } from '@tanstack/react-router';

type UseMatchesReturn = ReturnType<typeof useMatches>;

/**
 * Minimal RouteMatch shape consumed by breadcrumb / navigation widgets.
 * Components that read additional fields should not use this helper.
 */
export interface BreadcrumbRouteMatch {
  readonly pathname: string;
  readonly staticData?: {
    readonly breadcrumb?: string;
  };
}

/**
 * Build a `useMatches()` return value from a sparse array of route-match-like
 * objects. The cast lives here so test files stay free of `as unknown as`.
 * Use only with components whose match access is limited to the fields on
 * `BreadcrumbRouteMatch`.
 */
export function makeBreadcrumbMatches(matches: readonly BreadcrumbRouteMatch[]): UseMatchesReturn {
  return matches as unknown as UseMatchesReturn;
}
