import { useProfiles } from '@features/profile-management/index.ts';
import { Link } from '@tanstack/react-router';
import { User } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { ProfileResponse } from '@/shared/api';
import { extractErrorReason } from '@/shared/lib';
import { cn } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { EmptyState } from '@/shared/ui/empty-state.tsx';
import { PanelErrorState } from '@/shared/ui/panel-error-state.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';

interface ProfileStepProps {
  readonly selectedId: string | null;
  readonly onSelect: (profileId: string) => void;
}

function ProfileStepSkeleton(): JSX.Element {
  const { t } = useTranslation('documents');
  return (
    <output className="block space-y-3" aria-label={t('wizard.a11y.loading')} aria-busy="true">
      {Array.from({ length: 3 }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: Static skeleton placeholders never reorder
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-4 w-2/3" />
          </CardHeader>
        </Card>
      ))}
    </output>
  );
}

function ProfileCard({
  profile,
  isSelected,
  onSelect,
}: {
  readonly profile: ProfileResponse;
  readonly isSelected: boolean;
  readonly onSelect: (id: string) => void;
}): JSX.Element {
  const { t } = useTranslation('documents');

  return (
    <Card
      role="radio"
      aria-checked={isSelected}
      tabIndex={0}
      className={cn(
        'cursor-pointer transition-colors hover:border-primary/50',
        isSelected && 'border-primary ring-2 ring-primary/20',
      )}
      onClick={() => onSelect(profile.id)}
      onKeyDown={(e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(profile.id);
        }
      }}
    >
      <CardHeader>
        <CardTitle className="text-base">{profile.pref_name}</CardTitle>
        {profile.search_keywords.length > 0 && (
          <CardDescription>
            {t('wizard.profile.keywords')} {profile.search_keywords.join(', ')}
          </CardDescription>
        )}
      </CardHeader>
    </Card>
  );
}

function ProfileStep({ selectedId, onSelect }: ProfileStepProps): JSX.Element {
  const { t } = useTranslation('documents');
  const { data, isLoading, isError, error, refetch } = useProfiles();

  const profiles = data?.items ?? [];

  if (isLoading) {
    return <ProfileStepSkeleton />;
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

  if (profiles.length === 0) {
    return (
      <EmptyState
        icon={User}
        title={t('wizard.profile.emptyTitle')}
        description={t('wizard.profile.emptyDescription')}
        size="sm"
        variant="card"
      >
        <Button asChild={true} size="sm">
          <Link to="/profiles">{t('wizard.profile.emptyAction')}</Link>
        </Button>
      </EmptyState>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-semibold text-lg">{t('wizard.profile.heading')}</h2>
        <p className="text-muted-foreground text-sm">{t('wizard.profile.description')}</p>
      </div>
      <div className="space-y-3" role="radiogroup" aria-label={t('wizard.steps.profile')}>
        {profiles.map((profile) => (
          <ProfileCard
            key={profile.id}
            profile={profile}
            isSelected={selectedId === profile.id}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}

export { ProfileStep };
