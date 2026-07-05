import type { PageSize, PreviewConfig, ScaleState } from '../model/types.ts';
import { calculateAspectRatio } from './page-size.ts';

/** Browser default DPI for pixel conversion */
const BROWSER_DPI: number = 96;
/** Millimetres per inch for unit conversion */
const MM_PER_INCH: number = 25.4;
/** US Letter page width in pixels at 96 DPI (850px ~ 8.5in x 100px/in) */
const LETTER_BASE_WIDTH_PX: number = 850;
/** A4 page base width in pixels, chosen to maintain A4 aspect ratio */
const A4_BASE_WIDTH_PX: number = 827;
/** Maximum base width for custom page sizes relative to container */
const CUSTOM_PAGE_CONTAINER_SCALE: number = 1.5;
/** Maximum fallback width (px) for custom page sizes */
const CUSTOM_PAGE_MAX_WIDTH_PX: number = 800;
/** Percentage scale representing 100% (actual size) */
const ACTUAL_SCALE_PERCENT: number = 100;
/** US Letter paper width in inches */
const US_LETTER_WIDTH_IN: number = 8.5;
/** US Letter paper height in inches */
const US_LETTER_HEIGHT_IN: number = 11;
/** A4 paper width in millimetres */
const A4_WIDTH_MM: number = 210;
/** A4 paper height in millimetres */
const A4_HEIGHT_MM: number = 297;

/** Constrain exact pixel dimensions to max dimension while preserving aspect ratio */
function constrainToMaxDimension(
  dimensions: { width: number; height: number },
  maxDimension: number,
  aspectRatio: number,
): { width: number; height: number } {
  if (dimensions.width > maxDimension || dimensions.height > maxDimension) {
    if (dimensions.width > dimensions.height) {
      return { width: maxDimension, height: Math.round(maxDimension / aspectRatio) };
    }
    return { width: Math.round(maxDimension * aspectRatio), height: maxDimension };
  }
  return dimensions;
}

/** Determine base width for display based on standard page sizes */
function resolveBaseWidth(pageSize: PageSize, containerWidth: number): number {
  if (
    pageSize.unit === 'in' &&
    pageSize.width === US_LETTER_WIDTH_IN &&
    pageSize.height === US_LETTER_HEIGHT_IN
  ) {
    return LETTER_BASE_WIDTH_PX;
  }
  if (
    pageSize.unit === 'mm' &&
    pageSize.width === A4_WIDTH_MM &&
    pageSize.height === A4_HEIGHT_MM
  ) {
    return A4_BASE_WIDTH_PX;
  }
  return Math.min(CUSTOM_PAGE_MAX_WIDTH_PX, containerWidth * CUSTOM_PAGE_CONTAINER_SCALE);
}

/**
 * Calculate exact pixel dimensions for a page size that matches the CSS @page rule.
 * Guarantees image generation produces exact dimensions without margins.
 */
function calculateExactPixelDimensions(pageSize: PageSize): {
  width: number;
  height: number;
} {
  let widthInches: number;
  let heightInches: number;

  switch (pageSize.unit) {
    case 'in':
      widthInches = pageSize.width;
      heightInches = pageSize.height;
      break;
    case 'mm':
      widthInches = pageSize.width / MM_PER_INCH;
      heightInches = pageSize.height / MM_PER_INCH;
      break;
    default:
      widthInches = pageSize.width;
      heightInches = pageSize.height;
  }

  return {
    width: Math.round(widthInches * BROWSER_DPI),
    height: Math.round(heightInches * BROWSER_DPI),
  };
}

export function calculateOptimalImageSize(
  pageSize: PageSize,
  containerSize: { width: number; height: number },
  maxDimension: number,
  forImageGeneration: boolean = false,
): { width: number; height: number } {
  const aspectRatio = calculateAspectRatio(pageSize);

  // For image generation, use exact pixel dimensions to avoid margins
  if (forImageGeneration) {
    const exactDimensions = calculateExactPixelDimensions(pageSize);
    return constrainToMaxDimension(exactDimensions, maxDimension, aspectRatio);
  }

  // For display purposes, resolve base width by page type
  let width = resolveBaseWidth(pageSize, containerSize.width);
  let height = Math.round(width / aspectRatio);

  if (width > maxDimension) {
    width = maxDimension;
    height = Math.round(width / aspectRatio);
  }
  if (height > maxDimension) {
    height = maxDimension;
    width = Math.round(height * aspectRatio);
  }

  return { width, height };
}

export function calculateFitScale(
  imageNaturalSize: { width: number; height: number },
  containerSize: { width: number; height: number },
): number {
  const scaleX = containerSize.width / imageNaturalSize.width;
  const scaleY = containerSize.height / imageNaturalSize.height;
  return Math.min(scaleX, scaleY) * ACTUAL_SCALE_PERCENT;
}

export function calculateDisplaySize(
  imageNaturalSize: { width: number; height: number },
  scalePercentage: number,
): { width: number; height: number } {
  const scale = scalePercentage / ACTUAL_SCALE_PERCENT;
  return {
    width: Math.round(imageNaturalSize.width * scale),
    height: Math.round(imageNaturalSize.height * scale),
  };
}

export function clampScale(scale: number, config: PreviewConfig): number {
  return Math.max(config.minScale, Math.min(config.maxScale, scale));
}

export function shouldRegenerateImage(
  currentImageSize: { width: number; height: number } | null,
  optimalImageSize: { width: number; height: number },
  threshold: number = 0.5,
): boolean {
  if (!currentImageSize) {
    return true;
  }

  const widthRatio = optimalImageSize.width / currentImageSize.width;
  const heightRatio = optimalImageSize.height / currentImageSize.height;

  return widthRatio > 1 + threshold || heightRatio > 1 + threshold;
}

export function getNextScaleStep(
  currentScale: number,
  direction: 'in' | 'out',
  step: number,
): number {
  if (direction === 'in') {
    return currentScale + step;
  }
  return currentScale - step;
}

export function createInitialScaleState(containerSize: {
  width: number;
  height: number;
}): ScaleState {
  return {
    mode: 'fit',
    percentage: ACTUAL_SCALE_PERCENT,
    imageNaturalSize: null,
    containerSize,
  };
}

export function updateScaleForNewImage(
  scaleState: ScaleState,
  imageNaturalSize: { width: number; height: number },
): ScaleState {
  const newState = {
    ...scaleState,
    imageNaturalSize,
  };

  if (scaleState.mode === 'fit') {
    newState.percentage = calculateFitScale(imageNaturalSize, scaleState.containerSize);
  } else if (scaleState.mode === 'actual') {
    newState.percentage = ACTUAL_SCALE_PERCENT;
  }

  return newState;
}

export function updateScaleForNewContainer(
  scaleState: ScaleState,
  containerSize: { width: number; height: number },
): ScaleState {
  const newState = {
    ...scaleState,
    containerSize,
  };

  if (scaleState.mode === 'fit' && scaleState.imageNaturalSize) {
    newState.percentage = calculateFitScale(scaleState.imageNaturalSize, containerSize);
  }

  return newState;
}
