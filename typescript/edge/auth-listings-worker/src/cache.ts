import {
  CACHE_FRESH_SECONDS,
  CACHE_KEY_PREFIX,
  CACHE_SWR_SECONDS,
  CACHE_VERSION,
} from './constants';

/** Build a Cache API key URL for a given country and optional language. */
export function buildCacheKey(country: string, lang?: string): string {
  const base = `${CACHE_KEY_PREFIX}/${CACHE_VERSION}/${country}`;
  if (!lang) {
    return base;
  }

  return `${base}/${lang}`;
}

/** Build Cache-Control headers for standard (non-empty) responses. */
export function buildCacheHeaders(): Record<string, string> {
  return {
    'Cache-Control': `public, s-maxage=${CACHE_FRESH_SECONDS}, stale-while-revalidate=${CACHE_SWR_SECONDS}`,
  };
}
