import { Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import { Badge } from './badge.tsx';
import { FALLBACK_STATUS_THEME, type StatusTheme } from './status-badge-model.ts';

interface StatusBadgeProps {
  /** Status key used to look up the theme (e.g. "pending", "completed") */
  readonly status: string;
  /** Display label for the badge */
  readonly label: string;
  /** Theme map that determines colors/variant per status */
  readonly themes: Record<string, StatusTheme>;
}

/**
 * Shared status badge component supporting multiple domains (correlation, document, etc.)
 * via pluggable theme maps.
 *
 * @example
 * ```tsx
 * <StatusBadge
 *   status={correlation.status}
 *   label={t(`status.${correlation.status}`)}
 *   themes={correlationStatusThemes}
 * />
 * ```
 */
function StatusBadge({ status, label, themes }: StatusBadgeProps): JSX.Element {
  const theme = themes[status.toLowerCase()] ?? FALLBACK_STATUS_THEME;

  return (
    <Badge variant={theme.variant ?? 'outline'} className={theme.className}>
      {theme.spinning ? <Loader2 className="mr-1 size-3 animate-spin" aria-hidden="true" /> : null}
      {label}
    </Badge>
  );
}

export { StatusBadge };
