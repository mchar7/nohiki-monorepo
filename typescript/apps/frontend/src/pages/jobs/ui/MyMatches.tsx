import { AlertCircle } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  MatchesDataTable,
  type MatchesFilters,
  MatchesFiltersBar,
  MatchesStatsCards,
  MatchingMethodologyInfo,
  useMatchesFilters,
  useMyCorrelations,
  useRecordFeedback,
  useScoreFeedback,
} from '@/features/job-matching/index.ts';
import { useProfiles } from '@/features/profile-management/index.ts';
import type {
  FeedbackType,
  JobCorrelationResponse,
  ProfileResponse,
  ScoreFeedbackType,
} from '@/shared/api';
import {
  useDocumentTitle,
  useIsMobileLayout,
  useMainScrollRef,
  usePullToRefresh,
} from '@/shared/lib/index.ts';
import { Alert, AlertDescription, AlertTitle } from '@/shared/ui/alert.tsx';
import { DensityToggle } from '@/shared/ui/density-toggle.tsx';
import { PullIndicator } from '@/shared/ui/pull-indicator.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { TableSkeleton } from '@/shared/ui/skeleton-layouts.tsx';
import { PageLayout } from '@/widgets/layout/index.ts';

/** Minimum fit score (0-100 integer) to classify a correlation as high-quality */
const HIGH_QUALITY_FIT_SCORE_THRESHOLD: number = 80;
const DAYS_PER_WEEK: number = 7;

interface MatchesStats {
  total: number;
  highQuality: number;
  newThisWeek: number;
  saved: number;
}

/** Derives display stats from correlation data to avoid inline computation. */
function computeMatchStats(
  correlations: readonly JobCorrelationResponse[],
  total: number,
): MatchesStats {
  const weekAgo = new Date();
  weekAgo.setDate(weekAgo.getDate() - DAYS_PER_WEEK);

  let highQuality = 0;
  let newThisWeek = 0;
  let saved = 0;

  for (const c of correlations) {
    if (c.fit_score >= HIGH_QUALITY_FIT_SCORE_THRESHOLD) {
      highQuality += 1;
    }
    if (c.status === 'SAVED') {
      saved += 1;
    }
    if (c.status === 'PENDING' && new Date(c.created_at) >= weekAgo) {
      newThisWeek += 1;
    }
  }

  return { total, highQuality, newThisWeek, saved };
}

/** Converts a UI 'like'/'dislike' action into the API feedback type. */
function toFeedbackType(type: 'like' | 'dislike'): ScoreFeedbackType {
  return type === 'like' ? 'GOOD' : 'TOO_HIGH';
}

function MyMatches(): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const { filters, setPrefId, setMinScore, clearFilters, hasActiveFilters, activeFilterCount } =
    useMatchesFilters();
  const { data: profilesData, isLoading: profilesLoading } = useProfiles();
  const {
    data: correlationsData,
    isLoading: correlationsLoading,
    error: correlationsError,
    refetch: refetchCorrelations,
  } = useMyCorrelations({
    page: filters.page,
    pageSize: 20,
    ...(filters.prefId !== null ? { prefId: filters.prefId } : {}),
    ...(filters.minScore !== null ? { minScore: filters.minScore } : {}),
  });
  const { mutateAsync: submitFeedback } = useScoreFeedback();
  const { mutate: recordFeedback, isPending: isRecordingFeedback } = useRecordFeedback();

  const isMobile = useIsMobileLayout();
  const mainScrollRef = useMainScrollRef();
  const { isRefreshing, pullDistance } = usePullToRefresh({
    ref: mainScrollRef,
    onRefresh: refetchCorrelations,
    enabled: isMobile,
  });

  const profiles = profilesData?.items ?? [];
  const correlations = correlationsData?.items ?? [];
  const isLoading = profilesLoading || correlationsLoading;
  const stats = computeMatchStats(correlations, correlationsData?.total ?? 0);

  const handleFeedback = async (correlationId: string, type: 'like' | 'dislike'): Promise<void> => {
    await submitFeedback({
      params: { path: { correlation_id: correlationId } },
      body: { feedback_type: toFeedbackType(type) },
    });
    toast.success(t('feedback.feedbackSuccess'));
  };

  const handleStatusAction = (correlationId: string, feedbackType: FeedbackType): void => {
    if (isRecordingFeedback) {
      return;
    }
    recordFeedback(
      {
        params: { path: { correlation_id: correlationId } },
        body: { feedback_type: feedbackType },
      },
      { onError: () => toast.error(t('feedback.feedbackErrorFallback')) },
    );
  };

  return (
    <PageLayout className="space-y-6">
      <PullIndicator pullDistance={pullDistance} isRefreshing={isRefreshing} />
      <PageHeader />
      <MatchingMethodologyInfo />
      <MatchesStatsCards stats={stats} isLoading={isLoading} />
      <div className="flex items-center justify-end">
        <DensityToggle />
      </div>
      <MatchesList
        profiles={profiles}
        filters={filters}
        correlations={correlations}
        isLoading={isLoading}
        error={correlationsError}
        hasActiveFilters={hasActiveFilters}
        activeFilterCount={activeFilterCount}
        setPrefId={setPrefId}
        setMinScore={setMinScore}
        clearFilters={clearFilters}
        refetchCorrelations={refetchCorrelations}
        onFeedback={handleFeedback}
        onStatusAction={handleStatusAction}
        isStatusActionPending={isRecordingFeedback}
      />
    </PageLayout>
  );
}

function PageHeader(): JSX.Element {
  const { t } = useTranslation(['jobs']);
  useDocumentTitle(t('pages.matches.title'));

  return (
    <div>
      <h1 className="font-semibold text-2xl tracking-tight">{t('pages.matches.title')}</h1>
      <p className="text-muted-foreground">{t('pages.matches.description')}</p>
    </div>
  );
}

function MatchesContent({
  correlations,
  isLoading,
  error,
  onFeedback,
  onStatusAction,
  isStatusActionPending,
  hasProfiles,
  hasActiveFilters,
  onRefetch,
  onClearFilters,
}: {
  readonly correlations: readonly JobCorrelationResponse[];
  readonly isLoading: boolean;
  readonly error: unknown;
  readonly onFeedback: (correlationId: string, type: 'like' | 'dislike') => Promise<void>;
  readonly onStatusAction: (correlationId: string, feedbackType: FeedbackType) => void;
  readonly isStatusActionPending: boolean;
  readonly hasProfiles: boolean;
  readonly hasActiveFilters: boolean;
  readonly onRefetch: () => void;
  readonly onClearFilters: () => void;
}): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-9 w-28" />
        </div>
        <TableSkeleton columns={7} rows={5} />
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="size-4" />
        <AlertTitle>{t('common:errors.generic')}</AlertTitle>
        <AlertDescription>
          {error instanceof Error ? error.message : String(error)}
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <MatchesDataTable
      data={correlations}
      onFeedback={onFeedback}
      onStatusAction={onStatusAction}
      isStatusActionPending={isStatusActionPending}
      hasProfiles={hasProfiles}
      hasActiveFilters={hasActiveFilters}
      onRefetch={onRefetch}
      onClearFilters={onClearFilters}
    />
  );
}

interface MatchesListProps {
  readonly profiles: readonly ProfileResponse[];
  readonly filters: MatchesFilters;
  readonly correlations: readonly JobCorrelationResponse[];
  readonly isLoading: boolean;
  readonly error: unknown;
  readonly hasActiveFilters: boolean;
  readonly activeFilterCount: number;
  readonly setPrefId: (id: string | null) => void;
  readonly setMinScore: (score: number | null) => void;
  readonly clearFilters: () => void;
  readonly refetchCorrelations: () => void;
  readonly onFeedback: (correlationId: string, type: 'like' | 'dislike') => Promise<void>;
  readonly onStatusAction: (correlationId: string, feedbackType: FeedbackType) => void;
  readonly isStatusActionPending: boolean;
}

function MatchesList({
  profiles,
  filters,
  correlations,
  isLoading,
  error,
  hasActiveFilters,
  activeFilterCount,
  setPrefId,
  setMinScore,
  clearFilters,
  refetchCorrelations,
  onFeedback,
  onStatusAction,
  isStatusActionPending,
}: MatchesListProps): JSX.Element {
  return (
    <>
      <MatchesFiltersBar
        profiles={profiles}
        selectedPrefId={filters.prefId}
        minScore={filters.minScore}
        onPrefIdChange={setPrefId}
        onMinScoreChange={setMinScore}
        onClear={clearFilters}
        hasActiveFilters={hasActiveFilters}
        activeFilterCount={activeFilterCount}
      />
      <div aria-busy={isLoading} aria-live="polite">
        <MatchesContent
          correlations={correlations}
          isLoading={isLoading}
          error={error}
          onFeedback={onFeedback}
          onStatusAction={onStatusAction}
          isStatusActionPending={isStatusActionPending}
          hasProfiles={profiles.length > 0}
          hasActiveFilters={hasActiveFilters}
          onRefetch={refetchCorrelations}
          onClearFilters={clearFilters}
        />
      </div>
    </>
  );
}

export { MyMatches };
