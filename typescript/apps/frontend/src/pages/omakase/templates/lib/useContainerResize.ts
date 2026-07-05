import type { MutableRefObject } from 'react';
import type { PageSize, PreviewConfig, PreviewState } from '../model/index.ts';
import {
  calculateOptimalImageSize,
  shouldRegenerateImage,
  updateScaleForNewContainer,
} from './preview-calculations.ts';
import type { SetState } from './useImageGeneration.ts';

interface ContainerResizeOptions {
  pageSize: PageSize;
  config: PreviewConfig;
  previewState: PreviewState;
  setPreviewState: SetState;
  generatePreviewImage: (targetSize?: { width: number; height: number }) => Promise<void>;
  generationTimeoutRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
}

interface ContainerResizeResult {
  updateContainerSize: (size: { width: number; height: number }) => void;
  regenerateImage: () => void;
}

/**
 * Manages container resize handling, debounced regeneration, and manual regeneration.
 * Works alongside useImageGeneration which provides the core generate callback.
 */
export function useContainerResize(opts: ContainerResizeOptions): ContainerResizeResult {
  const {
    pageSize,
    config,
    previewState,
    setPreviewState,
    generatePreviewImage,
    generationTimeoutRef,
  } = opts;

  const debouncedGenerate = (targetSize?: { width: number; height: number }): void => {
    if (generationTimeoutRef.current) {
      clearTimeout(generationTimeoutRef.current);
    }
    generationTimeoutRef.current = setTimeout(() => {
      generatePreviewImage(targetSize).catch(() => undefined);
    }, config.debounceMs);
  };

  const updateContainerSize = (size: { width: number; height: number }): void => {
    setPreviewState((prev) => ({
      ...prev,
      containerSize: size,
      scale: updateScaleForNewContainer(prev.scale, size),
    }));
    const optimalSize = calculateOptimalImageSize(pageSize, size, config.maxDimension, false);
    if (shouldRegenerateImage(previewState.imageNaturalSize, optimalSize)) {
      debouncedGenerate(calculateOptimalImageSize(pageSize, size, config.maxDimension, true));
    }
  };

  const regenerateImage = (): void => {
    const size = calculateOptimalImageSize(
      pageSize,
      previewState.containerSize,
      config.maxDimension,
      true,
    );
    generatePreviewImage(size).catch(() => undefined);
  };

  return { updateContainerSize, regenerateImage };
}
