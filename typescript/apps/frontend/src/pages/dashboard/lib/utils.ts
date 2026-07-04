import type { JobCorrelationResponse } from '@/shared/api';

const DAYS_PER_WEEK: number = 7;
/** getDay() returns 0 for Sunday; remap to 7 for Monday-based week math. */
const SUNDAY_ISO_DAY: number = 7;
/** Score threshold for "excellent" match classification */
const SCORE_EXCELLENT_THRESHOLD: number = 85;
/** Score threshold for "good" match classification */
const SCORE_GOOD_THRESHOLD: number = 70;
/** Score threshold for "fair" match classification */
const SCORE_FAIR_THRESHOLD: number = 50;
/** Minimum data points required for a meaningful trend line. */
const MIN_TREND_POINTS: number = 5;
/** Decimal precision multiplier for rounding trend values to 2 places. */
const DECIMAL_PRECISION: number = 100;
/** Percentage change below this threshold is considered "steady". */
const STEADY_THRESHOLD: number = 5;
/** Multiplier for converting a ratio to a percentage. */
const PERCENT: number = 100;

/**
 * Returns the Monday 00:00:00 of the week containing the given date.
 * Uses Monday-based weeks (ISO standard).
 */
function getMonday(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay();
  // getDay(): 0=Sun, 1=Mon, ... 6=Sat → shift Sunday (0) to 7 for Monday-based math
  const diff = (day === 0 ? SUNDAY_ISO_DAY : day) - 1;
  d.setDate(d.getDate() - diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

/**
 * Computes a single stat trend (current week vs previous week).
 * Returns 'unavailable' when all items fall within the current week,
 * since we can't compute a meaningful week-over-week comparison.
 */
function computeSingleStatTrend(items: readonly { created_at: string }[]): StatTrend {
  const now = new Date();
  const currentWeekStart = getMonday(now);
  const previousWeekStart = new Date(currentWeekStart);
  previousWeekStart.setDate(previousWeekStart.getDate() - DAYS_PER_WEEK);

  let currentCount = 0;
  let previousCount = 0;
  let hasItemsBeforeCurrentWeek = false;

  for (const item of items) {
    const itemDate = new Date(item.created_at);
    if (itemDate >= currentWeekStart) {
      currentCount += 1;
    } else if (itemDate >= previousWeekStart) {
      previousCount += 1;
      hasItemsBeforeCurrentWeek = true;
    } else {
      hasItemsBeforeCurrentWeek = true;
    }
  }

  // Can't compute trend if all data is from current week only
  if (!hasItemsBeforeCurrentWeek && items.length > 0) {
    return { direction: 'unavailable', delta: 0 };
  }

  const delta = currentCount - previousCount;
  if (delta > 0) {
    return { direction: 'up', delta };
  }
  if (delta < 0) {
    return { direction: 'down', delta };
  }
  return { direction: 'steady', delta: 0 };
}

// --- Exported types ---

export interface ActivityDataPoint {
  readonly date: string;
  readonly matches: number;
  readonly trend?: number;
  readonly [key: string]: string | number | undefined;
}

export interface TrendSummary {
  readonly direction: 'up' | 'down' | 'steady';
  readonly percentChange: number;
  readonly label: string;
}

export interface StatTrend {
  readonly direction: 'up' | 'down' | 'steady' | 'unavailable';
  readonly delta: number;
}

interface StatTrends {
  readonly jobMatches?: StatTrend;
  readonly documents?: StatTrend;
}

// --- Exported functions ---

/**
 * Aggregates correlations by date for chart visualization.
 * Creates a date-indexed map for O(n) aggregation instead of nested loops.
 */
export function aggregateCorrelationsByDate(
  correlations: readonly JobCorrelationResponse[],
  days: number,
): ActivityDataPoint[] {
  const now = new Date();
  const dateMap = new Map<string, number>();

  for (let i = 0; i < days; i += 1) {
    const date = new Date(now);
    date.setDate(date.getDate() - (days - 1 - i));
    const dateKey = date.toISOString().split('T')[0] ?? '';
    dateMap.set(dateKey, 0);
  }

  for (const correlation of correlations) {
    const dateKey = new Date(correlation.created_at).toISOString().split('T')[0] ?? '';
    if (dateMap.has(dateKey)) {
      dateMap.set(dateKey, (dateMap.get(dateKey) ?? 0) + 1);
    }
  }

  return Array.from(dateMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, matches]) => ({ date, matches }));
}

/**
 * Appends a simple moving average trend to activity data points.
 * Uses a sliding window of `windowSize` days. Returns the original
 * data unmodified when there are too few points for a trend.
 */
export function withMovingAverage(
  data: readonly ActivityDataPoint[],
  windowSize: number = 7,
): ActivityDataPoint[] {
  if (data.length < MIN_TREND_POINTS) {
    return data.map((point) => ({ ...point }));
  }

  const effectiveWindow = Math.min(windowSize, data.length);
  let windowSum = 0;

  return data.map((point, i) => {
    windowSum += point.matches;
    if (i >= effectiveWindow) {
      const outgoing = data[i - effectiveWindow];
      // outgoing is always defined: i >= effectiveWindow guarantees a valid index
      if (outgoing !== undefined) {
        windowSum -= outgoing.matches;
      }
    }
    const divisor = Math.min(i + 1, effectiveWindow);
    return {
      ...point,
      trend: Math.round((windowSum / divisor) * DECIMAL_PRECISION) / DECIMAL_PRECISION,
    };
  });
}

/**
 * Checks if a date string is within the last 7 days.
 */
export function isWithinWeek(dateString: string): boolean {
  const date = new Date(dateString);
  const weekAgo = new Date();
  weekAgo.setDate(weekAgo.getDate() - DAYS_PER_WEEK);
  return date >= weekAgo;
}

/**
 * Returns a CSS class name based on match score thresholds.
 */
export function getScoreClassName(score: number): string {
  if (score >= SCORE_EXCELLENT_THRESHOLD) {
    return 'match-score-excellent';
  }
  if (score >= SCORE_GOOD_THRESHOLD) {
    return 'match-score-good';
  }
  if (score >= SCORE_FAIR_THRESHOLD) {
    return 'match-score-fair';
  }
  return 'match-score-low';
}

/**
 * Returns a CSS class name for progress bar based on match score thresholds.
 */
export function getProgressClassName(score: number): string {
  if (score >= SCORE_EXCELLENT_THRESHOLD) {
    return 'match-progress-excellent';
  }
  if (score >= SCORE_GOOD_THRESHOLD) {
    return 'match-progress-good';
  }
  if (score >= SCORE_FAIR_THRESHOLD) {
    return 'match-progress-fair';
  }
  return 'match-progress-low';
}

/**
 * Computes a trend summary by comparing the first and second halves of time-series data.
 * Used by the activity chart to show period-over-period direction.
 */
export function computeTrendSummary(
  data: readonly { date: string; count: number }[],
): TrendSummary {
  const steady: TrendSummary = { direction: 'steady', percentChange: 0, label: '→ Steady' };

  if (data.length <= 1) {
    return steady;
  }

  const midpoint = Math.floor(data.length / 2);
  let previousSum = 0;
  let currentSum = 0;

  for (let i = 0; i < midpoint; i += 1) {
    previousSum += (data[i] as { count: number }).count;
  }
  for (let i = midpoint; i < data.length; i += 1) {
    currentSum += (data[i] as { count: number }).count;
  }

  if (previousSum === 0 && currentSum === 0) {
    return steady;
  }

  const percentChange =
    previousSum === 0 ? PERCENT : Math.round(((currentSum - previousSum) / previousSum) * PERCENT);

  const absChange = Math.abs(percentChange);

  if (absChange < STEADY_THRESHOLD) {
    return steady;
  }

  if (percentChange > 0) {
    return { direction: 'up', percentChange: absChange, label: `↑ ${absChange}% more matches` };
  }
  return { direction: 'down', percentChange: absChange, label: `↓ ${absChange}% fewer matches` };
}

/**
 * Computes week-over-week trends for stat cards.
 * Compares current week (Mon–Sun) item counts against the previous week.
 */
export function computeStatTrends(
  correlations: readonly { created_at: string }[],
  documents: readonly { created_at: string }[],
): StatTrends {
  return {
    jobMatches: computeSingleStatTrend(correlations),
    documents: computeSingleStatTrend(documents),
  };
}

/**
 * Returns the correlation with the highest `fit_score`, or null if empty.
 * On tied scores, returns the first occurrence.
 */
export function getTopMatch<T extends { fit_score: number }>(correlations: readonly T[]): T | null {
  if (correlations.length === 0) {
    return null;
  }

  let best = correlations[0] as T;
  for (let i = 1; i < correlations.length; i += 1) {
    const current = correlations[i] as T;
    if (current.fit_score > best.fit_score) {
      best = current;
    }
  }
  return best;
}

export { formatRelativeTime } from '@/shared/lib';
