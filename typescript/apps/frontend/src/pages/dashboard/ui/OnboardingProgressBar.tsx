import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { Progress } from '@/shared/ui/progress.tsx';
import type { OnboardingProgressBarProps } from './Dashboard.types.ts';

/** Full percentage value used to compute progress indicator width */
const FULL_PERCENT: number = 100;

function OnboardingProgressBar({
  completedSteps,
  totalSteps,
}: OnboardingProgressBarProps): JSX.Element {
  const { t } = useTranslation('dashboard');
  const progressValue: number = (completedSteps / totalSteps) * FULL_PERCENT;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="font-medium text-sm">
          {t('onboarding.progress.label', { completed: completedSteps, total: totalSteps })}
        </p>
        <span className="font-medium text-muted-foreground text-xs">
          {t('onboarding.progress.percent', { value: Math.round(progressValue) })}
        </span>
      </div>
      <Progress value={progressValue} className="h-2.5" />
    </div>
  );
}

export { OnboardingProgressBar };
