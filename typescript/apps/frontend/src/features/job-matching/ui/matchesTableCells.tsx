import { Link, useNavigate } from '@tanstack/react-router';
import type { Column, HeaderContext, Row, useReactTable } from '@tanstack/react-table';
import type { TFunction } from 'i18next';
import {
  ArrowUpDown,
  Building2,
  ExternalLink,
  MapPin,
  MoreVertical,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react';
import { type JSX, useState } from 'react';
import type { FeedbackType, JobCorrelationResponse } from '@/shared/api';
import {
  formatShortDate,
  getSafeExternalUrl,
  handleNavigationPromise,
  parseMatchExplanation,
} from '@/shared/lib/index.ts';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Checkbox } from '@/shared/ui/checkbox.tsx';
import {
  ResponsiveMenu,
  ResponsiveMenuItem,
  ResponsiveMenuSeparator,
} from '@/shared/ui/responsive-menu.tsx';
import { ScoreBadge } from '@/shared/ui/score-badge.tsx';
import { StatusBadge } from '@/shared/ui/status-badge.tsx';
import { correlationStatusThemes } from '@/shared/ui/status-badge-model.ts';

const EM_DASH = '\u2014';
const MAX_STRENGTH_BADGES: number = 2;

/** Pairs each item with a key that stays stable and unique even when labels repeat. */
function withOccurrenceKeys<T>(
  items: readonly T[],
  toLabel: (item: T) => string,
): ReadonlyArray<{ readonly item: T; readonly key: string }> {
  const occurrenceCounts = new Map<string, number>();
  return items.map((item) => {
    const label = toLabel(item);
    const occurrence = occurrenceCounts.get(label) ?? 0;
    occurrenceCounts.set(label, occurrence + 1);
    return { item, key: `${label}#${occurrence}` };
  });
}

function SelectAllHeader({
  table,
  t,
}: {
  readonly table: ReturnType<typeof useReactTable<JobCorrelationResponse>>;
  readonly t: TFunction<['jobs', 'common']>;
}): JSX.Element {
  const handleSelectAll = (value: boolean | 'indeterminate'): void => {
    table.toggleAllPageRowsSelected(Boolean(value));
  };

  return (
    <div className="flex items-center justify-center">
      <Checkbox
        checked={
          table.getIsAllPageRowsSelected() || (table.getIsSomePageRowsSelected() && 'indeterminate')
        }
        onCheckedChange={handleSelectAll}
        aria-label={t('common:a11y.selectAll')}
      />
    </div>
  );
}

function RowSelectCell({
  row,
  t,
}: {
  readonly row: Row<JobCorrelationResponse>;
  readonly t: TFunction<['jobs', 'common']>;
}): JSX.Element {
  const handleRowSelect = (value: boolean | 'indeterminate'): void => {
    row.toggleSelected(Boolean(value));
  };

  return (
    <div className="flex items-center justify-center">
      <Checkbox
        checked={row.getIsSelected()}
        onCheckedChange={handleRowSelect}
        aria-label={t('common:a11y.selectRow')}
      />
    </div>
  );
}

function SortableColumnHeader({
  column,
  label,
}: {
  readonly column: Column<JobCorrelationResponse>;
  readonly label: string;
}): JSX.Element {
  const handleToggleSort = (): void => {
    column.toggleSorting(column.getIsSorted() === 'asc');
  };

  return (
    <Button variant="ghost" className="-ml-4" onClick={handleToggleSort}>
      {label}
      <ArrowUpDown className="ml-2 size-4" />
    </Button>
  );
}

function ActionsCell({
  row,
  onFeedback,
  onStatusAction,
  isStatusActionPending,
  t,
}: {
  readonly row: Row<JobCorrelationResponse>;
  readonly onFeedback:
    | ((correlationId: string, type: 'like' | 'dislike') => Promise<void>)
    | undefined;
  readonly onStatusAction: (correlationId: string, feedbackType: FeedbackType) => void;
  readonly isStatusActionPending: boolean;
  readonly t: TFunction<['jobs', 'common']>;
}): JSX.Element {
  const [menuOpen, setMenuOpen] = useState(false);
  const [feedback, setFeedback] = useState<'like' | 'dislike' | null>(null);
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);
  const [feedbackStatus, setFeedbackStatus] = useState<string | null>(null);
  const navigate = useNavigate();
  const listingUrl = getSafeExternalUrl(row.original.listing_url);

  const handleFeedback = async (nextFeedback: 'like' | 'dislike'): Promise<void> => {
    if (!onFeedback || isSubmittingFeedback || feedback === nextFeedback) {
      return;
    }
    const previousFeedback = feedback;
    setFeedback(nextFeedback);
    setIsSubmittingFeedback(true);
    setFeedbackStatus(t('jobs:feedback.submittingFeedback'));
    try {
      await onFeedback(row.original.id, nextFeedback);
      setFeedbackStatus(t('jobs:feedback.feedbackSuccess'));
    } catch {
      setFeedback(previousFeedback);
      setFeedbackStatus(t('jobs:feedback.feedbackErrorFallback'));
    } finally {
      setIsSubmittingFeedback(false);
    }
  };

  const handleStatusAction = (feedbackType: FeedbackType): void => {
    if (isStatusActionPending) {
      return;
    }
    setMenuOpen(false);
    onStatusAction(row.original.id, feedbackType);
  };

  const handleViewDetails = (): void => {
    handleNavigationPromise(
      navigate({
        to: '/jobs/matches/$correlationId',
        params: { correlationId: row.original.id },
      }),
    );
  };

  const handleViewOriginal = (): void => {
    if (listingUrl) {
      window.open(listingUrl, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <div className="flex items-center gap-1">
      {onFeedback ? (
        <>
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-muted-foreground hover:text-green-600 data-[selected=true]:bg-green-600/10 data-[selected=true]:text-green-700"
            onClick={(): void => {
              void handleFeedback('like');
            }}
            disabled={isSubmittingFeedback}
            aria-pressed={feedback === 'like'}
            data-selected={feedback === 'like'}
          >
            <ThumbsUp className="size-4" />
            <span className="sr-only">{t('jobs:actions.like')}</span>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-muted-foreground hover:text-red-600 data-[selected=true]:bg-red-600/10 data-[selected=true]:text-red-700"
            onClick={(): void => {
              void handleFeedback('dislike');
            }}
            disabled={isSubmittingFeedback}
            aria-pressed={feedback === 'dislike'}
            data-selected={feedback === 'dislike'}
          >
            <ThumbsDown className="size-4" />
            <span className="sr-only">{t('jobs:actions.dislike')}</span>
          </Button>
          <span className="sr-only" role="status" aria-live="polite">
            {feedbackStatus ?? ''}
          </span>
        </>
      ) : null}
      <ResponsiveMenu
        open={menuOpen}
        onOpenChange={setMenuOpen}
        title={t('jobs:card.actions')}
        trigger={
          <Button variant="ghost" size="icon" className="size-8">
            <MoreVertical className="size-4" />
            <span className="sr-only">{t('common:a11y.more')}</span>
          </Button>
        }
      >
        <ResponsiveMenuItem onClick={handleViewDetails}>
          {t('jobs:card.viewDetails')}
        </ResponsiveMenuItem>
        <ResponsiveMenuItem
          icon={<ExternalLink className="size-4" aria-hidden="true" />}
          onClick={handleViewOriginal}
          disabled={!listingUrl}
        >
          {t('jobs:pages.detail.viewOriginal')}
        </ResponsiveMenuItem>
        <ResponsiveMenuSeparator />
        <ResponsiveMenuItem
          onClick={() => handleStatusAction('SAVED')}
          disabled={isStatusActionPending}
        >
          {t('jobs:actions.save')}
        </ResponsiveMenuItem>
        <ResponsiveMenuItem
          onClick={() => handleStatusAction('APPLIED')}
          disabled={isStatusActionPending}
        >
          {t('jobs:actions.apply')}
        </ResponsiveMenuItem>
        <ResponsiveMenuSeparator />
        <ResponsiveMenuItem
          variant="destructive"
          onClick={() => handleStatusAction('DISMISSED')}
          disabled={isStatusActionPending}
        >
          {t('jobs:actions.dismiss')}
        </ResponsiveMenuItem>
      </ResponsiveMenu>
    </div>
  );
}

function ScoreCell({ row }: { readonly row: Row<JobCorrelationResponse> }): JSX.Element {
  return <ScoreBadge score={row.original.fit_score} />;
}

function StatusCell({
  row,
  t,
}: {
  readonly row: Row<JobCorrelationResponse>;
  readonly t: TFunction<['jobs', 'common']>;
}): JSX.Element {
  return (
    <StatusBadge
      status={row.original.status}
      label={t(`jobs:status.${row.original.status}`)}
      themes={correlationStatusThemes}
    />
  );
}

function CreatedAtCell({ row }: { readonly row: Row<JobCorrelationResponse> }): JSX.Element {
  return (
    <span className="whitespace-nowrap text-muted-foreground text-sm">
      {formatShortDate(row.original.created_at)}
    </span>
  );
}

function TitleCell({ row }: { readonly row: Row<JobCorrelationResponse> }): JSX.Element {
  const { strengths } = parseMatchExplanation(row.original.score_breakdown?.ml_explanation);
  const topStrengths = strengths.slice(0, MAX_STRENGTH_BADGES);

  return (
    <div className="min-w-50 max-w-75">
      <Link
        to="/jobs/matches/$correlationId"
        params={{ correlationId: row.original.id }}
        className="line-clamp-1 font-medium hover:underline"
      >
        {row.original.listing_title}
      </Link>
      {row.original.listing_company ? (
        <div className="flex items-center gap-1 text-muted-foreground text-sm">
          <Building2 className="size-3" />
          <span className="line-clamp-1">{row.original.listing_company}</span>
        </div>
      ) : null}
      {topStrengths.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {withOccurrenceKeys(topStrengths, (s) => s).map(({ item: s, key }) => (
            <Badge
              key={key}
              variant="secondary"
              className="border-green-500/20 bg-green-500/10 px-1.5 py-0 text-green-700 text-xs dark:text-green-400"
            >
              {s}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function LocationCell({ row }: { readonly row: Row<JobCorrelationResponse> }): JSX.Element {
  if (row.original.listing_location) {
    return (
      <div className="flex items-center gap-1 text-muted-foreground text-sm">
        <MapPin className="size-3 shrink-0" />
        <span className="line-clamp-1">{row.original.listing_location}</span>
      </div>
    );
  }
  return <span className="text-muted-foreground">{EM_DASH}</span>;
}

function SelectHeaderCell({
  table,
  t,
}: HeaderContext<JobCorrelationResponse, unknown> & {
  readonly t: TFunction<['jobs', 'common']>;
}): JSX.Element {
  return <SelectAllHeader table={table} t={t} />;
}

export {
  ActionsCell,
  CreatedAtCell,
  LocationCell,
  RowSelectCell,
  ScoreCell,
  SelectHeaderCell,
  SortableColumnHeader,
  StatusCell,
  TitleCell,
};
