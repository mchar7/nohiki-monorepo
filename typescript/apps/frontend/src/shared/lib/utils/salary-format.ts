/**
 * Currency symbols and locale mappings for salary formatting.
 * Using explicit symbols avoids relying on browser locale for consistent output.
 */
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$',
  CAD: 'CA$',
  EUR: '€',
  GBP: '£',
};

/** Divisor used when compacting values into "k" notation. */
const THOUSANDS = 1000;

/**
 * Frequency suffix mappings for display.
 */
const FREQUENCY_SUFFIXES: Record<string, string> = {
  ANNUALLY: '/yr',
  MONTHLY: '/mo',
  HOURLY: '/hr',
};

interface SalaryFormatOptions {
  min?: number | null;
  max?: number | null;
  currency?: string | null;
  frequency?: string | null;
  compact?: boolean;
}

/**
 * Formats a number into compact notation (e.g. 120000 → "120k").
 * Values under 1000 are returned as-is.
 */
function toCompact(value: number): string {
  if (value >= THOUSANDS) {
    const k = value / THOUSANDS;
    // Avoid trailing .0 for whole thousands
    return `${Number.isInteger(k) ? k : k.toFixed(1)}k`;
  }
  return String(value);
}

/**
 * Formats a number with thousands separators (e.g. 120000 → "120,000").
 */
function toFull(value: number): string {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
}

/**
 * Formats a salary range for display.
 *
 * Returns `null` when both `min` and `max` are absent, allowing callers to
 * conditionally render nothing when salary data is unavailable.
 *
 * @example
 * // Compact (for cards)
 * formatSalaryRange({ min: 120_000, max: 160_000, currency: 'USD', compact: true })
 * // → "$120k – $160k"
 *
 * @example
 * // Full (for detail page)
 * formatSalaryRange({ min: 120_000, max: 160_000, currency: 'USD', frequency: 'ANNUALLY' })
 * // → "$120,000 – $160,000/yr"
 */
export function formatSalaryRange(options: SalaryFormatOptions): string | null {
  const { min, max, currency = 'USD', frequency, compact = false } = options;

  const hasMin = typeof min === 'number';
  const hasMax = typeof max === 'number';

  if (!(hasMin || hasMax)) {
    return null;
  }

  const symbol = CURRENCY_SYMBOLS[currency ?? 'USD'] ?? '$';
  const suffix =
    frequency !== null && frequency !== undefined ? (FREQUENCY_SUFFIXES[frequency] ?? '') : '';
  const fmt = compact ? toCompact : toFull;

  if (hasMin && hasMax) {
    return `${symbol}${fmt(min as number)} – ${symbol}${fmt(max as number)}${suffix}`;
  }

  if (hasMin) {
    return `${symbol}${fmt(min as number)}+${suffix}`;
  }

  // hasMax only
  return `Up to ${symbol}${fmt(max as number)}${suffix}`;
}
