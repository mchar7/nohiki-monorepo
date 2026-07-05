import { useTemplateFamilies } from '@features/omakase/document-builder';
import { Layout } from 'lucide-react';
import { type JSX, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import type { TemplateFamilyResponse } from '@/shared/api';
import { extractErrorReason } from '@/shared/lib';
import { cn } from '@/shared/lib/index.ts';
import { Card, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { EmptyState } from '@/shared/ui/empty-state.tsx';
import { PanelErrorState } from '@/shared/ui/panel-error-state.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import type { DocType } from '../../lib/wizardReducer.ts';

interface TemplateStepProps {
  readonly selectedId: string | null;
  readonly docType: DocType | null;
  readonly preselectedTemplateId: string | undefined;
  readonly onSelect: (templateId: string) => void;
}

function TemplateStepSkeleton(): JSX.Element {
  const { t } = useTranslation('documents');
  return (
    <output
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      aria-label={t('wizard.a11y.loading')}
      aria-busy="true"
    >
      {Array.from({ length: 6 }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: Static skeleton placeholders never reorder
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-full" />
          </CardHeader>
        </Card>
      ))}
    </output>
  );
}

function TemplateCard({
  family,
  isSelected,
  onSelect,
}: {
  readonly family: TemplateFamilyResponse;
  readonly isSelected: boolean;
  readonly onSelect: (id: string) => void;
}): JSX.Element | null {
  const { t } = useTranslation(['documents', 'common']);
  const version = family.latest_version;
  if (!version) {
    return null;
  }
  const displayName = family.display_name || t('common:unavailable');

  return (
    <Card
      role="radio"
      aria-checked={isSelected}
      tabIndex={0}
      className={cn(
        'cursor-pointer transition-colors hover:border-primary/50',
        isSelected && 'border-primary ring-2 ring-primary/20',
      )}
      onClick={() => onSelect(version.id)}
      onKeyDown={(e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(version.id);
        }
      }}
    >
      <CardHeader>
        <CardTitle className="text-base">{displayName}</CardTitle>
        <CardDescription>
          {family.description ?? t('wizard.template.version', { version: version.version })}
        </CardDescription>
      </CardHeader>
    </Card>
  );
}

function TemplateStepErrorState({
  error,
  title,
  onRetry,
}: {
  readonly error: string;
  readonly title: string;
  readonly onRetry: () => void;
}): JSX.Element {
  return <PanelErrorState title={title} error={error} onRetry={onRetry} />;
}

function TemplateStepEmptyState({
  title,
  description,
}: {
  readonly title: string;
  readonly description: string;
}): JSX.Element {
  return (
    <EmptyState icon={Layout} title={title} description={description} size="sm" variant="card" />
  );
}

function TemplateStepContent({
  families,
  selectedId,
  onSelect,
  heading,
  description,
  ariaLabel,
}: {
  readonly families: readonly TemplateFamilyResponse[];
  readonly selectedId: string | null;
  readonly onSelect: (id: string) => void;
  readonly heading: string;
  readonly description: string;
  readonly ariaLabel: string;
}): JSX.Element {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-semibold text-lg">{heading}</h2>
        <p className="text-muted-foreground text-sm">{description}</p>
      </div>
      <div
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        role="radiogroup"
        aria-label={ariaLabel}
      >
        {families.map((family) => (
          <TemplateCard
            key={family.id}
            family={family}
            isSelected={selectedId === family.latest_version?.id}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}

function TemplateStepView({
  families,
  isLoading,
  isError,
  error,
  refetch,
  selectedId,
  onSelect,
  heading,
  description,
  ariaLabel,
  errorTitle,
  emptyTitle,
  emptyDescription,
}: {
  readonly families: readonly TemplateFamilyResponse[];
  readonly isLoading: boolean;
  readonly isError: boolean;
  readonly error: unknown;
  readonly refetch: () => Promise<unknown>;
  readonly selectedId: string | null;
  readonly onSelect: (id: string) => void;
  readonly heading: string;
  readonly description: string;
  readonly ariaLabel: string;
  readonly errorTitle: string;
  readonly emptyTitle: string;
  readonly emptyDescription: string;
}): JSX.Element {
  if (isLoading) {
    return <TemplateStepSkeleton />;
  }
  if (isError) {
    const reason = extractErrorReason(error);
    return (
      <TemplateStepErrorState
        title={errorTitle}
        error={reason ?? errorTitle}
        onRetry={async () => {
          await refetch();
        }}
      />
    );
  }
  if (families.length === 0) {
    return <TemplateStepEmptyState title={emptyTitle} description={emptyDescription} />;
  }
  return (
    <TemplateStepContent
      families={families}
      selectedId={selectedId}
      onSelect={onSelect}
      heading={heading}
      description={description}
      ariaLabel={ariaLabel}
    />
  );
}

function TemplateStep({
  selectedId,
  docType,
  preselectedTemplateId,
  onSelect,
}: TemplateStepProps): JSX.Element {
  const { t } = useTranslation('documents');
  const { data, isLoading, isError, error, refetch } = useTemplateFamilies({
    namespace: docType ?? undefined,
    page: 1,
    page_size: 100,
  });
  const families = data?.items ?? [];

  useEffect(() => {
    if (preselectedTemplateId && !selectedId) {
      const versionId = findVersionId(families, preselectedTemplateId);
      if (versionId) {
        onSelect(versionId);
      }
    }
  }, [preselectedTemplateId, selectedId, families, onSelect]);

  return (
    <TemplateStepView
      families={families}
      isLoading={isLoading}
      isError={isError}
      error={error}
      refetch={refetch}
      selectedId={selectedId}
      onSelect={onSelect}
      heading={t('wizard.template.heading')}
      description={t('wizard.template.description')}
      ariaLabel={t('wizard.steps.template')}
      errorTitle={t('wizard.errorTitle')}
      emptyTitle={t('wizard.template.emptyTitle')}
      emptyDescription={t('wizard.template.emptyDescription')}
    />
  );
}

/** Resolves a template family ID or version ID to a concrete version ID. */
function findVersionId(
  families: ReadonlyArray<{ id: string; latest_version?: { id: string } | null }>,
  templateId: string,
): string | null {
  for (const family of families) {
    if (family.latest_version?.id === templateId) {
      return templateId;
    }
  }
  for (const family of families) {
    if (family.id === templateId && family.latest_version) {
      return family.latest_version.id;
    }
  }
  return null;
}

export { TemplateStep };
