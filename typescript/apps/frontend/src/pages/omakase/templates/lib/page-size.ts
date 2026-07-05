import type { PageSize } from '../model/types.ts';

/** Default fallback width (px) when no dimensions are provided. */
const DEFAULT_IMAGE_WIDTH_PX: number = 800;

/** Standard page size presets, keyed by name. */
export const PAGE_PRESETS = {
  letter: { width: 8.5, height: 11, unit: 'in' as const },
  a4: { width: 210, height: 297, unit: 'mm' as const },
} as const;

export type PresetKey = keyof typeof PAGE_PRESETS | 'custom';

function isPreset(pageSize: PageSize, preset: PageSize): boolean {
  return (
    pageSize.width === preset.width &&
    pageSize.height === preset.height &&
    pageSize.unit === preset.unit
  );
}

export function detectPreset(pageSize: PageSize): PresetKey {
  if (isPreset(pageSize, PAGE_PRESETS.letter)) {
    return 'letter';
  }
  if (isPreset(pageSize, PAGE_PRESETS.a4)) {
    return 'a4';
  }
  return 'custom';
}

/**
 * Calculate aspect ratio from page size (width / height)
 */
export function calculateAspectRatio(pageSize: PageSize): number {
  return pageSize.width / pageSize.height;
}

/**
 * Calculate image dimensions maintaining aspect ratio
 * Always returns both width and height
 */
export function calculateImageDimensions(
  pageSize: PageSize,
  options: {
    width?: number;
    height?: number;
    maxWidth?: number;
    maxHeight?: number;
  },
): { width: number; height: number } {
  const aspectRatio = calculateAspectRatio(pageSize);

  let { width, height } = options;
  const { maxWidth, maxHeight } = options;

  if (width && height) {
    return { width, height };
  }

  if (width && !height) {
    height = Math.round(width / aspectRatio);
  }

  if (height && !width) {
    width = Math.round(height * aspectRatio);
  }

  if (!(width || height)) {
    width = maxWidth || DEFAULT_IMAGE_WIDTH_PX;
    height = Math.round(width / aspectRatio);
  }

  // Ensure width and height are defined at this point
  width = width || DEFAULT_IMAGE_WIDTH_PX;
  height = height || Math.round(width / aspectRatio);

  if (maxWidth && width > maxWidth) {
    width = maxWidth;
    height = Math.round(width / aspectRatio);
  }

  if (maxHeight && height > maxHeight) {
    height = maxHeight;
    width = Math.round(height * aspectRatio);
  }

  return { width, height };
}

/**
 * Validate that CSS @page size matches meta.json pageSize
 */
export function validatePageSizeMatch(
  metaPageSize: PageSize,
  cssPageSize: string,
): { valid: boolean; error?: string } {
  const normalized = cssPageSize.toLowerCase().trim();
  const expected = `${metaPageSize.width}${metaPageSize.unit} ${metaPageSize.height}${metaPageSize.unit}`;
  const expectedReverse = `${metaPageSize.height}${metaPageSize.unit} ${metaPageSize.width}${metaPageSize.unit}`;

  if (normalized === expected.toLowerCase() || normalized === expectedReverse.toLowerCase()) {
    return { valid: true };
  }

  return {
    valid: false,
    error: `CSS @page size "${cssPageSize}" does not match meta.json pageSize "${expected}"`,
  };
}
