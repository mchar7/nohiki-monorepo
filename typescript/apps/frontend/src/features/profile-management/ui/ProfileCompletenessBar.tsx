import { CircleAlert } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { ProfileResponse } from '@/shared/api';
import { Progress } from '@/shared/ui/progress.tsx';
import { useProfileCompleteness } from '../lib/useProfileCompleteness.ts';

/** Score threshold above which the bar renders with an accent (success-like) color */
const HIGH_SCORE_THRESHOLD: number = 70;
/** Score threshold below which the bar renders with a warning color */
const LOW_SCORE_THRESHOLD: number = 40;

function scoreColor(score: number): string {
  if (score >= HIGH_SCORE_THRESHOLD) {
    return 'text-emerald-600 dark:text-emerald-400';
  }
  if (score >= LOW_SCORE_THRESHOLD) {
    return 'text-amber-600 dark:text-amber-400';
  }
  return 'text-red-600 dark:text-red-400';
}

function barClassName(score: number): string {
  if (score >= HIGH_SCORE_THRESHOLD) {
    return '[&>div]:bg-emerald-600 bg-emerald-600/20 dark:[&>div]:bg-emerald-400 dark:bg-emerald-400/20';
  }
  if (score >= LOW_SCORE_THRESHOLD) {
    return '[&>div]:bg-amber-600 bg-amber-600/20 dark:[&>div]:bg-amber-400 dark:bg-amber-400/20';
  }
  return '[&>div]:bg-red-600 bg-red-600/20 dark:[&>div]:bg-red-400 dark:bg-red-400/20';
}

interface ProfileCompletenessBarProps {
  readonly profile: ProfileResponse;
}

function ProfileCompletenessBar({ profile }: ProfileCompletenessBarProps): JSX.Element {
  const { t } = useTranslation('profiles');
  const { score, maxScore, suggestions } = useProfileCompleteness(profile);

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <span className="font-medium text-sm">{t('completeness.title')}</span>
        <span className={`font-bold text-sm tabular-nums ${scoreColor(score)}`}>
          {t('completeness.scoreLabel', { score, max: maxScore })}
        </span>
      </div>
      <Progress value={score} max={maxScore} className={barClassName(score)} />
      {suggestions.length > 0 && (
        <ul className="space-y-1">
          {suggestions.map((key) => (
            <li key={key} className="flex items-start gap-1.5 text-muted-foreground text-xs">
              <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
              <span>{t(key)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export { ProfileCompletenessBar };
