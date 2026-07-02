import { PanelHeader } from '@shared/ui/index.ts';

/** Width threshold (px) below which the header switches to compact mode */
const COMPACT_MODE_THRESHOLD_PX: number = 600;

import { Download, Maximize2, RefreshCw, X } from 'lucide-react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FullscreenPreviewDialog } from '../FullscreenPreviewDialog.tsx';
import { ConditionalTooltipButton } from './ConditionalTooltipButton.tsx';

interface PreviewHeaderProps {
  isGenerating: boolean;
  generatePreview: () => void;
  hasPreview: boolean;
  onDownload: () => void;
  containerWidth?: number | undefined;
  isInDialog?: boolean | undefined;
  onClose?: (() => void) | undefined;
  // Props needed for fullscreen dialog
  template?: string | undefined;
  data?: Record<string, unknown> | undefined;
  datasetId?: string | undefined;
  templateId?: string | undefined;
  cachedHtmlData?: string | undefined;
  onHtmlGenerated?: ((datasetId: string, htmlData: string) => void) | undefined;
  onHtmlCleared?: ((datasetId: string) => void) | undefined;
}

interface PreviewActionsProps {
  isGenerating: boolean;
  generatePreview: () => void;
  hasPreview: boolean;
  onDownload: () => void;
  isCompact: boolean;
  showTooltips: boolean;
  isInDialog: boolean;
  onClose?: (() => void) | undefined;
  onFullscreenClick: () => void;
}

/**
 * Renders the action buttons for the preview header toolbar.
 *
 * Extracted from PreviewHeader to keep cognitive complexity within bounds.
 */
function PreviewActions({
  isGenerating,
  generatePreview,
  hasPreview,
  onDownload,
  isCompact,
  showTooltips,
  isInDialog,
  onClose,
  onFullscreenClick,
}: Readonly<PreviewActionsProps>): JSX.Element {
  const { t } = useTranslation('omakase.preview');

  return (
    <>
      <ConditionalTooltipButton
        showTooltip={showTooltips}
        tooltip={t('tooltips.generatePreview')}
        onClick={generatePreview}
        disabled={isGenerating}
        size="sm"
        className="gap-2"
      >
        {isGenerating ? (
          <RefreshCw className="size-4 animate-spin" />
        ) : (
          <RefreshCw className="size-4" />
        )}
        {!isCompact && <span>{t('header.generate')}</span>}
      </ConditionalTooltipButton>
      {hasPreview ? (
        <>
          {isInDialog ? null : (
            <ConditionalTooltipButton
              showTooltip={showTooltips}
              tooltip={t('tooltips.enterFullscreen')}
              onClick={onFullscreenClick}
              variant="outline"
              size="sm"
              className="gap-2"
            >
              <Maximize2 className="size-4" />
              {isCompact ? null : <span>{t('header.fullscreen')}</span>}
            </ConditionalTooltipButton>
          )}
          <ConditionalTooltipButton
            showTooltip={showTooltips}
            tooltip={t('tooltips.downloadPdf')}
            onClick={onDownload}
            variant="outline"
            size="sm"
            className="gap-2"
          >
            <Download className="size-4" />
            {isCompact ? null : <span>{t('header.download')}</span>}
          </ConditionalTooltipButton>
        </>
      ) : null}
      {isInDialog && onClose ? (
        <ConditionalTooltipButton
          showTooltip={showTooltips}
          tooltip={t('tooltips.closePreview')}
          onClick={onClose}
          variant="outline"
          size="sm"
          className="gap-2 border-red-300 text-red-600 hover:bg-red-50"
        >
          <X className="size-4" />
          {isCompact ? null : <span>{t('header.close')}</span>}
        </ConditionalTooltipButton>
      ) : null}
    </>
  );
}

/**
 * Preview header with action buttons.
 *
 */
export function PreviewHeader({
  isGenerating,
  generatePreview,
  hasPreview,
  onDownload,
  containerWidth,
  isInDialog = false,
  onClose,
  template,
  data,
  datasetId,
  templateId,
  cachedHtmlData,
  onHtmlGenerated,
  onHtmlCleared,
}: Readonly<PreviewHeaderProps>): JSX.Element {
  const { t } = useTranslation('omakase.preview');
  const [showFullscreenDialog, setShowFullscreenDialog] = useState(false);

  const isCompact = Boolean(containerWidth && containerWidth < COMPACT_MODE_THRESHOLD_PX);
  const showTooltips = isCompact && !isInDialog;

  const handleFullscreenClick = (): void => {
    setShowFullscreenDialog(true);
  };

  const actions = (
    <PreviewActions
      isGenerating={isGenerating}
      generatePreview={generatePreview}
      hasPreview={hasPreview}
      onDownload={onDownload}
      isCompact={isCompact}
      showTooltips={showTooltips}
      isInDialog={isInDialog}
      onClose={onClose}
      onFullscreenClick={handleFullscreenClick}
    />
  );

  return (
    <>
      <PanelHeader title={t('title')} actions={actions} compact={isInDialog} />
      <FullscreenPreviewDialog
        open={showFullscreenDialog}
        onOpenChange={setShowFullscreenDialog}
        template={template}
        data={data}
        datasetId={datasetId}
        templateId={templateId}
        cachedHtmlData={cachedHtmlData}
        onHtmlGenerated={onHtmlGenerated}
        onHtmlCleared={onHtmlCleared}
      />
    </>
  );
}
