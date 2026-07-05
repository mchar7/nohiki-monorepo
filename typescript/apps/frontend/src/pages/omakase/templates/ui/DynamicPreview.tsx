import { Eye } from 'lucide-react';
import type { JSX } from 'react';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useConnectivitySafe } from '@/shared/lib/contexts/index.ts';
import { ConnectionRequiredState } from '@/shared/ui/connection-required-state.tsx';
import { usePreviewImage } from '../lib/usePreviewImage.ts';
import type {
  PageSize,
  PreviewConfig,
  PreviewState,
  ScaleState,
  TemplateData,
} from '../model/index.ts';
import { PreviewImage } from './PreviewImage.tsx';
import { ScaleControls } from './ScaleControls.tsx';

interface DynamicPreviewProps {
  readonly pageSize: PageSize;
  readonly templateVersionId?: string | undefined;
  readonly templateData?: TemplateData | undefined;
  readonly title?: string | undefined;
  readonly config?: Partial<PreviewConfig> | undefined;
  readonly onError?: ((error: string) => void) | undefined;
  readonly className?: string | undefined;
  /** Hide the internal header (use when parent component provides its own header) */
  readonly hideHeader?: boolean | undefined;
  /** Hide the "Fit" button in scale controls (use when already in fullscreen mode) */
  readonly hideFitButton?: boolean | undefined;
}

interface PreviewHeaderProps {
  readonly displayTitle: string;
  readonly scale: ScaleState;
  readonly isGenerating: boolean;
  readonly disabled: boolean;
  readonly hideFitButton: boolean;
  readonly onZoomIn: () => void;
  readonly onZoomOut: () => void;
  readonly onSetScaleMode: (mode: ScaleState['mode']) => void;
}

function PreviewHeader({
  displayTitle,
  scale,
  isGenerating,
  disabled,
  hideFitButton,
  onZoomIn,
  onZoomOut,
  onSetScaleMode,
}: PreviewHeaderProps): JSX.Element {
  return (
    <div className="flex h-10 shrink-0 items-center justify-between border-b bg-muted/20 px-4">
      <div className="flex items-center gap-2">
        <Eye className="size-4 text-muted-foreground" />
        <span className="font-medium text-sm">{displayTitle}</span>
      </div>
      <ScaleControls
        scale={scale}
        onZoomIn={onZoomIn}
        onZoomOut={onZoomOut}
        onSetScaleMode={onSetScaleMode}
        disabled={isGenerating || disabled}
        hideFitButton={hideFitButton}
      />
    </div>
  );
}

interface PreviewContentProps {
  readonly isOfflineDisabled: boolean;
  readonly previewState: PreviewState;
  readonly updateContainerSize: (size: { width: number; height: number }) => void;
  readonly regenerateHandler: (() => void) | undefined;
  readonly onRetry: () => void;
}

function PreviewContent({
  isOfflineDisabled,
  previewState,
  updateContainerSize,
  regenerateHandler,
  onRetry,
}: PreviewContentProps): JSX.Element {
  return (
    <div className="flex-1 overflow-hidden bg-muted/10">
      {isOfflineDisabled && !previewState.imageUrl && (
        <ConnectionRequiredState size="md" onRetry={onRetry} />
      )}
      {!(isOfflineDisabled && !previewState.imageUrl) && (
        <PreviewImage
          previewState={previewState}
          onContainerSizeChange={updateContainerSize}
          onRegenerateImage={regenerateHandler}
          className="h-full"
        />
      )}
    </div>
  );
}

/** Auto-regenerate preview once when templateData changes and backend is available */
function useAutoRegenerate(
  templateData: TemplateData | undefined,
  previewState: PreviewState,
  isBackendAvailable: boolean,
  regenerateImage: () => void,
): void {
  const hasAttemptedRef = useRef(false);
  const prevTemplateDataRef = useRef(templateData);

  if (prevTemplateDataRef.current !== templateData) {
    prevTemplateDataRef.current = templateData;
    hasAttemptedRef.current = false;
  }

  useEffect(() => {
    if (
      templateData &&
      !previewState.imageUrl &&
      !previewState.isGenerating &&
      isBackendAvailable &&
      !hasAttemptedRef.current
    ) {
      hasAttemptedRef.current = true;
      regenerateImage();
    }
  }, [
    templateData,
    previewState.imageUrl,
    previewState.isGenerating,
    isBackendAvailable,
    regenerateImage,
  ]);
}

export function DynamicPreview({
  pageSize,
  templateVersionId,
  templateData,
  title,
  config,
  onError,
  className = '',
  hideHeader = false,
  hideFitButton = false,
}: DynamicPreviewProps): JSX.Element {
  const { t } = useTranslation('omakase.preview');
  const { isBackendAvailable, forceCheck } = useConnectivitySafe();

  const { previewState, updateContainerSize, setScaleMode, zoomIn, zoomOut, regenerateImage } =
    usePreviewImage({ pageSize, templateVersionId, templateData, config, onError });

  useAutoRegenerate(templateData, previewState, isBackendAvailable, regenerateImage);

  const displayTitle = title ?? t('title');
  const isOfflineDisabled = !isBackendAvailable;
  const regenerateHandler = isBackendAvailable ? regenerateImage : undefined;

  return (
    <div className={`flex h-full flex-col ${className}`}>
      {!hideHeader && (
        <PreviewHeader
          displayTitle={displayTitle}
          scale={previewState.scale}
          isGenerating={previewState.isGenerating}
          disabled={isOfflineDisabled}
          hideFitButton={hideFitButton}
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
          onSetScaleMode={setScaleMode}
        />
      )}
      <PreviewContent
        isOfflineDisabled={isOfflineDisabled}
        previewState={previewState}
        updateContainerSize={updateContainerSize}
        regenerateHandler={regenerateHandler}
        onRetry={forceCheck}
      />
    </div>
  );
}
