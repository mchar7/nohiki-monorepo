/**
 * Formats a number using the current locale's conventions.
 * Uses Intl.NumberFormat for locale-aware number display.
 *
 * @param value - Number to format
 * @param locale - BCP 47 locale tag (defaults to 'en')
 * @returns Locale-formatted number string
 */
function formatNumber(value: number, locale?: string): string {
  return new Intl.NumberFormat(locale ?? 'en').format(value);
}

export { formatNumber };
