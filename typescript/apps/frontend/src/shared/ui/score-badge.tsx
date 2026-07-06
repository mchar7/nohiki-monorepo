import type { JSX } from 'react';
import { cn } from '@/shared/lib';
import { Badge } from './badge.tsx';
import type { ScoreBadgeProps } from './score-badge.types.ts';

const SCORE_HIGH_THRESHOLD = 80;
const SCORE_MEDIUM_THRESHOLD = 60;

/** Colour-tiered score badge: ≥80 green, ≥60 yellow, <60 outline. */
function ScoreBadge({ score, className }: ScoreBadgeProps): JSX.Element {
  const rounded = Math.round(score);

  let variant: 'default' | 'secondary' | 'outline';
  let colorClass: string;

  if (rounded >= SCORE_HIGH_THRESHOLD) {
    variant = 'default';
    colorClass = 'bg-green-500/10 text-green-700 dark:text-green-400 border-green-500/20';
  } else if (rounded >= SCORE_MEDIUM_THRESHOLD) {
    variant = 'secondary';
    colorClass = 'bg-yellow-500/10 text-yellow-700 dark:text-yellow-400 border-yellow-500/20';
  } else {
    variant = 'outline';
    colorClass = '';
  }

  return (
    <Badge variant={variant} className={cn(`font-mono tabular-nums ${colorClass}`, className)}>
      {`${rounded} / 100`}
    </Badge>
  );
}

export { ScoreBadge };
