import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { PageLayout } from '@/widgets/layout/index.ts';
import { useDashboardData } from './lib/index.ts';
import {
  DashboardSkeleton,
  OnboardingDashboard,
  OnboardingProgressStrip,
  ReturningUserDashboard,
} from './ui/index.ts';

/**
 * Dashboard page orchestrator.
 *
 * Fetches data via `useDashboardData`, detects the user's onboarding stage,
 * and delegates rendering to the appropriate stage-specific view.
 */
export function Dashboard(): JSX.Element {
  const { t } = useTranslation('dashboard');
  const data = useDashboardData();

  if (data.isLoading) {
    return (
      <PageLayout className="space-y-6">
        <div>
          <h1 className="font-bold text-2xl">{t('title')}</h1>
        </div>
        <DashboardSkeleton />
      </PageLayout>
    );
  }

  return (
    <PageLayout className="space-y-6">
      <div>
        <h1 className="font-bold text-2xl">{t('title')}</h1>
        <p className="text-muted-foreground">{t('subtitle')}</p>
      </div>

      {data.stage === 'new' && (
        <OnboardingDashboard
          displayName={data.account?.display_name}
          firstName={data.account?.first_name}
          profileCount={data.profileCount}
          correlationCount={data.correlationCount}
          documentCount={data.documentCount}
          correlations={data.correlations}
        />
      )}

      {data.stage === 'getting-started' && (
        <>
          <OnboardingProgressStrip
            completedSteps={data.onboardingProgress.completedSteps}
            totalSteps={data.onboardingProgress.totalSteps}
            nextStepLabel={data.onboardingProgress.nextStepLabel}
            nextStepRoute={data.onboardingProgress.nextStepRoute}
          />
          <ReturningUserDashboard
            stats={data.stats}
            correlations={data.correlations}
            profiles={data.profiles}
            documents={data.documents}
            topMatch={data.topMatch}
            latestDocument={data.latestDocument}
            newMatchCount={data.newMatchCount}
            isLoading={data.isLoading}
          />
        </>
      )}

      {data.stage === 'active' && (
        <ReturningUserDashboard
          stats={data.stats}
          correlations={data.correlations}
          profiles={data.profiles}
          documents={data.documents}
          topMatch={data.topMatch}
          latestDocument={data.latestDocument}
          newMatchCount={data.newMatchCount}
          isLoading={data.isLoading}
        />
      )}
    </PageLayout>
  );
}
