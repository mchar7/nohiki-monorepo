import { useMyCorrelations } from '@features/job-matching/index.ts';
import { Briefcase, SkipForward } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { JobCorrelationResponse } from '@/shared/api';
import { extractErrorReason } from '@/shared/lib';
import { cn } from '@/shared/lib/index.ts';
import { Card, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { EmptyState } from '@/shared/ui/empty-state.tsx';
import { PanelErrorState } from '@/shared/ui/panel-error-state.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';

interface MatchStepProps {
  readonly selectedId: string | null;
  readonly profileId: string | null;
  readonly onSelect: (matchId: string | null) => void;
}

function MatchStepSkeleton(): JSX.Element {
  const { t } = useTranslation('documents');
  return (
    <output className="block space-y-3" aria-label={t('wizard.a11y.loading')} aria-busy="true">
      {Array.from({ length: 3 }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: Static skeleton placeholders never reorder
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="h-4 w-1/3" />
          </CardHeader>
        </Card>
      ))}
    </output>
  );
}

function SkipMatchCard({
  isSelected,
  onSelect,
}: {
  readonly isSelected: boolean;
  readonly onSelect: () => void;
}): JSX.Element {
  const { t } = useTranslation('documents');

  return (
    <Card
      role="radio"
      aria-checked={isSelected}
      tabIndex={0}
      className={cn(
        'cursor-pointer border-dashed transition-colors hover:border-primary/50',
        isSelected && 'border-primary ring-2 ring-primary/20',
      )}
      onClick={onSelect}
      onKeyDown={(e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <CardHeader className="flex-row items-center gap-3">
        <SkipForward className="size-5 text-muted-foreground" aria-hidden="true" />
        <CardTitle className="text-base">{t('wizard.match.skip')}</CardTitle>
      </CardHeader>
    </Card>
  );
}

function CorrelationCard({
  correlation,
  isSelected,
  onSelect,
}: {
  readonly correlation: JobCorrelationResponse;
  readonly isSelected: boolean;
  readonly onSelect: (id: string) => void;
}): JSX.Element {
  const { t } = useTranslation('documents');
  const score = Math.round(correlation.fit_score);

  return (
    <Card
      role="radio"
      aria-checked={isSelected}
      tabIndex={0}
      className={cn(
        'cursor-pointer transition-colors hover:border-primary/50',
        isSelected && 'border-primary ring-2 ring-primary/20',
      )}
      onClick={() => onSelect(correlation.id)}
      onKeyDown={(e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(correlation.id);
        }
      }}
    >
      <CardHeader>
        <CardTitle className="text-base">{correlation.listing_title}</CardTitle>
        <CardDescription>
          {correlation.listing_company
            ? `${correlation.listing_company} - ${t('wizard.match.score', { score })}`
            : t('wizard.match.score', { score })}
        </CardDescription>
      </CardHeader>
    </Card>
  );
}

function MatchStep({ selectedId, profileId, onSelect }: MatchStepProps): JSX.Element {
  const { t } = useTranslation('documents');
  const { data, isLoading, isError, error, refetch } = useMyCorrelations({
    prefId: profileId ?? undefined,
    pageSize: 50,
  });

  const correlations = data?.items ?? [];

  if (isLoading) {
    return <MatchStepSkeleton />;
  }
  if (isError) {
    const reason = extractErrorReason(error);
    return (
      <PanelErrorState
        title={t('wizard.errorTitle')}
        error={reason ?? t('wizard.errorTitle')}
        onRetry={() => {
          refetch().then(() => undefined);
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-semibold text-lg">{t('wizard.match.heading')}</h2>
        <p className="text-muted-foreground text-sm">{t('wizard.match.description')}</p>
      </div>
      <div className="space-y-3" role="radiogroup" aria-label={t('wizard.steps.match')}>
        <SkipMatchCard isSelected={selectedId === null} onSelect={() => onSelect(null)} />
        {correlations.length === 0 ? (
          <EmptyState
            icon={Briefcase}
            title={t('wizard.match.emptyTitle')}
            description={t('wizard.match.emptyDescription')}
            size="sm"
            variant="card"
          />
        ) : (
          correlations.map((correlation) => (
            <CorrelationCard
              key={correlation.id}
              correlation={correlation}
              isSelected={selectedId === correlation.id}
              onSelect={(id: string) => onSelect(id)}
            />
          ))
        )}
      </div>
    </div>
  );
}

export { MatchStep };
