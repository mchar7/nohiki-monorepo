import { useTranslation } from 'react-i18next';
import { useAccount } from '@/features/account/index.ts';
import { useDocuments } from '@/features/document-generation/index.ts';
import { useMyCorrelations } from '@/features/job-matching/index.ts';
import { useProfiles } from '@/features/profile-management/index.ts';
import type { JobCorrelationResponse } from '@/shared/api';
import { ROUTE_PATHS } from '@/shared/config';
import { useDocumentTitle } from '@/shared/lib/index.ts';
import type {
  DashboardStats,
  LatestDocumentCardProps,
  TopMatchCardProps,
} from '../ui/Dashboard.types.ts';
import { getDashboardUserStage, type UserStage } from './getDashboardUserStage.ts';
import { type UseLastVisitReturn, useLastVisit } from './useLastVisit.ts';
import { computeStatTrends, getTopMatch } from './utils.ts';

const DASHBOARD_PAGE_SIZE: number = 5;
const DASHBOARD_DOCUMENTS_PAGE_SIZE: number = 20;
const DASHBOARD_PAGE: number = 1;

/** Minimum correlation count to mark the "browse" step as done */
const BROWSE_THRESHOLD: number = 5;
const TOTAL_ONBOARDING_STEPS: number = 4;

const ONBOARDING_STEP_LABELS = [
  'onboarding.steps.profile.title',
  'onboarding.steps.browse.title',
  'onboarding.steps.matches.title',
  'onboarding.steps.resume.title',
] as const;

const ONBOARDING_STEP_ROUTES = [
  ROUTE_PATHS.PROFILES.NEW,
  ROUTE_PATHS.JOBS.LIST,
  ROUTE_PATHS.JOBS.MATCHES,
  ROUTE_PATHS.DOCUMENTS.LIST,
] as const;

interface OnboardingProgress {
  readonly completedSteps: number;
  readonly totalSteps: number;
  readonly nextStepLabel: string;
  readonly nextStepRoute: string;
}

interface OnboardingInput {
  readonly profileCount: number;
  readonly correlationCount: number;
  readonly documentCount: number;
  readonly correlations: readonly JobCorrelationResponse[];
  readonly t: (key: string) => string;
}

function computeOnboardingProgress({
  profileCount,
  correlationCount,
  documentCount,
  correlations,
  t,
}: OnboardingInput): OnboardingProgress {
  const stepsDone = [
    profileCount >= 1,
    correlationCount >= 1,
    correlations.some((c) => c.status === 'VIEWED') || correlationCount >= BROWSE_THRESHOLD,
    documentCount >= 1,
  ];
  const completedSteps = stepsDone.filter(Boolean).length;
  const firstIncomplete = stepsDone.indexOf(false);
  const nextIdx = Math.max(firstIncomplete, 0);

  const nextStepLabels = ONBOARDING_STEP_LABELS.map((key) => t(key));

  return {
    completedSteps,
    totalSteps: TOTAL_ONBOARDING_STEPS,
    nextStepLabel: nextStepLabels[nextIdx] ?? nextStepLabels[0] ?? '',
    nextStepRoute: ONBOARDING_STEP_ROUTES[nextIdx] ?? ONBOARDING_STEP_ROUTES[0] ?? '',
  };
}

interface DashboardData {
  /** User account info (display name, first name) */
  readonly account: { display_name?: string; first_name?: string } | undefined;
  /** Total number of profiles */
  readonly profileCount: number;
  /** Total number of correlations */
  readonly correlationCount: number;
  /** Total number of documents */
  readonly documentCount: number;
  /** Raw profile data with shape needed by child components */
  readonly profiles: readonly {
    id: string;
    pref_name?: string;
    user_skills?: readonly unknown[];
  }[];
  /** Raw correlation data */
  readonly correlations: readonly JobCorrelationResponse[];
  /** Raw document data */
  readonly documents: readonly {
    request_id: string;
    status: string;
    created_at: string;
    download_url?: string | null;
  }[];
  /** Computed stat card data including trends */
  readonly stats: DashboardStats;
  /** User's onboarding stage */
  readonly stage: UserStage;
  /** Top-scoring correlation for the highlights card */
  readonly topMatch: TopMatchCardProps['correlation'] | null;
  /** Most recent document for the highlights card */
  readonly latestDocument: LatestDocumentCardProps['document'] | null;
  /** Number of new matches since last visit */
  readonly newMatchCount: number;
  /** Onboarding progress strip data (for 'getting-started' stage) */
  readonly onboardingProgress: OnboardingProgress;
  /** Whether any data query is still loading */
  readonly isLoading: boolean;
}

interface NormalizedQueries {
  readonly accountData: Record<string, unknown> | undefined;
  readonly profileCount: number;
  readonly correlationCount: number;
  readonly documentCount: number;
  readonly correlations: readonly JobCorrelationResponse[];
  readonly profiles: DashboardData['profiles'];
  readonly documents: DashboardData['documents'];
  readonly isLoading: boolean;
  readonly newSinceLastVisit: UseLastVisitReturn['newSinceLastVisit'];
}

function useDashboardQueries(): NormalizedQueries {
  const { data: accountData } = useAccount();
  const { data: profilesData, isLoading: profilesLoading } = useProfiles();
  const { data: correlationsData, isLoading: correlationsLoading } = useMyCorrelations({
    page: DASHBOARD_PAGE,
    pageSize: DASHBOARD_PAGE_SIZE,
  });
  const { data: documentsData, isLoading: documentsLoading } = useDocuments(
    DASHBOARD_PAGE,
    DASHBOARD_DOCUMENTS_PAGE_SIZE,
  );
  const { newSinceLastVisit } = useLastVisit();

  return {
    accountData,
    profileCount: profilesData?.total ?? 0,
    correlationCount: correlationsData?.total ?? 0,
    documentCount: documentsData?.total ?? 0,
    correlations: (correlationsData?.items ?? []) as readonly JobCorrelationResponse[],
    profiles: (profilesData?.items ?? []) as DashboardData['profiles'],
    documents: (documentsData?.items ?? []) as DashboardData['documents'],
    isLoading: profilesLoading || correlationsLoading || documentsLoading,
    newSinceLastVisit,
  };
}

/**
 * Central data hook for the Dashboard page.
 *
 * Encapsulates ALL dashboard data fetching and derived computations.
 *
 * Queries profiles, correlations, documents, and account data, then derives
 * the user stage, stat trends, top match, latest document, and new match count.
 */
function useDashboardData(): DashboardData {
  const { t } = useTranslation('dashboard');
  useDocumentTitle(t('title'));

  const q = useDashboardQueries();

  const stage = getDashboardUserStage({
    profileCount: q.profileCount,
    correlationCount: q.correlationCount,
    documentCount: q.documentCount,
  });

  const trends = computeStatTrends(q.correlations, q.documents);
  const stats: DashboardStats = {
    jobMatches: q.correlationCount,
    profiles: q.profileCount,
    documents: q.documentCount,
    savedJobs: q.correlations.filter((c) => c.status === 'SAVED').length,
    trends,
  };

  return {
    account: q.accountData,
    profileCount: q.profileCount,
    correlationCount: q.correlationCount,
    documentCount: q.documentCount,
    profiles: q.profiles,
    correlations: q.correlations,
    documents: q.documents,
    stats,
    stage,
    topMatch: getTopMatch(q.correlations),
    latestDocument: q.documents[0] ?? null,
    newMatchCount: q.newSinceLastVisit(q.correlations),
    onboardingProgress: computeOnboardingProgress({
      profileCount: q.profileCount,
      correlationCount: q.correlationCount,
      documentCount: q.documentCount,
      correlations: q.correlations,
      t,
    }),
    isLoading: q.isLoading,
  };
}

export type { DashboardData };
export { useDashboardData };
