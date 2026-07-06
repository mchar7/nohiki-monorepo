import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/utils/utils.ts';

const WARNING_THRESHOLD = 0.9;

interface CharacterCounterProps {
  /** Current character count */
  readonly current: number;
  /** Maximum allowed characters */
  readonly max: number;
  /** Additional CSS classes */
  readonly className?: string;
}

/**
 * Displays a `current/max` character count with color-coded warnings.
 *
 * - Default: muted text
 * - >= 90% of max: amber warning
 * - At max: destructive red
 */
export function CharacterCounter({ current, max, className }: CharacterCounterProps): JSX.Element {
  const { t } = useTranslation('common');
  const atMax = current >= max;
  const nearMax = current >= max * WARNING_THRESHOLD;

  return (
    <span
      className={cn(
        'text-muted-foreground text-xs transition-colors',
        nearMax && !atMax && 'text-amber-600 dark:text-amber-500',
        atMax && 'text-destructive',
        className,
      )}
      aria-live="polite"
    >
      {t('characterCounter.count', { current, max })}
    </span>
  );
}
