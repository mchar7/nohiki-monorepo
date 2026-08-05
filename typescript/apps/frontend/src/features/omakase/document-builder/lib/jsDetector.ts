/**
 * Client-side JavaScript Detection Utility
 *
 * This mirrors the server-side js_detector.py functionality to detect
 * JavaScript presence in HTML templates on the frontend.
 */

interface JsDetectionResult {
  hasJavaScript: boolean;
  detectedFeatures: string[];
}

interface PatternCheck {
  readonly regex: RegExp;
  readonly feature: string;
}

/** Regex patterns that indicate JS presence when matched against the full template. */
const TEMPLATE_PATTERNS: readonly PatternCheck[] = [
  { regex: /<script[^>]*>/iu, feature: 'script-tag' },
  { regex: /\s+on[a-z]+\s*=/iu, feature: 'event-handlers' },
  {
    regex: /(?:href|src|action|formaction)\s*=\s*["']?javascript:/iu,
    feature: 'javascript-protocol',
  },
  {
    regex: /<meta[^>]+http-equiv\s*=\s*["']?refresh["'][^>]*javascript:/iu,
    feature: 'meta-refresh-js',
  },
  { regex: /<(?:svg|g|rect|circle|path|text|image)[^>]*\s+on[a-z]+\s*=/iu, feature: 'svg-events' },
  { regex: /<script[^>]*type\s*=\s*["']module["'][^>]*>/iu, feature: 'module-script' },
  { regex: /on[a-z]+\s*=\s*["'][^"']*(?:function|=>|\{)[^"']*/iu, feature: 'inline-js-functions' },
];

/** DOM API patterns flagged only when found inside &lt;script&gt; blocks. */
const SCRIPT_CONTENT_PATTERNS: readonly RegExp[] = [
  /document\./iu,
  /window\./iu,
  /addEventListener/iu,
  /getElementById/iu,
  /querySelector/iu,
  /setTimeout/iu,
  /setInterval/iu,
];

/**
 * Matches template-level patterns (e.g. script tags, event handlers) and
 * returns all detected feature names.
 */
function matchTemplatePatterns(template: string): string[] {
  const features: string[] = [];
  for (const { regex, feature } of TEMPLATE_PATTERNS) {
    if (regex.test(template)) {
      features.push(feature);
    }
  }
  return features;
}

/**
 * Scans the contents of each &lt;script&gt; block for common DOM API calls.
 *
 * @returns `true` if any script block contains DOM manipulation patterns.
 */
function containsDomManipulation(template: string): boolean {
  const scriptContentRegex = /<script[^>]*>(?<scriptContent>[\s\S]*?)<\/script>/giu;
  let scriptMatch = scriptContentRegex.exec(template);
  while (scriptMatch !== null) {
    const [, scriptContent] = scriptMatch;
    if (scriptContent !== undefined) {
      for (const pattern of SCRIPT_CONTENT_PATTERNS) {
        if (pattern.test(scriptContent)) {
          return true;
        }
      }
    }
    scriptMatch = scriptContentRegex.exec(template);
  }
  return false;
}

/**
 * Detects JavaScript presence in an HTML template string.
 *
 * @param htmlTemplate - The HTML template content to analyze.
 * @returns Detection result with boolean flag and list of detected JS features.
 */
function detectJavaScript(htmlTemplate: string | null | undefined): JsDetectionResult {
  if (!htmlTemplate || typeof htmlTemplate !== 'string') {
    return { hasJavaScript: false, detectedFeatures: [] };
  }

  const detectedFeatures = matchTemplatePatterns(htmlTemplate);

  if (containsDomManipulation(htmlTemplate)) {
    detectedFeatures.push('dom-manipulation');
  }

  return {
    hasJavaScript: detectedFeatures.length > 0,
    detectedFeatures,
  };
}

/**
 * Determines if the JavaScript warning should be shown
 * @param htmlTemplate The HTML template content to check
 * @returns True if warning should be shown
 */
function shouldShowJsWarning(htmlTemplate: string): boolean {
  const detection = detectJavaScript(htmlTemplate);

  // Show warning if template contains JavaScript (regardless of declaration)
  // The user should be able to choose rendering method
  return detection.hasJavaScript;
}

export { detectJavaScript, shouldShowJsWarning };
