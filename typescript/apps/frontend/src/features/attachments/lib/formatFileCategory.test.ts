import { describe, expect } from 'vitest';
import { getFileCategory, getFileExtension } from './format.ts';

describe('getFileExtension', () => {
  test('extracts extension from filename', () => {
    expect(getFileExtension('document.pdf')).toBe('pdf');
    expect(getFileExtension('image.PNG')).toBe('png');
  });

  test('handles multiple dots in filename', () => {
    expect(getFileExtension('file.name.txt')).toBe('txt');
  });

  test('returns empty string for no extension', () => {
    expect(getFileExtension('filename')).toBe('');
  });

  test('returns empty string for hidden files', () => {
    expect(getFileExtension('.gitignore')).toBe('gitignore');
  });

  test('handles empty filename', () => {
    expect(getFileExtension('')).toBe('');
  });
});

describe('getFileCategory', () => {
  test('identifies PDF files', () => {
    expect(getFileCategory('application/pdf')).toBe('pdf');
  });

  test('identifies Word documents (.doc format)', () => {
    expect(getFileCategory('application/msword')).toBe('word');
  });

  test('identifies Word documents (modern)', () => {
    expect(
      getFileCategory('application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    ).toBe('word');
  });

  test('identifies image files', () => {
    expect(getFileCategory('image/png')).toBe('image');
    expect(getFileCategory('image/jpeg')).toBe('image');
    expect(getFileCategory('image/gif')).toBe('image');
  });

  test('identifies text files', () => {
    expect(getFileCategory('text/plain')).toBe('text');
    expect(getFileCategory('text/html')).toBe('text');
    expect(getFileCategory('text/css')).toBe('text');
  });

  test('returns unknown for other types', () => {
    expect(getFileCategory('application/zip')).toBe('unknown');
    expect(getFileCategory('application/json')).toBe('unknown');
    expect(getFileCategory('video/mp4')).toBe('unknown');
  });
});
