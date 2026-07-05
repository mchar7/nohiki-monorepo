import { describe, expect } from 'vitest';

import { extractBaseLanguage, formatLanguage } from './language-format.ts';

describe('formatLanguage', () => {
  test('formats a simple language code to a human-readable name', () => {
    expect(formatLanguage('en', 'en')).toBe('English');
  });

  test('formats a regional tag to a dialect display name', () => {
    expect(formatLanguage('fr-CA', 'en')).toBe('Canadian French');
  });

  test('formats common language codes correctly', () => {
    expect(formatLanguage('de', 'en')).toBe('German');
    expect(formatLanguage('ja', 'en')).toBe('Japanese');
    // Node.js Intl returns 'Chinese (China)'; browsers may return 'Simplified Chinese' -
    // both are valid human-readable names, so assert the raw code is NOT returned.
    expect(formatLanguage('zh-CN', 'en')).not.toBe('zh-CN');
  });

  test('respects the display locale for output language', () => {
    const result = formatLanguage('de', 'fr-CA');
    // French locale renders language names in French (lowercase by convention)
    expect(result).toBe('allemand');
  });

  test('defaults to English display locale when none provided', () => {
    expect(formatLanguage('fr-CA')).toBe('Canadian French');
  });

  test('falls back to the raw code for an unrecognized tag', () => {
    expect(formatLanguage('xyz')).toBe('xyz');
  });

  test('falls back to the raw code for an empty string', () => {
    expect(formatLanguage('')).toBe('');
  });

  test('returns consistent results across multiple calls (cache stability)', () => {
    const first = formatLanguage('fr-CA', 'en');
    const second = formatLanguage('fr-CA', 'en');
    expect(first).toBe(second);
    expect(first).toBe('Canadian French');
  });
});

describe('extractBaseLanguage', () => {
  test('extracts the base subtag from a regional tag', () => {
    expect(extractBaseLanguage('fr-CA')).toBe('fr');
  });

  test('extracts the base subtag from other regional tags', () => {
    expect(extractBaseLanguage('en-US')).toBe('en');
    expect(extractBaseLanguage('zh-CN')).toBe('zh');
    expect(extractBaseLanguage('pt-BR')).toBe('pt');
  });

  test('returns the tag itself when no region is present', () => {
    expect(extractBaseLanguage('en')).toBe('en');
    expect(extractBaseLanguage('fr')).toBe('fr');
    expect(extractBaseLanguage('de')).toBe('de');
  });
});
