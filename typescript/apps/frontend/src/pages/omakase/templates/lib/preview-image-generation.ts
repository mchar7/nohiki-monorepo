import { awaitDocumentReady } from '@/entities/document';
import { fetchClient } from '@/shared/api/index.ts';
import type { PageSize, PreviewState, TemplateData } from '../model/index.ts';
import { calculateOptimalImageSize, updateScaleForNewImage } from './preview-calculations.ts';
import type { ImageCacheMap } from './useImageGeneration.ts';

/** Build a deterministic cache key for a given generation request */
function buildCacheKey(
  ps: PageSize,
  td: TemplateData,
  imgSize: { width: number; height: number },
): string {
  return JSON.stringify({ pageSize: ps, templateData: td, imageSize: imgSize });
}

/** Evict the oldest cache entry when the cache exceeds its maximum size */
function evictOldestCacheEntry(cache: ImageCacheMap, maxSize: number): void {
  if (cache.size < maxSize) {
    return;
  }
  const firstKey = cache.keys().next().value;
  if (firstKey) {
    const firstEntry = cache.get(firstKey);
    if (firstEntry) {
      URL.revokeObjectURL(firstEntry.url);
      cache.delete(firstKey);
    }
  }
}

/**
 * Request document generation via the API and fetch the resulting image blob.
 *
 * Uses fetchClient.POST imperatively by design. This function is called
 * from a non-hook async Promise chain (generateOrUseCached). $api.useMutation
 * is a React hook and cannot be used here. fetchClient provides the same
 * typed, schema-validated API surface for imperative async calls.
 */
async function requestAndFetchImage(
  templateVersionId: string,
  templateData: TemplateData,
): Promise<string> {
  const { data: genResponse, error } = await fetchClient.POST('/api/v1/documents/generate', {
    body: {
      template_version_id: templateVersionId,
      data: templateData || {},
      output_format: 'png',
    },
  });
  if (error) {
    throw error;
  }

  const { downloadUrl } = await awaitDocumentReady(genResponse.request_id);
  const blobResponse = await fetch(downloadUrl);
  if (!blobResponse.ok) {
    throw new Error(`Generated preview fetch failed with status ${blobResponse.status}`);
  }
  const blob = await blobResponse.blob();
  return URL.createObjectURL(blob);
}

/** Load an image URL and resolve its natural dimensions */
function loadImageNaturalSize(imageUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = (): void => {
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = (): void => {
      URL.revokeObjectURL(imageUrl);
      reject(new Error('Failed to load image'));
    };
    img.src = imageUrl;
  });
}

/** Apply a successful image load result to preview state */
function applyImageToState(
  prev: PreviewState,
  imageUrl: string,
  naturalSize: { width: number; height: number },
): PreviewState {
  return {
    ...prev,
    imageUrl,
    imageNaturalSize: naturalSize,
    isGenerating: false,
    lastGeneratedAt: new Date(),
    scale: updateScaleForNewImage(prev.scale, naturalSize),
  };
}

/** Apply a generation error to preview state */
function applyErrorToState(prev: PreviewState, errorMessage: string): PreviewState {
  return {
    ...prev,
    isGenerating: false,
    generationError: errorMessage,
  };
}

/**
 * Full generate-or-cache-hit cycle: check cache, request image if missed,
 * load natural size, update cache, and call state setters.
 */
export async function generateOrUseCached(params: {
  templateVersionId: string;
  templateData: TemplateData;
  pageSize: PageSize;
  containerSize: { width: number; height: number };
  maxDimension: number;
  cacheSize: number;
  targetSize: { width: number; height: number } | undefined;
  cache: ImageCacheMap;
  setPreviewState: (fn: (prev: PreviewState) => PreviewState) => void;
  onError: ((error: string) => void) | undefined;
  fallbackErrorMessage: string;
}): Promise<void> {
  const { templateVersionId, templateData, pageSize, containerSize, maxDimension, targetSize } =
    params;
  const { cacheSize, cache, setPreviewState, onError, fallbackErrorMessage } = params;
  const imageSize =
    targetSize ?? calculateOptimalImageSize(pageSize, containerSize, maxDimension, true);
  const cacheKey = buildCacheKey(pageSize, templateData, imageSize);
  const cached = cache.get(cacheKey);
  if (cached) {
    setPreviewState((prev) => ({
      ...prev,
      imageUrl: cached.url,
      imageNaturalSize: cached.size,
      scale: updateScaleForNewImage(prev.scale, cached.size),
    }));
    return;
  }
  setPreviewState((prev) => ({ ...prev, isGenerating: true, generationError: null }));
  try {
    const imageUrl = await requestAndFetchImage(templateVersionId, templateData);
    const naturalSize = await loadImageNaturalSize(imageUrl);
    evictOldestCacheEntry(cache, cacheSize);
    cache.set(cacheKey, { url: imageUrl, size: naturalSize });
    setPreviewState((prev) => applyImageToState(prev, imageUrl, naturalSize));
  } catch (error) {
    const msg = error instanceof Error ? error.message : fallbackErrorMessage;
    setPreviewState((prev) => applyErrorToState(prev, msg));
    onError?.(msg);
  }
}
