import { Button } from '@shared/ui/index.ts';
import type { JSX } from 'react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TemplateResponse } from '@/shared/api';
import { logger } from '@/shared/lib/index.ts';
import { useDownloadDocument } from '../../api/index.ts';
import { generatePdfFilename } from '../../lib/filename.ts';
import type { Dataset } from '../../model/index.ts';

interface PdfDownloadButtonProps {
  readonly dataset: Dataset;
  readonly template: TemplateResponse;
  readonly className?: string;
  readonly children?: React.ReactNode;
}

export function PdfDownloadButton({
  dataset,
  template,
  className = '',
  children,
}: PdfDownloadButtonProps): JSX.Element {
  const { t } = useTranslation('omakase.preview');
  const { t: tCommon } = useTranslation('common');
  const [progress, setProgress] = useState(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const pdfGeneration = useDownloadDocument();

  const handleDownload = async (): Promise<void> => {
    abortControllerRef.current = new AbortController();
    setProgress(0);

    try {
      const filename = generatePdfFilename(
        dataset.name,
        template.display_name || tCommon('unavailable'),
      );

      await pdfGeneration.mutateAsync({
        template_version_id: template.id,
        data: dataset.data,
        output_format: 'pdf',
        filename,
      });

      setProgress(0);
    } catch (error) {
      logger.error('PDF generation failed', error, { component: 'PdfDownloadButton' });
      setProgress(0);
    }
  };

  const handleCancel = (): void => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setProgress(0);
    }
  };

  const isLoading = pdfGeneration.isPending;
  const hasError = pdfGeneration.isError;

  return (
    <div className="relative">
      {isLoading ? (
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="size-4 animate-spin rounded-full border-2 border-muted border-t-primary" />
            <span className="font-medium text-sm">
              {progress > 0
                ? `${t('download.downloading')} ${Math.round(progress)}%`
                : t('download.downloading')}
            </span>
          </div>
          <Button
            type="button"
            onClick={handleCancel}
            variant="ghost"
            size="sm"
            className="text-destructive hover:bg-destructive/10 hover:text-destructive"
          >
            {tCommon('actions.cancel')}
          </Button>
        </div>
      ) : (
        <Button onClick={handleDownload} disabled={pdfGeneration.isPending} className={className}>
          {children ?? t('actions.download')}
        </Button>
      )}

      {hasError ? (
        <div className="absolute top-full left-0 mt-2 max-w-xs rounded-md border border-destructive/20 bg-destructive/10 p-2 text-destructive text-sm">
          {pdfGeneration.error?.message ?? t('download.error')}
        </div>
      ) : null}
    </div>
  );
}
