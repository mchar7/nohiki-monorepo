import { Check, Minus, Plus } from 'lucide-react';
import { type ChangeEvent, type JSX, type ReactNode, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { ScoreFeedbackType } from '@/shared/api';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { CharacterCounter } from '@/shared/ui/character-counter.tsx';
import { Label } from '@/shared/ui/label.tsx';
import { Slider } from '@/shared/ui/slider.tsx';
import { Textarea } from '@/shared/ui/textarea.tsx';
import { ToggleGroup, ToggleGroupItem } from '@/shared/ui/toggle-group.tsx';

interface FeedbackSectionProps {
  readonly currentScore: number;
  readonly onScoreFeedback: (type: ScoreFeedbackType) => Promise<void>;
  readonly onScoreAdjust: (newScore: number, reason: string) => Promise<void>;
  readonly isSubmitting: boolean;
}

const SCORE_API_DIVISOR: number = 100;
const ADJUST_REASON_MAX_LENGTH: number = 500;

function FeedbackSection({
  currentScore,
  onScoreFeedback,
  onScoreAdjust,
  isSubmitting,
}: FeedbackSectionProps): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);
  const [feedbackType, setFeedbackType] = useState<ScoreFeedbackType | null>(null);
  const [adjustedScore, setAdjustedScore] = useState(Math.round(currentScore));
  const [adjustReason, setAdjustReason] = useState('');
  const [showAdjust, setShowAdjust] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const handleFeedbackChange = async (value: string): Promise<void> => {
    if (!value || isSubmitting) {
      return;
    }
    const nextFeedback = value as ScoreFeedbackType;
    const previousFeedback = feedbackType;
    setFeedbackType(nextFeedback);
    setStatus(t('jobs:feedback.submittingFeedback'));
    try {
      await onScoreFeedback(nextFeedback);
      toast.success(t('jobs:feedback.feedbackSuccess'));
      setStatus(t('jobs:feedback.feedbackSuccess'));
    } catch {
      setFeedbackType(previousFeedback);
      setStatus(t('jobs:feedback.feedbackErrorFallback'));
    }
  };

  const handleAdjustSubmit = async (): Promise<void> => {
    setStatus(t('jobs:feedback.submittingFeedback'));
    try {
      await onScoreAdjust(adjustedScore / SCORE_API_DIVISOR, adjustReason);
      toast.success(t('jobs:feedback.feedbackSuccess'));
      setStatus(t('jobs:feedback.feedbackSuccess'));
      setShowAdjust(false);
      setAdjustReason('');
    } catch {
      setStatus(t('jobs:feedback.feedbackErrorFallback'));
    }
  };

  const cardContent: ReactNode = showAdjust ? (
    <AdjustScoreForm
      adjustedScore={adjustedScore}
      onScoreChange={([value = 0]: number[]): void => setAdjustedScore(value)}
      adjustReason={adjustReason}
      onReasonChange={(e: ChangeEvent<HTMLTextAreaElement>): void =>
        setAdjustReason(e.target.value)
      }
      onSubmit={handleAdjustSubmit}
      onCancel={(): void => setShowAdjust(false)}
      isSubmitting={isSubmitting}
    />
  ) : (
    <QuickFeedbackForm
      feedbackType={feedbackType}
      onFeedbackChange={(value: string): void => {
        void handleFeedbackChange(value);
      }}
      onShowAdjust={(): void => setShowAdjust(true)}
      showAdjustAction={feedbackType !== null}
      isSubmitting={isSubmitting}
    />
  );

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>{t('jobs:feedback.title')}</CardTitle>
        <CardDescription>{t('jobs:feedback.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">{cardContent}</CardContent>
      <p className="px-6 pb-4 text-muted-foreground text-sm" role="status" aria-live="polite">
        {status ?? ''}
      </p>
    </Card>
  );
}

function AdjustScoreForm({
  adjustedScore,
  onScoreChange,
  adjustReason,
  onReasonChange,
  onSubmit,
  onCancel,
  isSubmitting,
}: {
  readonly adjustedScore: number;
  readonly onScoreChange: (values: number[]) => void;
  readonly adjustReason: string;
  readonly onReasonChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
  readonly onSubmit: () => void;
  readonly onCancel: () => void;
  readonly isSubmitting: boolean;
}): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);
  const adjustReasonId = useId();
  const sliderLabelId = useId();

  return (
    <>
      <div className="space-y-3">
        <Label id={sliderLabelId}>{t('jobs:feedback.adjustDescription')}</Label>
        <div className="flex items-center gap-4">
          <Slider
            value={[adjustedScore]}
            onValueChange={onScoreChange}
            max={100}
            step={1}
            className="flex-1"
            aria-labelledby={sliderLabelId}
          />
          <span className="w-12 text-right font-mono font-semibold text-lg tabular-nums">
            {`${adjustedScore} / 100`}
          </span>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor={adjustReasonId}>{t('jobs:feedback.adjustReason')}</Label>
        <Textarea
          id={adjustReasonId}
          value={adjustReason}
          onChange={onReasonChange}
          placeholder={t('jobs:feedback.adjustReasonPlaceholder')}
          rows={3}
          maxLength={ADJUST_REASON_MAX_LENGTH}
        />
        <CharacterCounter
          current={adjustReason.length}
          max={ADJUST_REASON_MAX_LENGTH}
          className="block text-right"
        />
      </div>

      <div className="flex items-center gap-2">
        <Button onClick={onSubmit} disabled={isSubmitting} className="flex-1">
          {t('jobs:feedback.submitFeedback')}
        </Button>
        <Button variant="outline" onClick={onCancel}>
          {t('common:actions.cancel')}
        </Button>
      </div>
    </>
  );
}

function QuickFeedbackForm({
  feedbackType,
  onFeedbackChange,
  onShowAdjust,
  showAdjustAction,
  isSubmitting,
}: {
  readonly feedbackType: ScoreFeedbackType | null;
  readonly onFeedbackChange: (value: string) => void;
  readonly onShowAdjust: () => void;
  readonly showAdjustAction: boolean;
  readonly isSubmitting: boolean;
}): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const toggleLabelId = useId();

  return (
    <>
      <div className="space-y-2">
        <Label id={toggleLabelId}>{t('jobs:feedback.scoreQuestion')}</Label>
        <ToggleGroup
          type="single"
          value={feedbackType ?? ''}
          onValueChange={onFeedbackChange}
          disabled={isSubmitting}
          className="justify-start"
          aria-labelledby={toggleLabelId}
        >
          <ToggleGroupItem value="GOOD" aria-label={t('jobs:feedback.good')} className="gap-1.5">
            <Check className="size-4" aria-hidden="true" />
            {t('jobs:feedback.good')}
          </ToggleGroupItem>
          <ToggleGroupItem
            value="TOO_HIGH"
            aria-label={t('jobs:feedback.tooHigh')}
            className="gap-1.5"
          >
            <Minus className="size-4" aria-hidden="true" />
            {t('jobs:feedback.tooHigh')}
          </ToggleGroupItem>
          <ToggleGroupItem
            value="TOO_LOW"
            aria-label={t('jobs:feedback.tooLow')}
            className="gap-1.5"
          >
            <Plus className="size-4" aria-hidden="true" />
            {t('jobs:feedback.tooLow')}
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      {showAdjustAction ? (
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={onShowAdjust} disabled={isSubmitting}>
            {t('jobs:feedback.adjustTitle')}
          </Button>
        </div>
      ) : null}
    </>
  );
}

export { FeedbackSection };
