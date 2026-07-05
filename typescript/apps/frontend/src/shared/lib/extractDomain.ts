const WWW_PREFIX_RE = /^www\./u;

/**
 * Extracts the hostname from a URL string, stripping the `www.` prefix.
 * Returns null for null input or unparseable URLs.
 */
function extractDomainFromUrl(url: string | null): string | null {
  if (!url) {
    return null;
  }

  try {
    const { hostname } = new URL(url);
    return hostname.replace(WWW_PREFIX_RE, '');
  } catch {
    return null;
  }
}

export { extractDomainFromUrl };
