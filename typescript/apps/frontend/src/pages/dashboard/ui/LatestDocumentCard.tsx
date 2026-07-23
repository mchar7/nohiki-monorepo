import { Link } from '@tanstack/react-router';
import { Download, FileText, Loader2, PenTool } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { ROUTE_PATHS } from '@/shared/config';
import { getSafeGeneratedDocumentUrl } from '@/shared/lib';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import type { LatestDocumentCardProps } from './Dashboard.types.ts';

/** Returns a styled badge element for the given document processing status. */
function StatusBadge({ status }: { readonly status: string }): JSX.Element {
  const { t } = useTranslation('dashboard');

  switch (status) {
    case 'completed':
      return (
        <Badge className="border-transparent bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
          {t('highlights.latestDocument.statusReady')}
        </Badge>
      );
    case 'generating':
    case 'pending':
      return (
        <Badge className="border-transparent bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400">
          <Loader2 className="size-3 animate-spin" />
          {t('highlights.latestDocument.statusGenerating')}
        </Badge>
      );
    case 'failed':
      return <Badge variant="destructive">{t('highlights.latestDocument.statusFailed')}</Badge>;
    default:
      return (
        <Badge variant="secondary">
          {t('highlights.latestDocument.status.unknown', { status })}
        </Badge>
      );
  }
}

function LatestDocumentEmptyState(): JSX.Element {
  const { t } = useTranslation('dashboard');

  return (
    <CardContent>
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-muted">
          <PenTool className="size-6 text-muted-foreground" />
        </div>
        <p className="font-medium text-muted-foreground">
          {t('highlights.latestDocument.emptyTitle')}
        </p>
        <p className="mt-1 text-muted-foreground/70 text-sm">
          {t('highlights.latestDocument.emptyDescription')}
        </p>
        <Button asChild={true} className="mt-4" size="sm">
          <Link to={ROUTE_PATHS.DOCUMENTS.LIST}>
            {t('highlights.latestDocument.goToDocuments')}
          </Link>
        </Button>
      </div>
    </CardContent>
  );
}

function LatestDocumentCard({ document }: LatestDocumentCardProps): JSX.Element {
  const { t } = useTranslation('dashboard');
  const downloadUrl = getSafeGeneratedDocumentUrl(document?.download_url, window.location.origin);

  return (
    <section aria-label={t('highlights.latestDocument.ariaLabel')}>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <div className="flex size-7 items-center justify-center rounded-md bg-primary/10">
              <FileText className="size-4 text-primary" />
            </div>
            {t('highlights.latestDocument.title')}
          </CardTitle>
        </CardHeader>
        {document ? (
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <StatusBadge status={document.status} />
              {downloadUrl ? (
                <Button variant="ghost" size="sm" asChild={true}>
                  <a href={downloadUrl} download={true} className="gap-1">
                    <Download className="size-4" />
                    {t('highlights.latestDocument.downloadPdf')}
                  </a>
                </Button>
              ) : null}
            </div>
            {document.status === 'generating' || document.status === 'pending' ? (
              <p className="text-muted-foreground/70 text-xs">
                {t('highlights.latestDocument.generatingHint')}
              </p>
            ) : null}
          </CardContent>
        ) : (
          <LatestDocumentEmptyState />
        )}
      </Card>
    </section>
  );
}

export { LatestDocumentCard };
