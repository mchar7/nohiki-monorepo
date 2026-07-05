import { type MutableRefObject, useRef } from 'react';
import type { PageSize, PreviewConfig, PreviewState, TemplateData } from '../model/index.ts';
import { generateOrUseCached } from './preview-image-generation.ts';

type ImageCacheMap = Map<string, { url: string; size: { width: number; height: number } }>;
type SetState = React.Dispatch<React.SetStateAction<PreviewState>>;

interface ImageGenerationOptions {
  pageSize: PageSize;
  templateVersionId: string | undefined;
  templateData: TemplateData | undefined;
  config: PreviewConfig;
  previewState: PreviewState;
  setPreviewState: SetState;
  onError: ((error: string) => void) | undefined;
  fallbackErrorMessage: string;
}

interface ImageGenerationResult {
  generatePreviewImage: (targetSize?: { width: number; height: number }) => Promise<void>;
  imageCache: MutableRefObject<ImageCacheMap>;
  generationTimeoutRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
}

/**
 * Manages the core image generation callback, cache refs, and timeout ref.
 * Container resize and debounce logic lives in useContainerResize.
 */
export function useImageGeneration(opts: ImageGenerationOptions): ImageGenerationResult {
  const { pageSize, config, previewState, setPreviewState, templateData, templateVersionId } = opts;
  const generationTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const imageCache = useRef<ImageCacheMap>(new Map());

  const generatePreviewImage = async (targetSize?: {
    width: number;
    height: number;
  }): Promise<void> => {
    if (!(templateData && templateVersionId)) {
      return;
    }
    await generateOrUseCached({
      templateVersionId,
      templateData,
      pageSize,
      containerSize: previewState.containerSize,
      maxDimension: config.maxDimension,
      cacheSize: config.cacheSize,
      targetSize,
      cache: imageCache.current,
      setPreviewState,
      onError: opts.onError,
      fallbackErrorMessage: opts.fallbackErrorMessage,
    });
  };

  return { generatePreviewImage, imageCache, generationTimeoutRef };
}

export type { ImageCacheMap, SetState };
