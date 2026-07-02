import { Link } from '@tanstack/react-router';
import {
  ArrowLeft,
  Building2,
  Calendar,
  ClipboardCopy,
  ExternalLink,
  MapPin,
  X,
} from 'lucide-react';
import type { JSX, MouseEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { JobCorrelationResponse } from '@/shared/api';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { formatLongDate, getSafeExternalUrl, useCopyToClipboard } from '@/shared/lib';
import { ActionBar } from '@/shared/ui/action-bar.tsx';
import type { OverflowAction } from '@/shared/ui/action-bar.types.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { SaveToggle } from '@/shared/ui/save-toggle.tsx';
import { ScoreBadge } from '@/shared/ui/score-badge.tsx';
import { Separator } from '@/shared/ui/separator.tsx';
import { ShareButton } from '@/shared/ui/share-button.tsx';
import { StatusBadge } from '@/shared/ui/status-badge.tsx';
import { correlationStatusThemes } from '@/shared/ui/status-badge-model.ts';

interface MatchDetailViewProps {
  readonly correlation: JobCorrelationResponse;
  readonly onSave: () => void;
  readonly onApply: () => void;
  readonly onDismiss: () => void;
  readonly isSaving: boolean;
  readonly tailoredDocumentAction?: ReactNode;
}

function MatchDetailView({
  correlation,
  onSave,
  onApply,
  onDismiss,
  isSaving,
  tailoredDocumentAction,
}: MatchDetailViewProps): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);
  const [copyJd] = useCopyToClipboard();
  const listingUrl = getSafeExternalUrl(correlation.listing_url);

  const handleCopyJd = (): void => {
    copyJd(correlation.listing_url).catch(() => undefined);
    toast.success(t('card.copiedToClipboard'));
  };
  const handleApplyClick = (event: MouseEvent<HTMLAnchorElement>): void => {
    if (isSaving) {
      event.preventDefault();
      return;
    }
    onApply();
  };

  const overflowActions: OverflowAction[] = [
    {
      label: t('actions.copyJobDescription'),
      icon: <ClipboardCopy className="size-4" aria-hidden="true" />,
      onClick: handleCopyJd,
    },
    ...(isSaving
      ? []
      : [
          {
            label: t('actions.dismiss'),
            icon: <X className="size-4" aria-hidden="true" />,
            onClick: onDismiss,
          },
        ]),
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <Link to={ROUTE_PATHS.JOBS.MATCHES}>
              <Button variant="ghost" size="icon" className="-ml-2">
                <ArrowLeft className="size-4" aria-hidden="true" />
                <span className="sr-only">{t('common:actions.goBack')}</span>
              </Button>
            </Link>
            <div className="space-y-1">
              <CardTitle className="text-xl">{correlation.listing_title}</CardTitle>
              {correlation.listing_company ? (
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <Building2 className="size-4" aria-hidden="true" />
                  <span>{correlation.listing_company}</span>
                </div>
              ) : null}
            </div>
          </div>
          <ScoreBadge score={correlation.fit_score} className="px-3 py-1 text-lg" />
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-4 text-muted-foreground text-sm">
          {correlation.listing_location ? (
            <div className="flex items-center gap-1.5">
              <MapPin className="size-4" aria-hidden="true" />
              <span>{correlation.listing_location}</span>
            </div>
          ) : null}
          <div className="flex items-center gap-1.5">
            <Calendar className="size-4" aria-hidden="true" />
            <span>{`${t('match.matchedAt')}: ${formatLongDate(correlation.created_at)}`}</span>
          </div>
          <StatusBadge
            status={correlation.status}
            label={t(`status.${correlation.status}`)}
            themes={correlationStatusThemes}
          />
        </div>

        <Separator />

        <ActionBar
          primaryAction={
            listingUrl ? (
              <Button asChild={true}>
                <a
                  href={listingUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-disabled={isSaving}
                  onClick={handleApplyClick}
                >
                  <ExternalLink className="mr-2 size-4" aria-hidden="true" />
                  {t('actions.applyExternal')}
                </a>
              </Button>
            ) : (
              <Button disabled={true}>
                <ExternalLink className="mr-2 size-4" aria-hidden="true" />
                {t('actions.applyExternal')}
              </Button>
            )
          }
          secondaryActions={[
            <SaveToggle
              key="save"
              isSaved={correlation.status === 'SAVED'}
              onToggle={onSave}
              disabled={isSaving}
            />,
            listingUrl ? <ShareButton key="share" url={listingUrl} /> : null,
          ]}
          overflowActions={overflowActions}
        />

        {tailoredDocumentAction}
      </CardContent>
    </Card>
  );
}

export { MatchDetailView };
