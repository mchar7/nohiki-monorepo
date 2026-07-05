const MS_PER_SECOND: number = 1000;
const SECONDS_PER_MINUTE: number = 60;
const MINUTES_PER_HOUR: number = 60;
const HOURS_PER_DAY: number = 24;
const DAYS_PER_WEEK: number = 7;
const DAYS_PER_MONTH: number = 30;

const MS_PER_MINUTE: number = MS_PER_SECOND * SECONDS_PER_MINUTE;
const MS_PER_HOUR: number = MS_PER_MINUTE * MINUTES_PER_HOUR;
const MS_PER_DAY: number = MS_PER_HOUR * HOURS_PER_DAY;

/**
 * Formats a date string as a human-readable relative time.
 *
 * Returns compact labels: "Just now", "5m ago", "3h ago", "Yesterday",
 * "4d ago", "2w ago", "3mo ago". Falls back to locale date string
 * for dates older than ~12 months.
 *
 * @param dateString - ISO 8601 date string
 * @returns Human-readable relative time label
 */
export function formatRelativeTime(dateString: string): string {
  const now = new Date();
  const date = new Date(dateString);
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / MS_PER_MINUTE);
  const diffHours = Math.floor(diffMs / MS_PER_HOUR);
  const diffDays = Math.floor(diffMs / MS_PER_DAY);

  if (diffMinutes < 1) {
    return 'Just now';
  }
  if (diffMinutes < MINUTES_PER_HOUR) {
    return `${diffMinutes}m ago`;
  }
  if (diffHours < HOURS_PER_DAY) {
    return `${diffHours}h ago`;
  }
  if (diffDays === 1) {
    return 'Yesterday';
  }
  if (diffDays < DAYS_PER_WEEK) {
    return `${diffDays}d ago`;
  }
  if (diffDays < DAYS_PER_MONTH) {
    return `${Math.floor(diffDays / DAYS_PER_WEEK)}w ago`;
  }
  return `${Math.floor(diffDays / DAYS_PER_MONTH)}mo ago`;
}

/**
 * Formats a date string as a short locale date (e.g. "Jan 5", "Dec 12").
 *
 * @param dateString - ISO 8601 date string
 * @returns Short formatted date
 */
export function formatShortDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });
}

/**
 * Formats a date string as a long locale date (e.g. "January 5, 2025").
 *
 * @param dateString - ISO 8601 date string
 * @returns Long formatted date
 */
export function formatLongDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}
