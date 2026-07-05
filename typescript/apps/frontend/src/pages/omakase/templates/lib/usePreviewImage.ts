import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type {
  PageSize,
  PreviewConfig,
  PreviewState,
  ScaleState,
  TemplateData,
} from '../model/index.ts';
import { DEFAULT_PREVIEW_CONFIG } from '../model/index.ts';
import { createInitialScaleState } from './preview-calculations.ts';
import { useContainerResize } from './useContainerResize.ts';
import { useImageGeneration } from './useImageGeneration.ts';
import { useScaleControls } from './useScaleControls.ts';

/** Initial container dimensions before the real size is known */
const INITIAL_CONTAINER_WIDTH_PX: number = 800;
const INITIAL_CONTAINER_HEIGHT_PX: number = 600;

interface UsePreviewImageOptions {
  pageSize: PageSize;
  templateVersionId?: string | undefined;
  templateData?: TemplateData | undefined;
  config?: Partial<PreviewConfig> | undefined;
  onError?: ((error: string) => void) | undefined;
}

interface UsePreviewImageReturn {
  previewState: PreviewState;
  updateContainerSize: (size: { width: number; height: number }) => void;
  setScaleMode: (mode: ScaleState['mode']) => void;
  setCustomScale: (percentage: number) => void;
  zoomIn: () => void;
  zoomOut: () => void;
  regenerateImage: () => void;
  generatePreviewImage: (targetSize?: { width: number; height: number }) => Promise<void>;
}

/** Create the initial preview state for the hook */
function createInitialPreviewState(
  pageSize: PageSize,
  templateData: TemplateData | undefined,
): PreviewState {
  return {
    imageUrl: null,
    imageNaturalSize: null,
    isGenerating: false,
    generationError: null,
    lastGeneratedAt: null,
    scale: createInitialScaleState({
      width: INITIAL_CONTAINER_WIDTH_PX,
      height: INITIAL_CONTAINER_HEIGHT_PX,
    }),
    containerSize: { width: INITIAL_CONTAINER_WIDTH_PX, height: INITIAL_CONTAINER_HEIGHT_PX },
    pageSize,
    templateData,
  };
}

type ImageCacheMap = Map<string, { url: string; size: { width: number; height: number } }>;
type TimeoutRef = React.MutableRefObject<ReturnType<typeof setTimeout> | null>;

/** Cleanup effect: revoke cached blob URLs and clear timeout on unmount */
function useCleanupOnUnmount(
  generationTimeoutRef: TimeoutRef,
  imageCache: React.MutableRefObject<ImageCacheMap>,
): void {
  useEffect(
    () => (): void => {
      if (generationTimeoutRef.current) {
        clearTimeout(generationTimeoutRef.current);
      }
      for (const { url } of imageCache.current.values()) {
        URL.revokeObjectURL(url);
      }
      imageCache.current.clear();
    },
    [generationTimeoutRef, imageCache],
  );
}

export function usePreviewImage(options: UsePreviewImageOptions): UsePreviewImageReturn {
  const { pageSize, templateVersionId, templateData, config: configOverrides, onError } = options;
  const { t } = useTranslation('omakase.preview');
  const config = { ...DEFAULT_PREVIEW_CONFIG, ...configOverrides };
  const [previewState, setPreviewState] = useState<PreviewState>(() =>
    createInitialPreviewState(pageSize, templateData),
  );

  const { generatePreviewImage, imageCache, generationTimeoutRef } = useImageGeneration({
    pageSize,
    templateVersionId,
    templateData,
    config,
    previewState,
    setPreviewState,
    onError,
    fallbackErrorMessage: t('errors.generationFailed'),
  });

  const { updateContainerSize, regenerateImage } = useContainerResize({
    pageSize,
    config,
    previewState,
    setPreviewState,
    generatePreviewImage,
    generationTimeoutRef,
  });

  const { setScaleMode, setCustomScale, zoomIn, zoomOut } = useScaleControls(
    config,
    setPreviewState,
  );

  useEffect(() => {
    setPreviewState((prev) => ({ ...prev, pageSize, templateData }));
  }, [pageSize, templateData]);

  useCleanupOnUnmount(generationTimeoutRef, imageCache);

  return {
    previewState,
    updateContainerSize,
    setScaleMode,
    setCustomScale,
    zoomIn,
    zoomOut,
    regenerateImage,
    generatePreviewImage,
  };
}
