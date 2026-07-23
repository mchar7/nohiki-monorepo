import { Link, useParams } from '@tanstack/react-router';
import { AlertCircle, ArrowLeft } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  FeedbackSection,
  MatchDetailView,
  ScoreBreakdownCard,
  useAdjustScore,
  useCorrelation,
  useRecordFeedback,
  useScoreFeedback,
} from '@/features/job-matching/index.ts';
import type { ScoreFeedbackType } from '@/shared/api';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { useDocumentTitle } from '@/shared/lib/index.ts';
import { Alert, AlertDescription, AlertTitle } from '@/shared/ui/alert.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { PageHeader } from '@/shared/ui/PageHeader.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { PageLayout } from '@/widgets/layout/index.ts';
import { TailoredDocumentAction } from './TailoredDocumentAction.tsx';

/** Encapsulates all feedback-related mutations for a correlation. */
function useMatchFeedback(correlationId: string | undefined): {
  handleSave: () => void;
  handleApply: () => void;
  handleDismiss: () => void;
  handleScoreFeedback: (type: ScoreFeedbackType) => Promise<void>;
  handleScoreAdjust: (newScore: number, reason: string) => Promise<void>;
  isRecording: boolean;
  isSubmittingFeedback: boolean;
  isAdjusting: boolean;
} {
  const { t } = useTranslation(['jobs']);
  const { mutate: recordFeedback, isPending: isRecording } = useRecordFeedback();
  const { mutateAsync: submitScoreFeedback, isPending: isSubmittingFeedback } = useScoreFeedback();
  const { mutateAsync: adjustScore, isPending: isAdjusting } = useAdjustScore();

  const recordAction = (feedbackType: 'SAVED' | 'APPLIED' | 'DISMISSED'): void => {
    if (!correlationId || isRecording) {
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

  return {
    handleSave: () => recordAction('SAVED'),
    handleApply: () => recordAction('APPLIED'),
    handleDismiss: () => recordAction('DISMISSED'),
    handleScoreFeedback: async (type: ScoreFeedbackType) => {
      if (!correlationId) {
        return;
      }
      await submitScoreFeedback({
        params: { path: { correlation_id: correlationId } },
        body: { feedback_type: type },
      });
    },
    handleScoreAdjust: async (newScore: number, reason: string) => {
      if (!correlationId) {
        return;
      }
      await adjustScore({
        params: { path: { correlation_id: correlationId } },
        body: { adjusted_score: newScore, reasoning: reason || '' },
      });
    },
    isRecording,
    isSubmittingFeedback,
    isAdjusting,
  };
}

function MatchDetail(): JSX.Element {
  const { correlationId } = useParams({ from: '/_authenticated/jobs/matches/$correlationId' });
  const { data: correlation, isLoading, error } = useCorrelation(correlationId ?? '');
  const feedback = useMatchFeedback(correlationId);

  if (!correlationId) {
    return <NotFoundState />;
  }

  if (isLoading) {
    return <LoadingState />;
  }

  if (error || !correlation) {
    return <ErrorState error={error} />;
  }

  return (
    <PageLayout className="space-y-6">
      <MatchDetailHeader />
      <MatchDetailContent
        correlationId={correlationId}
        correlation={correlation}
        feedback={feedback}
      />
    </PageLayout>
  );
}

/** Renders the main content grid: detail view, feedback section, and score breakdown. */
function MatchDetailContent({
  correlationId,
  correlation,
  feedback,
}: {
  readonly correlationId: string;
  readonly correlation: NonNullable<ReturnType<typeof useCorrelation>['data']>;
  readonly feedback: ReturnType<typeof useMatchFeedback>;
}): JSX.Element {
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <MatchDetailView
          correlation={correlation}
          onSave={feedback.handleSave}
          onApply={feedback.handleApply}
          onDismiss={feedback.handleDismiss}
          isSaving={feedback.isRecording}
          tailoredDocumentAction={
            <TailoredDocumentAction
              correlationId={correlationId}
              jobTitle={correlation.listing_title}
              company={correlation.listing_company}
            />
          }
        />
        <FeedbackSection
          currentScore={correlation.fit_score}
          onScoreFeedback={feedback.handleScoreFeedback}
          onScoreAdjust={feedback.handleScoreAdjust}
          isSubmitting={feedback.isSubmittingFeedback || feedback.isAdjusting}
        />
      </div>
      <div>
        <ScoreBreakdownCard
          breakdown={correlation.fit_ranking_breakdown}
          fitScore={correlation.fit_score}
        />
      </div>
    </div>
  );
}

function MatchDetailHeader(): JSX.Element {
  const { t } = useTranslation(['jobs']);

  useDocumentTitle(t('pages.matchDetail.title'));

  return (
    <PageHeader
      title={t('pages.matchDetail.title')}
      description={t('pages.matchDetail.description')}
      backTo={ROUTE_PATHS.JOBS.MATCHES}
      preferHistory={true}
    />
  );
}

function LoadingState(): JSX.Element {
  return (
    <PageLayout className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-5 w-72" />
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Skeleton className="h-48 w-full rounded-lg" />
          <Skeleton className="h-64 w-full rounded-lg" />
        </div>
        <Skeleton className="h-96 w-full rounded-lg" />
      </div>
    </PageLayout>
  );
}

function ErrorState({ error }: { readonly error: unknown }): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  return (
    <PageLayout>
      <Alert variant="destructive">
        <AlertCircle className="size-4" />
        <AlertTitle>{t('common:errors.generic')}</AlertTitle>
        <AlertDescription>
          {error instanceof Error ? error.message : t('empty.noMatchDetail')}
        </AlertDescription>
      </Alert>
      <div className="mt-4">
        <Button variant="outline" asChild={true}>
          <Link to={ROUTE_PATHS.JOBS.MATCHES}>
            <ArrowLeft className="mr-2 size-4" />
            {t('common:actions.goBack')}
          </Link>
        </Button>
      </div>
    </PageLayout>
  );
}

function NotFoundState(): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  return (
    <PageLayout>
      <Alert>
        <AlertCircle className="size-4" />
        <AlertTitle>{t('common:errors.notFound')}</AlertTitle>
        <AlertDescription>{t('empty.noMatchDetail')}</AlertDescription>
      </Alert>
      <div className="mt-4">
        <Button variant="outline" asChild={true}>
          <Link to={ROUTE_PATHS.JOBS.MATCHES}>
            <ArrowLeft className="mr-2 size-4" />
            {t('common:actions.goBack')}
          </Link>
        </Button>
      </div>
    </PageLayout>
  );
}

export { MatchDetail };
