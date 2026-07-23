import { Link } from '@tanstack/react-router';
import { ArrowRight, X } from 'lucide-react';
import { type JSX, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import { Progress } from '@/shared/ui/progress.tsx';

/** Multiplier for converting step fraction to percentage */
const PERCENT_SCALE: number = 100;

interface OnboardingProgressStripProps {
  readonly completedSteps: number;
  readonly totalSteps: number;
  readonly nextStepLabel: string;
  readonly nextStepRoute: string;
}

export function OnboardingProgressStrip({
  completedSteps,
  totalSteps,
  nextStepLabel,
  nextStepRoute,
}: OnboardingProgressStripProps): JSX.Element | null {
  const { t } = useTranslation('dashboard');
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) {
    return null;
  }

  const progressPercent = Math.round((completedSteps / totalSteps) * PERCENT_SCALE);

  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-4">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="shrink-0 font-medium text-sm">
            {t('stage.gettingStarted.progress', { completed: completedSteps, total: totalSteps })}
          </span>
          <Progress value={progressPercent} className="h-2 max-w-48" />
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Button variant="ghost" size="sm" asChild={true}>
            <Link to={nextStepRoute} className="gap-1 text-primary">
              {t('stage.gettingStarted.next', { step: nextStepLabel })}
              <ArrowRight className="size-4" />
            </Link>
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground hover:text-foreground"
            onClick={() => setDismissed(true)}
            aria-label={t('stage.gettingStarted.dismiss')}
          >
            <X className="size-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
