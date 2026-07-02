import { Button, Dialog, DialogContent, DialogHeader, DialogTitle } from '@shared/ui/index.ts';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { useResizeObserver } from '@/shared/lib/index.ts';
import { TemplateJsWarning } from '@/shared/ui/TemplateJsWarning.tsx';
import { useFullscreenPreviewDialog } from '../lib/useFullscreenPreviewDialog.ts';
import { PreviewRenderer } from './PreviewPane/PreviewRenderer.tsx';

interface FullscreenPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  template?: string | undefined;
  data?: Record<string, unknown> | undefined;
  templateId?: string | undefined;
  datasetId?: string | undefined;
  cachedHtmlData?: string | undefined;
  onHtmlGenerated?: ((datasetId: string, htmlData: string) => void) | undefined;
  onHtmlCleared?: ((datasetId: string) => void) | undefined;
}

type RenderMethod = 'html' | 'image';

interface PreviewContentProps {
  readonly error: string | null;
  readonly hasPreview: boolean;
  readonly renderMethod: RenderMethod;
  readonly htmlUrl: string | null;
  readonly imageUrl: string | null;
  readonly onGenerate: () => void;
  readonly retryLabel: string;
  readonly noPreviewLabel: string;
  readonly generateLabel: string;
}

function PreviewContent({
  error,
  hasPreview,
  renderMethod,
  htmlUrl,
  imageUrl,
  onGenerate,
  retryLabel,
  noPreviewLabel,
  generateLabel,
}: PreviewContentProps): JSX.Element {
  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="space-y-2 text-center">
          <p className="text-red-600">{error}</p>
          <Button onClick={onGenerate} variant="outline" size="sm">
            {retryLabel}
          </Button>
        </div>
      </div>
    );
  }

  if (hasPreview) {
    return (
      <PreviewRenderer
        htmlUrl={renderMethod === 'html' ? htmlUrl : null}
        imageUrl={renderMethod === 'image' ? imageUrl : null}
        isFullscreen={false}
        isInDialog={true}
        className="h-full"
      />
    );
  }

  return (
    <div className="flex h-full items-center justify-center">
      <div className="space-y-2 text-center">
        <p className="text-muted-foreground">{noPreviewLabel}</p>
        <Button onClick={onGenerate} size="sm">
          {generateLabel}
        </Button>
      </div>
    </div>
  );
}

function FullscreenPreviewDialog({
  open,
  onOpenChange,
  template,
  data,
  templateId,
  datasetId,
  cachedHtmlData,
  onHtmlGenerated,
  onHtmlCleared,
}: FullscreenPreviewDialogProps): JSX.Element {
  const { t } = useTranslation('omakase.preview');
  const [containerRef] = useResizeObserver<HTMLDivElement>();

  const dialog = useFullscreenPreviewDialog({
    templateId,
    datasetId,
    cachedHtmlData,
    onHtmlGenerated,
    onHtmlCleared,
  });

  const handleJsDialogChoice = (method: RenderMethod, remember: boolean): void => {
    dialog.jsWarning.handleJsChoice(method, remember);
    dialog.setRenderMethod(method);
    dialog.handleGeneratePreview(template, data).catch(() => {
      // Error state is managed inside useFullscreenPreviewDialog via dialog.error
    });
  };

  const handleGeneratePreview = (): void => {
    dialog.handleGeneratePreview(template, data).catch(() => {
      // Error state is managed inside useFullscreenPreviewDialog via dialog.error
    });
  };

  const isLoading = dialog.isGeneratingPreview || dialog.isGeneratingImage;
  const hasPreview = Boolean(dialog.htmlUrl) || Boolean(dialog.imageUrl);

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        {/* a11y fix: aria-describedby={undefined} suppresses Radix warning about
           missing DialogDescription; fullscreen preview is self-describing via its content */}
        <DialogContent className="h-full w-full max-w-full gap-0 p-0" aria-describedby={undefined}>
          <DialogHeader className="border-b px-6 py-4">
            <div className="flex items-center justify-between">
              <DialogTitle>{t('fullscreen.title')}</DialogTitle>
              <div className="flex items-center gap-2">
                <Button onClick={handleGeneratePreview} disabled={isLoading} size="sm">
                  {isLoading ? t('states.generating') : t('actions.generate')}
                </Button>
              </div>
            </div>
          </DialogHeader>

          <div ref={containerRef} className="min-h-0 flex-1 overflow-hidden">
            <PreviewContent
              error={dialog.error}
              hasPreview={hasPreview}
              renderMethod={dialog.renderMethod}
              htmlUrl={dialog.htmlUrl}
              imageUrl={dialog.imageUrl}
              onGenerate={handleGeneratePreview}
              retryLabel={t('actions.retry')}
              noPreviewLabel={t('states.noPreview')}
              generateLabel={t('actions.generate')}
            />
          </div>
        </DialogContent>
      </Dialog>

      <TemplateJsWarning
        open={dialog.jsWarning.showWarning}
        templateName={dialog.jsWarning.templateName}
        templateVersion={dialog.jsWarning.templateVersion}
        reason={dialog.jsWarning.reason}
        onChoice={handleJsDialogChoice}
      />
    </>
  );
}

export { FullscreenPreviewDialog };
