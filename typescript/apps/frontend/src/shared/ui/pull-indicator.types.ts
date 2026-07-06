interface PullIndicatorProps {
  /** Current pull distance in pixels (from usePullToRefresh). */
  readonly pullDistance: number;
  /** Whether a refresh is currently in progress. */
  readonly isRefreshing: boolean;
}

export type { PullIndicatorProps };
