/**
 * Language formatting utilities using the browser-native Intl.DisplayNames API.
 *
 * Provides locale-aware language name resolution (e.g. "fr-CA" → "Canadian French"
 * in English, "français canadien" in French) and BCP 47 base language extraction.
 *
 * Intl.DisplayNames instances are cached per locale to avoid repeated construction
 * when rendering lists of items (Anti-Pattern #3: Repeated Expensive Operations).
 */

/** Fallback locale when no display locale is specified. */
const FALLBACK_DISPLAY_LOCALE = 'en';

/**
 * Module-level cache for Intl.DisplayNames instances, keyed by display locale.
 *
 * Construction cost is low (~microseconds), but caching avoids N identical
 * constructions when rendering N list items in a single render pass.
 * The cache holds at most one entry per supported UI locale (currently 2: en, fr-CA).
 */
const displayNamesCache: Map<string, Intl.DisplayNames> = new Map();

/**
 * Returns a cached Intl.DisplayNames instance for the given locale.
 * Creates and caches a new instance on first access per locale.
 *
 * @param locale - BCP 47 locale tag (e.g., "en", "fr-CA")
 * @returns Intl.DisplayNames instance for language name resolution
 */
function getDisplayNames(locale: string): Intl.DisplayNames {
  let cached = displayNamesCache.get(locale);
  if (!cached) {
    cached = new Intl.DisplayNames(locale, { type: 'language' });
    displayNamesCache.set(locale, cached);
  }
  return cached;
}

/**
 * Formats a BCP 47 language tag into a human-readable, localized language name.
 *
 * Uses the browser-native Intl.DisplayNames API for locale-aware resolution.
 * Falls back to the raw code if the tag is unrecognized or malformed.
 *
 * @param code - BCP 47 language tag (e.g., "fr-CA", "en", "zh-CN")
 * @param displayLocale - Locale for the output name (defaults to "en")
 * @returns Localized language name (e.g., "Canadian French", "français canadien")
 *
 * @example
 * formatLanguage('fr-CA', 'en')    // → "Canadian French"
 * formatLanguage('fr-CA', 'fr-CA') // → "français canadien"
 * formatLanguage('de', 'en')       // → "German"
 * formatLanguage('xyz')            // → "xyz" (fallback)
 */
function formatLanguage(code: string, displayLocale?: string): string {
  try {
    return getDisplayNames(displayLocale ?? FALLBACK_DISPLAY_LOCALE).of(code) ?? code;
  } catch {
    return code;
  }
}

/**
 * Extracts the base language subtag from a BCP 47 language tag.
 *
 * Used to compare language tags without region differences causing false
 * positives (e.g. a "fr-CA" UI should not badge "fr-FR" listings as foreign).
 *
 * @param tag - BCP 47 language tag (e.g., "fr-CA", "en-US", "zh-CN")
 * @returns Base language subtag (e.g., "fr", "en", "zh")
 *
 * @example
 * extractBaseLanguage('fr-CA')  // → "fr"
 * extractBaseLanguage('en')     // → "en"
 * extractBaseLanguage('zh-CN')  // → "zh"
 */
function extractBaseLanguage(tag: string): string {
  const separatorIndex = tag.indexOf('-');
  return separatorIndex === -1 ? tag : tag.substring(0, separatorIndex);
}

export { extractBaseLanguage, formatLanguage };
