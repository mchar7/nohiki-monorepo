import { describe, expect } from 'vitest';
import { extractDomainFromUrl } from './extractDomain.ts';

describe('extractDomainFromUrl', () => {
  test('extracts hostname from a valid URL', () => {
    expect(extractDomainFromUrl('https://jobs.acme.com/posting/123')).toBe('jobs.acme.com');
  });

  test('strips the www. prefix', () => {
    expect(extractDomainFromUrl('https://www.linkedin.com/jobs/view/123')).toBe('linkedin.com');
  });

  test('handles URLs without www.', () => {
    expect(extractDomainFromUrl('https://greenhouse.io/apply/456')).toBe('greenhouse.io');
  });

  test('returns null for null input', () => {
    expect(extractDomainFromUrl(null)).toBeNull();
  });

  test('returns null for an invalid URL', () => {
    expect(extractDomainFromUrl('not-a-url')).toBeNull();
  });

  test('returns null for an empty string', () => {
    expect(extractDomainFromUrl('')).toBeNull();
  });
});
