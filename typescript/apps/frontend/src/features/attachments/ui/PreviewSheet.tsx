import { Download, FileWarning } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { AttachmentResponse } from '@/shared/api';
import { formatFileSize, getSafeExternalUrl } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/shared/ui/sheet.tsx';

interface PreviewSheetProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly attachment: AttachmentResponse;
}

function PdfViewer({ url }: { readonly url: string }): JSX.Element {
  const { t } = useTranslation('attachments');
  return (
    <object data={url} type="application/pdf" title="PDF" className="h-full w-full border-0">
      <p>{t('preview.notAvailable')}</p>
    </object>
  );
}

function NonPdfFallback({
  downloadUrl,
}: {
  readonly downloadUrl: string | null | undefined;
}): JSX.Element {
  const { t } = useTranslation('attachments');

  const handleDownload = (): void => {
    if (downloadUrl) {
      window.open(downloadUrl, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
      <FileWarning className="size-12 text-muted-foreground" aria-hidden="true" />
      <p className="text-center text-muted-foreground">{t('preview.notAvailable')}</p>
      {downloadUrl ? (
        <Button variant="outline" onClick={handleDownload}>
          <Download className="mr-2 size-4" aria-hidden="true" />
          {t('preview.download')}
        </Button>
      ) : null}
    </div>
  );
}

function ExpiredError(): JSX.Element {
  const { t } = useTranslation('attachments');

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
      <FileWarning className="size-12 text-destructive" aria-hidden="true" />
      <p className="text-center text-muted-foreground">{t('preview.errorExpired')}</p>
    </div>
  );
}

function PreviewSheet({ open, onOpenChange, attachment }: PreviewSheetProps): JSX.Element {
  const { t } = useTranslation('attachments');
  const { size, unit } = formatFileSize(attachment.file_size);
  const isPdf = attachment.content_type === 'application/pdf';
  const downloadUrl = getSafeExternalUrl(attachment.download_url);

  const handleDownload = (): void => {
    if (downloadUrl) {
      window.open(downloadUrl, '_blank', 'noopener,noreferrer');
    }
  };

  const handleOpenChange = (nextOpen: boolean): void => {
    onOpenChange(nextOpen);
  };

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col p-0 sm:max-w-2xl"
        hideCloseButton={false}
      >
        <SheetHeader className="flex-row items-center justify-between gap-2 border-b px-4 py-3 pr-12">
          <div className="min-w-0 flex-1">
            <SheetTitle className="truncate text-sm">{attachment.filename}</SheetTitle>
            <SheetDescription className="text-xs">
              {`${t('preview.description', { filename: attachment.filename })}—${t(`size.${unit}` as `size.${'bytes' | 'kb' | 'mb'}`, { size })}`}
            </SheetDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={!downloadUrl}
            onClick={handleDownload}
            aria-label={t('preview.download')}
          >
            <Download className="mr-1.5 size-3.5" aria-hidden="true" />
            {t('actions.download')}
          </Button>
        </SheetHeader>

        <div className="flex flex-1 overflow-hidden" data-testid="preview-body">
          {isPdf && downloadUrl ? <PdfViewer url={downloadUrl} /> : null}
          {isPdf && !downloadUrl ? <ExpiredError /> : null}
          {isPdf ? null : <NonPdfFallback downloadUrl={downloadUrl} />}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export { PreviewSheet };
