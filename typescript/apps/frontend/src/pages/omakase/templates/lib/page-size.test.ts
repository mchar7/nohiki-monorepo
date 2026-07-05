import { describe, expect } from 'vitest';
import type { PageSize } from '../model/types.ts';
import {
  calculateAspectRatio,
  calculateImageDimensions,
  validatePageSizeMatch,
} from './page-size.ts';

const LETTER_WIDTH_IN: number = 8.5;
const LETTER_HEIGHT_IN: number = 11;
const A4_WIDTH_MM: number = 210;
const A4_HEIGHT_MM: number = 297;
const SQUARE_SIZE_MM: number = 100;
const DIM_400_PX: number = 400;
const DIM_500_PX: number = 500;
const DIM_600_PX: number = 600;
const DIM_800_PX: number = 800;
const DIM_1000_PX: number = 1000;
const DIM_1200_PX: number = 1200;
const DIM_1600_PX: number = 1600;
const PRECISION_5_DECIMALS: number = 5;

const letterSize: PageSize = { width: LETTER_WIDTH_IN, height: LETTER_HEIGHT_IN, unit: 'in' };
const a4Size: PageSize = { width: A4_WIDTH_MM, height: A4_HEIGHT_MM, unit: 'mm' };

describe('calculateAspectRatio', () => {
  test('calculates aspect ratio for letter size', () => {
    const ratio = calculateAspectRatio(letterSize);
    expect(ratio).toBeCloseTo(LETTER_WIDTH_IN / LETTER_HEIGHT_IN, PRECISION_5_DECIMALS);
  });

  test('calculates aspect ratio for A4', () => {
    const ratio = calculateAspectRatio(a4Size);
    expect(ratio).toBeCloseTo(A4_WIDTH_MM / A4_HEIGHT_MM, PRECISION_5_DECIMALS);
  });

  test('handles square dimensions', () => {
    const square: PageSize = { width: SQUARE_SIZE_MM, height: SQUARE_SIZE_MM, unit: 'mm' };
    expect(calculateAspectRatio(square)).toBe(1);
  });
});

describe('calculateImageDimensions', () => {
  test('returns provided width and height when both are given', () => {
    const result = calculateImageDimensions(letterSize, {
      width: DIM_400_PX,
      height: DIM_500_PX,
    });
    expect(result).toEqual({ width: DIM_400_PX, height: DIM_500_PX });
  });

  test('calculates height from width', () => {
    const result = calculateImageDimensions(letterSize, { width: DIM_800_PX });
    expect(result.width).toBe(DIM_800_PX);
    expect(result.height).toBe(Math.round(DIM_800_PX / (LETTER_WIDTH_IN / LETTER_HEIGHT_IN)));
  });

  test('calculates width from height', () => {
    const result = calculateImageDimensions(letterSize, { height: DIM_1000_PX });
    expect(result.height).toBe(DIM_1000_PX);
    expect(result.width).toBe(Math.round(DIM_1000_PX * (LETTER_WIDTH_IN / LETTER_HEIGHT_IN)));
  });

  test('uses maxWidth as default when no dimensions provided', () => {
    const result = calculateImageDimensions(letterSize, { maxWidth: DIM_600_PX });
    expect(result.width).toBe(DIM_600_PX);
  });

  test('uses 800 as default width when no dimensions provided', () => {
    const result = calculateImageDimensions(letterSize, {});
    expect(result.width).toBe(DIM_800_PX);
  });

  test('constrains to maxWidth', () => {
    const result = calculateImageDimensions(letterSize, {
      width: DIM_1200_PX,
      maxWidth: DIM_800_PX,
    });
    expect(result.width).toBe(DIM_800_PX);
  });

  test('constrains to maxHeight', () => {
    const DIM_2000_PX: number = 2000;
    const result = calculateImageDimensions(letterSize, {
      height: DIM_2000_PX,
      maxHeight: DIM_1000_PX,
    });
    expect(result.height).toBe(DIM_1000_PX);
  });

  test('maintains aspect ratio when constraining', () => {
    const result = calculateImageDimensions(letterSize, {
      width: DIM_1600_PX,
      maxWidth: DIM_800_PX,
    });
    const expectedRatio = LETTER_WIDTH_IN / LETTER_HEIGHT_IN;
    expect(result.width).toBe(DIM_800_PX);
    expect(result.height).toBe(Math.round(DIM_800_PX / expectedRatio));
  });
});

describe('validatePageSizeMatch', () => {
  test('returns valid for matching CSS size', () => {
    const result = validatePageSizeMatch(letterSize, '8.5in 11in');
    expect(result.valid).toBe(true);
  });

  test('returns valid for reversed matching CSS size', () => {
    const result = validatePageSizeMatch(letterSize, '11in 8.5in');
    expect(result.valid).toBe(true);
  });

  test('is case-insensitive', () => {
    const result = validatePageSizeMatch(letterSize, '8.5IN 11IN');
    expect(result.valid).toBe(true);
  });

  test('trims whitespace', () => {
    const result = validatePageSizeMatch(letterSize, '  8.5in 11in  ');
    expect(result.valid).toBe(true);
  });

  test('returns invalid with error for non-matching size', () => {
    const result = validatePageSizeMatch(letterSize, '210mm 297mm');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('does not match');
  });

  test('validates A4 size', () => {
    const result = validatePageSizeMatch(a4Size, '210mm 297mm');
    expect(result.valid).toBe(true);
  });
});
