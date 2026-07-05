const BYTES_PER_KB: number = 1024;
const BYTES_PER_MB: number = BYTES_PER_KB * BYTES_PER_KB;
/** Divisor for rounding MB to one decimal place */
const MB_DECIMAL_PRECISION: number = 10;

/**
 * Format a raw byte count into a human-readable size tuple.
 *
 * Returns an object so callers can independently format the numeric value and
 * localise the unit label via i18n without string concatenation in this layer.
 *
 * @param bytes - File size in bytes (non-negative integer).
 * @returns Object with `size` (formatted number) and `unit` ('bytes' | 'kb' | 'mb').
 *
 * Examples:
 *   formatFileSize(500)          // { size: 500, unit: 'bytes' }
 *   formatFileSize(2048)         // { size: 2, unit: 'kb' }
 *   formatFileSize(1572864)      // { size: 1.5, unit: 'mb' }
 */
export function formatFileSize(bytes: number): { size: number; unit: 'bytes' | 'kb' | 'mb' } {
  if (bytes < BYTES_PER_KB) {
    return { size: bytes, unit: 'bytes' };
  }
  if (bytes < BYTES_PER_MB) {
    return { size: Math.round(bytes / BYTES_PER_KB), unit: 'kb' };
  }
  return {
    size: Math.round((bytes / BYTES_PER_MB) * MB_DECIMAL_PRECISION) / MB_DECIMAL_PRECISION,
    unit: 'mb',
  };
}
