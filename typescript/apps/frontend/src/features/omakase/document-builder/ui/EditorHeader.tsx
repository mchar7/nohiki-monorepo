import { Download, FileText } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui/button.tsx';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/shared/ui/tooltip.tsx';

interface EditorHeaderProps {
  readonly currentDatasetName?: string | undefined;
  readonly formIsDirty: boolean;
  readonly onCreateDataset: () => void;
  readonly onDownloadPdf: () => void;
  readonly onImport: () => void;
  readonly onExport: () => void;
  readonly isDownloading: boolean;
}

export function EditorHeader({
  currentDatasetName,
  formIsDirty,
  onCreateDataset,
  onDownloadPdf,
  onImport,
  onExport,
  isDownloading,
}: EditorHeaderProps): JSX.Element {
  const { t } = useTranslation('omakase.editor');

  return (
    <header className="border-b bg-background">
      <div className="flex h-14 items-center justify-between px-4 lg:px-6">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10">
            <FileText className="size-5 text-primary" />
          </div>
          <div className="flex items-center gap-2">
            <h1 className="font-semibold text-lg">{currentDatasetName ?? t('title')}</h1>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild={true}>
                  {formIsDirty ? (
                    <div className="h-2 w-2 animate-pulse cursor-help rounded-full bg-amber-500" />
                  ) : (
                    <div className="h-2 w-2 cursor-help rounded-full bg-green-500" />
                  )}
                </TooltipTrigger>
                <TooltipContent>
                  <p>{formIsDirty ? t('form.saving') : t('form.autoSaved')}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={onImport}>
            {t('import.title')}
          </Button>
          <Button variant="outline" size="sm" onClick={onExport}>
            {t('export.title')}
          </Button>

          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild={true}>
                <Button
                  variant="outline"
                  size="sm"
                  className="aspect-square px-2"
                  onClick={onDownloadPdf}
                  disabled={isDownloading}
                  aria-label={t('actions.downloadPdf')}
                >
                  <Download className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{t('actions.downloadPdf')}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <Button size="sm" onClick={onCreateDataset}>
            {t('sidebar.newDocument')}
          </Button>
        </div>
      </div>
    </header>
  );
}
