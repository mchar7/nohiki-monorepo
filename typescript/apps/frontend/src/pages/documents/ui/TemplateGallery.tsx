import { FileCode2, RefreshCcw, Search } from 'lucide-react';
import { type ChangeEvent, type JSX, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useTemplateFamilies } from '@/features/omakase/document-builder';
import type { TemplateFamilyResponse } from '@/shared/api';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Skeleton } from '@/shared/ui/skeleton';
import { TemplateCard } from './TemplateCard';

const SKELETON_COUNT = 6;
const SKELETON_KEYS: string[] = Array.from(
  { length: SKELETON_COUNT },
  (_, i) => `skeleton-${String(i)}`,
);

function LoadingSkeleton(): JSX.Element {
  return (
    <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {SKELETON_KEYS.map((key) => (
        <Skeleton key={key} className="h-48 w-full rounded-xl" />
      ))}
    </div>
  );
}

function EmptyState({
  searchQuery,
  t,
}: {
  searchQuery: string;
  t: (key: string) => string;
}): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border bg-muted/20 py-24 text-center">
      <div className="mb-4 rounded-full bg-muted p-4">
        <FileCode2 className="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 className="font-semibold text-lg">{t('templates.gallery.empty')}</h3>
      <p className="mt-2 max-w-sm text-muted-foreground">
        {searchQuery ? t('templates.gallery.emptyDescription') : t('templates.gallery.noTemplates')}
      </p>
    </div>
  );
}

function ErrorState({
  t,
  onRetry,
}: {
  t: (key: string) => string;
  onRetry: () => void;
}): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center space-y-4 py-12 text-center">
      <p className="font-medium text-destructive">{t('templates.gallery.error')}</p>
      <Button variant="outline" onClick={onRetry} className="gap-2">
        <RefreshCcw className="h-4 w-4" />
        {t('templates.gallery.retry')}
      </Button>
    </div>
  );
}

function TemplateGrid({ templates }: { templates: TemplateFamilyResponse[] }): JSX.Element {
  return (
    <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {templates.map((template) => (
        <TemplateCard key={template.id} template={template} />
      ))}
    </div>
  );
}

function filterTemplates(
  templates: TemplateFamilyResponse[],
  query: string,
): TemplateFamilyResponse[] {
  if (!query.trim()) {
    return templates;
  }
  const lowerQuery = query.toLowerCase();
  return templates.filter(
    (template) =>
      template.display_name?.toLowerCase().includes(lowerQuery) ||
      template.description?.toLowerCase().includes(lowerQuery) ||
      template.namespace.toLowerCase().includes(lowerQuery),
  );
}

export function TemplateGallery(): JSX.Element {
  const { t } = useTranslation('documents');
  const [searchQuery, setSearchQuery] = useState('');

  const { data, isLoading, error, refetch } = useTemplateFamilies({
    page: 1,
    page_size: 100,
  });

  const filteredTemplates = filterTemplates(data?.items ?? [], searchQuery);

  const handleSearchChange = (e: ChangeEvent<HTMLInputElement>): void => {
    setSearchQuery(e.target.value);
  };

  const handleRetry = (): void => {
    refetch().catch(() => undefined);
  };

  if (error) {
    return <ErrorState t={t} onRetry={handleRetry} />;
  }

  const hasResults = !isLoading && filteredTemplates.length > 0;
  const isEmpty = !isLoading && filteredTemplates.length === 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <h1 className="font-bold text-3xl tracking-tight">{t('templates.gallery.title')}</h1>
        <div className="relative w-full sm:w-72">
          <Search className="absolute top-2.5 left-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            type="search"
            placeholder={t('templates.gallery.search')}
            className="w-full pl-9"
            value={searchQuery}
            onChange={handleSearchChange}
            aria-label={t('templates.gallery.search')}
          />
        </div>
      </div>

      {isLoading ? <LoadingSkeleton /> : null}
      {isEmpty ? <EmptyState searchQuery={searchQuery} t={t} /> : null}
      {hasResults ? <TemplateGrid templates={filteredTemplates} /> : null}
    </div>
  );
}
