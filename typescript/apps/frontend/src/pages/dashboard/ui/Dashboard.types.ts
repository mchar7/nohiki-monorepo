import type { JobCorrelationResponse } from '@/shared/api';
import type { StatTrend } from '../lib/index.ts';

interface CommonMissingSkillsWidgetProps {
  readonly hasSkills: boolean;
  readonly profileId?: string;
}

interface DashboardActivityChartProps {
  readonly correlations: readonly JobCorrelationResponse[];
  readonly isLoading?: boolean;
}

interface DashboardStats {
  readonly jobMatches: number;
  readonly profiles: number;
  readonly documents: number;
  readonly savedJobs: number;
  readonly trends?: {
    readonly jobMatches?: StatTrend;
    readonly documents?: StatTrend;
  };
}

interface DashboardStatsCardsProps {
  readonly stats: DashboardStats;
  readonly isLoading?: boolean;
}

interface LatestDocumentCardProps {
  readonly document: {
    readonly request_id: string;
    readonly status: string;
    readonly download_url?: string | null;
  } | null;
}

interface TopMatchCardProps {
  readonly correlation: {
    readonly id: string;
    readonly listing_title: string;
    readonly listing_company: string | null;
    readonly listing_location: string | null;
    readonly fit_score: number;
  } | null;
}

interface DashboardHighlightsProps {
  readonly topMatch: TopMatchCardProps['correlation'];
  readonly latestDocument: LatestDocumentCardProps['document'];
}

interface OnboardingWelcomeProps {
  readonly displayName?: string | null;
  readonly firstName?: string | null;
}

interface OnboardingProgressBarProps {
  readonly completedSteps: number;
  readonly totalSteps: number;
}

type StepState = 'completed' | 'active' | 'pending';

interface OnboardingStep {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly ctaLabel: string;
  readonly ctaRoute: string;
  readonly completionSummary?: string;
  readonly state: StepState;
}

interface OnboardingStepTrackerProps {
  readonly steps: readonly OnboardingStep[];
}

interface OnboardingDashboardProps {
  readonly displayName?: string | null;
  readonly firstName?: string | null;
  readonly profileCount: number;
  readonly correlationCount: number;
  readonly documentCount: number;
  readonly correlations: readonly { status: string }[];
  readonly profileName?: string;
}

interface ReturningUserDashboardProps {
  readonly stats: DashboardStats;
  readonly correlations: readonly JobCorrelationResponse[];
  readonly profiles: readonly {
    id: string;
    pref_name?: string;
    user_skills?: readonly unknown[];
  }[];
  readonly documents: readonly {
    request_id: string;
    status: string;
    download_url?: string | null;
  }[];
  readonly topMatch: TopMatchCardProps['correlation'] | null;
  readonly latestDocument: LatestDocumentCardProps['document'] | null;
  readonly newMatchCount: number;
  readonly isLoading: boolean;
}

export type {
  CommonMissingSkillsWidgetProps,
  DashboardActivityChartProps,
  DashboardHighlightsProps,
  DashboardStats,
  DashboardStatsCardsProps,
  LatestDocumentCardProps,
  OnboardingDashboardProps,
  OnboardingProgressBarProps,
  OnboardingStep,
  OnboardingStepTrackerProps,
  OnboardingWelcomeProps,
  ReturningUserDashboardProps,
  TopMatchCardProps,
};
