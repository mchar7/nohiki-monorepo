/**
 * Input sanitization utilities for XSS prevention.
 *
 * These functions help prevent Cross-Site Scripting (XSS) attacks by
 * sanitizing user input before rendering or processing.
 */

/** Characters that need HTML entity encoding */
const HTML_ESCAPE_MAP: Readonly<Record<string, string>> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#x27;',
  '/': '&#x2F;',
  '`': '&#x60;',
  '=': '&#x3D;',
};

/** Pattern matching characters to escape */
const HTML_ESCAPE_PATTERN = /[&<>"'`=/]/gu;

/**
 * Escapes HTML special characters to prevent XSS attacks.
 * Use this when inserting untrusted data into HTML content.
 *
 * Accepts nullish input defensively so callers do not need to guard around it
 * at every boundary; nullish values return an empty string.
 *
 * @param input - The string to escape (null/undefined treated as empty)
 * @returns The escaped string safe for HTML insertion
 */
function escapeHtml(input: string | null | undefined): string {
  if (!input) {
    return '';
  }
  return input.replaceAll(HTML_ESCAPE_PATTERN, (char) => HTML_ESCAPE_MAP[char] ?? char);
}

/** Allowed HTML tags for basic sanitization */
const ALLOWED_TAGS: Set<string> = new Set([
  'p',
  'br',
  'b',
  'i',
  'u',
  'strong',
  'em',
  'span',
  'div',
  'ul',
  'ol',
  'li',
  'a',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
]);

/** Allowed attributes for sanitized HTML */
const ALLOWED_ATTRIBUTES: Set<string> = new Set(['href', 'title', 'class', 'id']);

/** Pattern to match HTML tags */
const HTML_TAG_PATTERN = /<\/?([a-z][a-z0-9]*)\b[^>]*>/giu;

/** Pattern to match HTML attributes */
const ATTRIBUTE_PATTERN = /\s+([a-z-]+)(?:=(?:"[^"]*"|'[^']*'|[^\s>]*))?/gu;

/** Pattern to extract href value */
const HREF_VALUE_PATTERN = /href=(?:"([^"]*)"|'([^']*)'|([^\s>]*))/iu;

/**
 * Extracts and validates an href attribute from a tag match.
 */
function extractHrefAttribute(match: string): string | null {
  const hrefMatch = HREF_VALUE_PATTERN.exec(match);
  const hrefValue = hrefMatch?.[1] ?? hrefMatch?.[2] ?? hrefMatch?.[3] ?? '';
  if (isValidUrl(hrefValue)) {
    return `href="${escapeHtml(hrefValue)}"`;
  }
  return null;
}

/**
 * Processes a single attribute match and returns the sanitized attribute string.
 */
function processAttribute(attrMatch: RegExpExecArray, match: string): string | null {
  const [, rawName] = attrMatch;
  if (rawName === undefined) {
    return null;
  }
  const attrName = rawName.toLowerCase();

  if (!ALLOWED_ATTRIBUTES.has(attrName)) {
    return null;
  }

  if (attrName === 'href') {
    return extractHrefAttribute(match);
  }

  return attrMatch[0].trim();
}

/**
 * Extracts all allowed attributes from a tag match.
 */
function extractAllowedAttributes(match: string): string[] {
  const attributes: string[] = [];
  const attrMatches = match.matchAll(ATTRIBUTE_PATTERN);

  for (const attrMatch of attrMatches) {
    const processed = processAttribute(attrMatch, match);
    if (processed !== null) {
      attributes.push(processed);
    }
  }

  return attributes;
}

/**
 * Processes a single HTML tag and returns the sanitized version.
 */
function processTag(match: string, tagName: string): string {
  const lowerTag = tagName.toLowerCase();

  if (!ALLOWED_TAGS.has(lowerTag)) {
    return '';
  }

  if (match.startsWith('</')) {
    return `</${lowerTag}>`;
  }

  const attributes = extractAllowedAttributes(match);
  const attrString = attributes.length > 0 ? ` ${attributes.join(' ')}` : '';
  const selfClosing = match.endsWith('/>') ? ' /' : '';

  return `<${lowerTag}${attrString}${selfClosing}>`;
}

/**
 * Sanitizes HTML content by removing potentially dangerous tags and attributes.
 * Only allows a whitelist of safe tags and attributes.
 *
 * @param html - The HTML string to sanitize
 * @returns Sanitized HTML string
 */
function sanitizeHtml(html: string): string {
  if (!html) {
    return '';
  }
  return html.replaceAll(HTML_TAG_PATTERN, processTag);
}

/** Protocols allowed in URLs */
const SAFE_URL_PROTOCOLS: Set<string> = new Set(['http:', 'https:', 'mailto:', 'tel:']);

/** Pattern for detecting javascript: or data: URLs */
const DANGEROUS_URL_PATTERN = /^(?:javascript|data|vbscript):/iu;

/**
 * Validates that a URL is safe to use (not a javascript: or data: URL).
 *
 * @param url - The URL to validate
 * @returns True if the URL is safe, false otherwise
 */
function isValidUrl(url: string): boolean {
  if (!url) {
    return false;
  }

  const trimmed = url.trim();

  // Check for dangerous protocols
  if (DANGEROUS_URL_PATTERN.test(trimmed)) {
    return false;
  }

  // Allow relative URLs
  if (trimmed.startsWith('/') || trimmed.startsWith('#') || trimmed.startsWith('?')) {
    return true;
  }

  // Check for safe protocols
  try {
    const parsed = new URL(trimmed, globalThis.location?.origin ?? 'https://example.com');
    return SAFE_URL_PROTOCOLS.has(parsed.protocol);
  } catch {
    // If URL parsing fails, check if it looks like a relative path
    return !trimmed.includes(':');
  }
}

/**
 * Returns a backend-compatible app-local absolute path or the supplied fallback.
 * The path must be 1..2048 characters, begin with exactly one slash, and contain
 * neither URL authority syntax, backslashes, nor control characters.
 */
function getSafeReturnUrl(url: string | undefined, fallback: string = '/'): string {
  return url !== undefined &&
    url.length >= 1 &&
    url.length <= 2048 &&
    url[0] === '/' &&
    url[1] !== '/' &&
    !url.includes('\\') &&
    !Array.from(url).some((char) => {
      const codePoint = char.codePointAt(0) ?? 0;
      return codePoint <= 0x1f || codePoint === 0x7f;
    })
    ? url
    : fallback;
}

/** Returns an absolute browser-safe HTTP(S) URL, or an empty string when unsafe. */
function getSafeExternalUrl(url: string | null | undefined, baseUrl?: string): string {
  if (!url) {
    return '';
  }

  if (/\p{Cc}/u.test(url)) {
    return '';
  }
  const trimmed = url.trim();

  const isRelative = !/^[a-zA-Z][a-zA-Z\d+.-]*:/u.test(trimmed);
  if (isRelative) {
    if (!baseUrl || trimmed.startsWith('//') || trimmed.includes('\\')) {
      return '';
    }
    try {
      const segments = trimmed.split(/[/?#]/u);
      if (
        segments.some((segment) => {
          const decoded = decodeURIComponent(segment);
          return decoded === '.' || decoded === '..';
        })
      ) {
        return '';
      }
    } catch {
      return '';
    }
  }

  try {
    const parsed = new URL(trimmed, isRelative ? baseUrl : undefined);
    if (
      (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') ||
      parsed.username !== '' ||
      parsed.password !== ''
    ) {
      return '';
    }
    return parsed.href;
  } catch {
    return '';
  }
}

/** Resolves a generated-document storage key or validates an external presigned URL. */
function getSafeGeneratedDocumentUrl(url: string | null | undefined, baseUrl: string): string {
  if (url && !/^[a-zA-Z][a-zA-Z\d+.-]*:/u.test(url.trim()) && !url.trim().startsWith('rendered/')) {
    return '';
  }
  return getSafeExternalUrl(url, baseUrl);
}

/**
 * Sanitizes a URL to ensure it's safe to use in href attributes.
 * Returns an empty string if the URL is potentially dangerous.
 *
 * @param url - The URL to sanitize
 * @returns The sanitized URL or empty string if invalid
 */
function sanitizeUrl(url: string): string {
  if (!url) {
    return '';
  }

  const trimmed = url.trim();

  if (!isValidUrl(trimmed)) {
    return '';
  }

  return escapeHtml(trimmed);
}

export {
  escapeHtml,
  getSafeExternalUrl,
  getSafeGeneratedDocumentUrl,
  getSafeReturnUrl,
  isValidUrl,
  sanitizeHtml,
  sanitizeUrl,
};
