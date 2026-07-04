import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { ROUTE_PATHS } from '@/shared/config';

import type { OnboardingDashboardProps, OnboardingStep } from './Dashboard.types.ts';
import { OnboardingProgressBar } from './OnboardingProgressBar.tsx';
import { OnboardingStepTracker } from './OnboardingStepTracker.tsx';
import { OnboardingWelcome } from './OnboardingWelcome.tsx';

/** Minimum correlation count that implies the user has browsed jobs enough to mark step 3 */
const BROWSE_THRESHOLD: number = 5;

/** Total onboarding steps in the wizard */

/** Step index constants for deriveState comparisons */
const STEP_INDEX_PROFILE: number = 0;
const STEP_INDEX_BROWSE: number = 1;
const STEP_INDEX_MATCHES: number = 2;
const STEP_INDEX_RESUME: number = 3;
const TOTAL_STEPS: number = 4;

type StepState = 'completed' | 'active' | 'pending';

/**
 * Determines state for each onboarding step based on completion status.
 * First incomplete step becomes 'active'; earlier steps are 'completed'; later are 'pending'.
 */
function computeStepStates(
  profileCount: number,
  correlationCount: number,
  documentCount: number,
  correlations: readonly { status: string }[],
): readonly [boolean, boolean, boolean, boolean] {
  const step1Done: boolean = profileCount >= 1;
  const step2Done: boolean = correlationCount >= 1;
  const hasViewedMatch: boolean = correlations.some((c) => c.status === 'VIEWED');
  const step3Done: boolean = hasViewedMatch || correlationCount >= BROWSE_THRESHOLD;
  const step4Done: boolean = documentCount >= 1;
  return [step1Done, step2Done, step3Done, step4Done] as const;
}

function deriveState(isDone: boolean, isFirstIncomplete: boolean): StepState {
  if (isDone) {
    return 'completed';
  }
  if (isFirstIncomplete) {
    return 'active';
  }
  return 'pending';
}

function OnboardingDashboard({
  displayName,
  firstName,
  profileCount,
  correlationCount,
  documentCount,
  correlations,
  profileName,
}: OnboardingDashboardProps): JSX.Element {
  const { t } = useTranslation('dashboard');

  const [step1Done, step2Done, step3Done, step4Done] = computeStepStates(
    profileCount,
    correlationCount,
    documentCount,
    correlations,
  );

  const completions: readonly boolean[] = [step1Done, step2Done, step3Done, step4Done];
  const completedSteps: number = completions.filter(Boolean).length;

  // The first incomplete step is the active one
  const firstIncompleteIndex: number = completions.indexOf(false);

  const steps: readonly OnboardingStep[] = [
    {
      id: 'create-profile',
      title: t('onboarding.steps.profile.title'),
      description: t('onboarding.steps.profile.description'),
      ctaLabel: t('onboarding.steps.profile.cta'),
      ctaRoute: ROUTE_PATHS.PROFILES.NEW,
      completionSummary:
        step1Done && profileName
          ? t('onboarding.steps.profile.completionSummary', { name: profileName })
          : undefined,
      state: deriveState(step1Done, firstIncompleteIndex === STEP_INDEX_PROFILE),
    },
    {
      id: 'browse-jobs',
      title: t('onboarding.steps.browse.title'),
      description: t('onboarding.steps.browse.description'),
      ctaLabel: t('onboarding.steps.browse.cta'),
      ctaRoute: ROUTE_PATHS.JOBS.LIST,
      state: deriveState(step2Done, firstIncompleteIndex === STEP_INDEX_BROWSE),
    },
    {
      id: 'review-matches',
      title: t('onboarding.steps.matches.title'),
      description: t('onboarding.steps.matches.description'),
      ctaLabel: t('onboarding.steps.matches.cta'),
      ctaRoute: ROUTE_PATHS.JOBS.MATCHES,
      state: deriveState(step3Done, firstIncompleteIndex === STEP_INDEX_MATCHES),
    },
    {
      id: 'generate-resume',
      title: t('onboarding.steps.resume.title'),
      description: t('onboarding.steps.resume.description'),
      ctaLabel: t('onboarding.steps.resume.cta'),
      ctaRoute: ROUTE_PATHS.DOCUMENTS.LIST,
      state: deriveState(step4Done, firstIncompleteIndex === STEP_INDEX_RESUME),
    },
  ];

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <OnboardingWelcome displayName={displayName} firstName={firstName} />
      <OnboardingProgressBar completedSteps={completedSteps} totalSteps={TOTAL_STEPS} />
      <OnboardingStepTracker steps={steps} />
    </div>
  );
}

export { OnboardingDashboard };
