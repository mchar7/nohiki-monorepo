import { Link } from '@tanstack/react-router';
import { ArrowRight, CheckCircle2, Circle } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import { Button } from '@/shared/ui/button.tsx';
import { Collapsible, CollapsibleContent } from '@/shared/ui/collapsible.tsx';
import type { OnboardingStep, OnboardingStepTrackerProps } from './Dashboard.types.ts';

type StepState = OnboardingStep['state'];

function StepIcon({ state }: { readonly state: StepState }): JSX.Element {
  const { t } = useTranslation('dashboard');

  if (state === 'completed') {
    return (
      <>
        <CheckCircle2 className="size-6 text-green-500" aria-hidden="true" />
        <span className="sr-only">{t('onboarding.stepState.completed')}</span>
      </>
    );
  }

  if (state === 'active') {
    return (
      <>
        <Circle className="size-6 fill-primary/20 text-primary" aria-hidden="true" />
        <span className="sr-only">{t('onboarding.stepState.active')}</span>
      </>
    );
  }

  return (
    <>
      <Circle className="size-6 text-muted-foreground/40" aria-hidden="true" />
      <span className="sr-only">{t('onboarding.stepState.pending')}</span>
    </>
  );
}

function StepRow({
  step,
  isLast,
}: {
  readonly step: OnboardingStep;
  readonly isLast: boolean;
}): JSX.Element {
  const isActive: boolean = step.state === 'active';
  const isCompleted: boolean = step.state === 'completed';
  const isPending: boolean = step.state === 'pending';

  return (
    <li className="relative flex gap-4" {...(isActive ? { 'aria-current': 'step' as const } : {})}>
      {/* Vertical timeline connector */}
      <div className="flex flex-col items-center">
        <div className="z-10 flex shrink-0 items-center justify-center">
          <StepIcon state={step.state} />
        </div>
        {isLast ? null : (
          <div className={cn('mt-1 w-px grow', isCompleted ? 'bg-green-500/40' : 'bg-border')} />
        )}
      </div>

      {/* Step content */}
      <Collapsible open={isActive} className="min-w-0 flex-1 pb-6">
        <div className="flex flex-col">
          <h3 className={cn('font-medium text-sm leading-6', isPending && 'text-muted-foreground')}>
            {step.title}
          </h3>

          {/* Completion summary for completed steps */}
          {isCompleted && step.completionSummary ? (
            <p className="mt-0.5 text-muted-foreground text-xs">{step.completionSummary}</p>
          ) : null}

          {/* Expanded content for active step */}
          <CollapsibleContent>
            <p className="mt-1 text-muted-foreground text-sm">{step.description}</p>
            <Button asChild={true} size="sm" className="mt-3 gap-1.5">
              <Link to={step.ctaRoute}>
                {step.ctaLabel}
                <ArrowRight className="size-3.5" />
              </Link>
            </Button>
          </CollapsibleContent>
        </div>
      </Collapsible>
    </li>
  );
}

function OnboardingStepTracker({ steps }: OnboardingStepTrackerProps): JSX.Element {
  const { t } = useTranslation('dashboard');
  const lastIndex: number = steps.length - 1;

  return (
    <ol className="list-none space-y-0" aria-label={t('onboarding.stepsAriaLabel')}>
      {steps.map((step, index) => (
        <StepRow key={step.id} step={step} isLast={index === lastIndex} />
      ))}
    </ol>
  );
}

export { OnboardingStepTracker };
