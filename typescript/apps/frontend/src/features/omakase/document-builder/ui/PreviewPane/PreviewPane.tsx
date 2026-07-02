/**
 * PreviewPane Component - Secure HTML Template Preview
 *
 * Security Layers:
 * 1. Server-side: Jinja2 sandboxed environment with strict limits
 * 2. CSP Headers: Restrict script sources and prevent XSS
 * 3. iframe Sandbox: Isolate content with minimal permissions
 * 4. Content Validation: Size limits and navigation monitoring
 * 5. Object URL Lifecycle: Proper cleanup to prevent memory leaks
 */

import { cn } from '@shared/lib/index.ts';

/** Granularity (px) for rounding container width to reduce unnecessary re-renders */
const CONTAINER_WIDTH_ROUND_STEP: number = 50;

import { PanelEmptyState, PanelErrorState } from '@shared/ui/index.ts';
import type { JSX } from 'react';
import { useResizeObserver } from '@/shared/lib/index.ts';
import { TemplateJsWarning } from '@/shared/ui/TemplateJsWarning.tsx';
import { usePreviewPane } from '../../lib/usePreviewPane.ts';
import { PreviewHeader } from './PreviewHeader.tsx';
import { PreviewRenderer } from './PreviewRenderer.tsx';

interface PreviewPaneProps {
  template?: string;
  data?: Record<string, unknown> | undefined;
  className?: string;
  datasetId?: string | undefined;
  templateId?: string | undefined;
  cachedHtmlData?: string | undefined;
  onHtmlGenerated?: (datasetId: string, htmlData: string) => void;
  onHtmlCleared?: (datasetId: string) => void;
  isFullscreen?: boolean;
  generatePreview?: () => void;
  showHeader?: boolean;
  isInDialog?: boolean;
  onClose?: () => void;
}

function ErrorDisplay({ error, onRetry }: { error: string; onRetry?: () => void }): JSX.Element {
  return <PanelErrorState error={error} onRetry={onRetry ? (): void => onRetry() : undefined} />;
}

function EmptyPreview({ onGenerate }: { onGenerate: () => void }): JSX.Element {
  const handleAction = (): void => {
    onGenerate();
  };

  return <PanelEmptyState variant="preview" onAction={handleAction} />;
}

function renderPreviewContent(
  preview: {
    error: string | null;
    clearError: () => void;
    hasPreview: boolean;
    renderMethod: 'html' | 'image';
    htmlUrl: string | null;
    imageUrl: string | null;
  },
  onGenerate: () => void | Promise<void>,
  isFullscreen: boolean,
  isInDialog: boolean,
): JSX.Element {
  if (preview.error) {
    return <ErrorDisplay error={preview.error} onRetry={preview.clearError} />;
  }

  if (preview.hasPreview) {
    return (
      <PreviewRenderer
        htmlUrl={preview.renderMethod === 'html' ? preview.htmlUrl : null}
        imageUrl={preview.renderMethod === 'image' ? preview.imageUrl : null}
        isFullscreen={isFullscreen}
        isInDialog={isInDialog}
        className="h-full"
      />
    );
  }

  return <EmptyPreview onGenerate={onGenerate} />;
}

function PreviewPane({
  template = '',
  data = {},
  className = '',
  datasetId,
  templateId,
  cachedHtmlData,
  onHtmlGenerated,
  onHtmlCleared,
  isFullscreen = false,
  generatePreview: externalGeneratePreview,
  showHeader = true,
  isInDialog = false,
  onClose,
}: Readonly<PreviewPaneProps>): JSX.Element {
  const [containerRef, containerSize] = useResizeObserver<HTMLDivElement>();

  const preview = usePreviewPane({
    template,
    data,
    templateId,
    datasetId,
    cachedHtmlData,
    onHtmlGenerated,
    onHtmlCleared,
  });

  const actualGeneratePreview = externalGeneratePreview || preview.generatePreview;

  const headerContainerWidth = containerSize?.width
    ? Math.round(containerSize.width / CONTAINER_WIDTH_ROUND_STEP) * CONTAINER_WIDTH_ROUND_STEP
    : undefined;

  return (
    <div className={cn('flex h-full flex-col', className)}>
      {showHeader ? (
        <PreviewHeader
          isGenerating={preview.isGenerating}
          generatePreview={actualGeneratePreview}
          hasPreview={preview.hasPreview}
          onDownload={preview.downloadPdf}
          containerWidth={headerContainerWidth}
          isInDialog={isInDialog}
          onClose={onClose}
          template={template}
          data={data}
          datasetId={datasetId}
          templateId={templateId}
          cachedHtmlData={cachedHtmlData}
          onHtmlGenerated={onHtmlGenerated}
          onHtmlCleared={onHtmlCleared}
        />
      ) : null}

      <div ref={containerRef} className="min-h-0 flex-1 overflow-hidden">
        {renderPreviewContent(preview, actualGeneratePreview, isFullscreen, isInDialog)}
      </div>

      <TemplateJsWarning
        open={preview.jsWarning.showWarning}
        templateName={preview.jsWarning.templateName}
        templateVersion={preview.jsWarning.templateVersion}
        reason={preview.jsWarning.reason}
        onChoice={preview.jsWarning.handleJsChoice}
      />
    </div>
  );
}

export { PreviewPane };
