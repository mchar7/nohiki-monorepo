import { describe, expect } from 'vitest';
import { generatePdfFilename, slugify } from './filename.ts';

describe('slugify', () => {
  test('converts to lowercase', () => {
    expect(slugify('Hello World')).toBe('hello-world');
  });

  test('replaces spaces with hyphens', () => {
    expect(slugify('my document name')).toBe('my-document-name');
  });

  test('removes special characters', () => {
    expect(slugify('Hello, World!')).toBe('hello-world');
    expect(slugify('test@file#name')).toBe('testfilename');
  });

  test('replaces underscores with hyphens', () => {
    expect(slugify('my_file_name')).toBe('my-file-name');
  });

  test('handles multiple consecutive spaces', () => {
    expect(slugify('hello   world')).toBe('hello-world');
  });

  test('handles multiple consecutive hyphens', () => {
    expect(slugify('hello---world')).toBe('hello-world');
  });

  test('removes leading and trailing hyphens', () => {
    expect(slugify('--hello world--')).toBe('hello-world');
  });

  test('trims whitespace', () => {
    expect(slugify('  hello world  ')).toBe('hello-world');
  });

  test('handles empty string', () => {
    expect(slugify('')).toBe('');
  });

  test('handles string with only special characters', () => {
    expect(slugify('!@#$%^&*()')).toBe('');
  });

  test('preserves numbers', () => {
    expect(slugify('Resume 2025 v2')).toBe('resume-2025-v2');
  });
});

describe('generatePdfFilename', () => {
  test('generates filename from dataset and template names', () => {
    const result = generatePdfFilename('My Resume', 'Modern Template');
    expect(result).toBe('my-resume-modern-template.pdf');
  });

  test('handles special characters in names', () => {
    const result = generatePdfFilename('John Doe Resume', 'Template (v2)');
    expect(result).toBe('john-doe-resume-template-v2.pdf');
  });

  test('handles empty dataset name', () => {
    const result = generatePdfFilename('', 'Template');
    expect(result).toBe('-template.pdf');
  });

  test('handles empty template name', () => {
    const result = generatePdfFilename('Resume', '');
    expect(result).toBe('resume-.pdf');
  });

  test('handles unicode characters by removing them', () => {
    const result = generatePdfFilename('Résumé', 'Template');
    expect(result).toBe('rsum-template.pdf');
  });
});
