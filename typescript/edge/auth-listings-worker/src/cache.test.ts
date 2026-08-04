import { describe, expect, it } from 'vitest';
import { buildCacheHeaders, buildCacheKey } from './cache';
import {
  CACHE_FRESH_SECONDS,
  CACHE_KEY_PREFIX,
  CACHE_SWR_SECONDS,
  CACHE_VERSION,
} from './constants';

describe('buildCacheKey', () => {
  it('builds key for USA', () => {
    expect(buildCacheKey('USA')).toBe(`${CACHE_KEY_PREFIX}/${CACHE_VERSION}/USA`);
  });

  it('builds key for GBR', () => {
    expect(buildCacheKey('GBR')).toBe(`${CACHE_KEY_PREFIX}/${CACHE_VERSION}/GBR`);
  });

  it('builds key for any arbitrary country string', () => {
    expect(buildCacheKey('DEU')).toBe(`${CACHE_KEY_PREFIX}/${CACHE_VERSION}/DEU`);
  });

  it('builds key with lang segment for multilingual countries', () => {
    expect(buildCacheKey('USA', 'en')).toBe(`${CACHE_KEY_PREFIX}/${CACHE_VERSION}/USA/en`);
  });

  it('builds key without lang segment when lang is undefined', () => {
    expect(buildCacheKey('CHE', undefined)).toBe(`${CACHE_KEY_PREFIX}/${CACHE_VERSION}/CHE`);
  });
});

describe('buildCacheHeaders', () => {
  it('returns Cache-Control with s-maxage and stale-while-revalidate', () => {
    const headers = buildCacheHeaders();
    expect(headers).toEqual({
      'Cache-Control': `public, s-maxage=${CACHE_FRESH_SECONDS}, stale-while-revalidate=${CACHE_SWR_SECONDS}`,
    });
  });

  it('uses correct freshness and SWR values', () => {
    const headers = buildCacheHeaders() as Record<string, string>;
    const cc = headers['Cache-Control'];
    expect(cc).toContain(`s-maxage=${CACHE_FRESH_SECONDS}`);
    expect(cc).toContain(`stale-while-revalidate=${CACHE_SWR_SECONDS}`);
    expect(cc).toContain('public');
  });
});
