import { describe, expect } from 'vitest';
import { formatFileSize } from './file-size-format.ts';

const BYTES_500: number = 500;
const BYTES_1023: number = 1023;
const BYTES_PER_KB: number = 1024;
const BYTES_PER_MB: number = BYTES_PER_KB * BYTES_PER_KB;
const KB_500: number = 500;
const MB_5: number = 5;
const MB_1_5: number = 1.5;

describe('formatFileSize', () => {
  test('returns bytes for small files', () => {
    expect(formatFileSize(BYTES_500)).toEqual({ size: BYTES_500, unit: 'bytes' });
  });

  test('returns bytes for files under 1KB', () => {
    expect(formatFileSize(BYTES_1023)).toEqual({ size: BYTES_1023, unit: 'bytes' });
  });

  test('returns kb for files between 1KB and 1MB', () => {
    expect(formatFileSize(BYTES_PER_KB)).toEqual({ size: 1, unit: 'kb' });
    expect(formatFileSize(BYTES_PER_KB * KB_500)).toEqual({ size: KB_500, unit: 'kb' });
  });

  test('returns mb for files 1MB and larger', () => {
    expect(formatFileSize(BYTES_PER_MB)).toEqual({ size: 1, unit: 'mb' });
    expect(formatFileSize(BYTES_PER_MB * MB_5)).toEqual({ size: MB_5, unit: 'mb' });
  });

  test('rounds mb to one decimal place', () => {
    expect(formatFileSize(BYTES_PER_MB * MB_1_5)).toEqual({ size: MB_1_5, unit: 'mb' });
  });

  test('handles zero bytes', () => {
    expect(formatFileSize(0)).toEqual({ size: 0, unit: 'bytes' });
  });
});
