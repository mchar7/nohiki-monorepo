import { describe, expect } from 'vitest';
import {
  escapeHtml,
  getSafeExternalUrl,
  getSafeReturnUrl,
  isValidUrl,
  sanitizeHtml,
  sanitizeUrl,
} from './sanitization.ts';

describe('escapeHtml', () => {
  test('escapes ampersand', () => {
    expect(escapeHtml('A & B')).toBe('A &amp; B');
  });

  test('escapes less than', () => {
    expect(escapeHtml('A < B')).toBe('A &lt; B');
  });

  test('escapes greater than', () => {
    expect(escapeHtml('A > B')).toBe('A &gt; B');
  });

  test('escapes double quotes', () => {
    expect(escapeHtml('Say "hello"')).toBe('Say &quot;hello&quot;');
  });

  test('escapes single quotes', () => {
    expect(escapeHtml("It's fine")).toBe('It&#x27;s fine');
  });

  test('escapes forward slash', () => {
    expect(escapeHtml('a/b')).toBe('a&#x2F;b');
  });

  test('escapes backticks', () => {
    expect(escapeHtml('use `code`')).toBe('use &#x60;code&#x60;');
  });

  test('escapes equals sign', () => {
    expect(escapeHtml('a=b')).toBe('a&#x3D;b');
  });

  test('escapes multiple special characters', () => {
    expect(escapeHtml('<script>alert("XSS")</script>')).toBe(
      '&lt;script&gt;alert(&quot;XSS&quot;)&lt;&#x2F;script&gt;',
    );
  });

  test('returns empty string for empty input', () => {
    expect(escapeHtml('')).toBe('');
  });

  test('returns empty string for null-ish input', () => {
    expect(escapeHtml(null)).toBe('');
    expect(escapeHtml(undefined)).toBe('');
  });

  test('leaves safe text unchanged', () => {
    expect(escapeHtml('Hello World')).toBe('Hello World');
  });
});

describe('sanitizeHtml', () => {
  test('allows safe tags', () => {
    expect(sanitizeHtml('<p>Hello</p>')).toBe('<p>Hello</p>');
    expect(sanitizeHtml('<b>Bold</b>')).toBe('<b>Bold</b>');
    expect(sanitizeHtml('<i>Italic</i>')).toBe('<i>Italic</i>');
    expect(sanitizeHtml('<strong>Strong</strong>')).toBe('<strong>Strong</strong>');
    expect(sanitizeHtml('<em>Emphasis</em>')).toBe('<em>Emphasis</em>');
  });

  test('allows list tags', () => {
    expect(sanitizeHtml('<ul><li>Item</li></ul>')).toBe('<ul><li>Item</li></ul>');
    expect(sanitizeHtml('<ol><li>Item</li></ol>')).toBe('<ol><li>Item</li></ol>');
  });

  test('allows heading tags', () => {
    expect(sanitizeHtml('<h1>Title</h1>')).toBe('<h1>Title</h1>');
    expect(sanitizeHtml('<h2>Subtitle</h2>')).toBe('<h2>Subtitle</h2>');
    expect(sanitizeHtml('<h6>Small</h6>')).toBe('<h6>Small</h6>');
  });

  test('removes script tags', () => {
    expect(sanitizeHtml('<script>alert("XSS")</script>')).toBe('alert("XSS")');
  });

  test('removes iframe tags', () => {
    expect(sanitizeHtml('<iframe src="evil.com"></iframe>')).toBe('');
  });

  test('removes style tags', () => {
    expect(sanitizeHtml('<style>body{display:none}</style>')).toBe('body{display:none}');
  });

  test('removes img tags', () => {
    expect(sanitizeHtml('<img src="x" onerror="alert(1)">')).toBe('');
  });

  test('allows safe attributes on links', () => {
    expect(sanitizeHtml('<a href="https://example.com">Link</a>')).toBe(
      '<a href="https:&#x2F;&#x2F;example.com">Link</a>',
    );
  });

  test('removes dangerous attributes', () => {
    expect(sanitizeHtml('<p onclick="alert(1)">Text</p>')).toBe('<p>Text</p>');
    expect(sanitizeHtml('<div onmouseover="evil()">Content</div>')).toBe('<div>Content</div>');
  });

  test('allows class and id attributes', () => {
    expect(sanitizeHtml('<p class="my-class" id="my-id">Text</p>')).toBe(
      '<p class="my-class" id="my-id">Text</p>',
    );
  });

  test('returns empty string for empty input', () => {
    expect(sanitizeHtml('')).toBe('');
  });
});

describe('isValidUrl', () => {
  test('allows http URLs', () => {
    expect(isValidUrl('http://example.com')).toBe(true);
  });

  test('allows https URLs', () => {
    expect(isValidUrl('https://example.com')).toBe(true);
  });

  test('allows mailto URLs', () => {
    expect(isValidUrl('mailto:test@example.com')).toBe(true);
  });

  test('allows tel URLs', () => {
    expect(isValidUrl('tel:+1234567890')).toBe(true);
  });

  test('allows relative URLs starting with /', () => {
    expect(isValidUrl('/path/to/page')).toBe(true);
  });

  test('allows hash URLs', () => {
    expect(isValidUrl('#section')).toBe(true);
  });

  test('allows query URLs', () => {
    expect(isValidUrl('?param=value')).toBe(true);
  });

  test('rejects javascript: URLs', () => {
    expect(isValidUrl('javascript:alert(1)')).toBe(false);
  });

  test('rejects data: URLs', () => {
    expect(isValidUrl('data:text/html,<script>alert(1)</script>')).toBe(false);
  });

  test('rejects vbscript: URLs', () => {
    expect(isValidUrl('vbscript:msgbox("XSS")')).toBe(false);
  });

  test('is case insensitive for dangerous protocols', () => {
    expect(isValidUrl('JAVASCRIPT:alert(1)')).toBe(false);
    expect(isValidUrl('JavaScript:alert(1)')).toBe(false);
  });

  test('returns false for empty input', () => {
    expect(isValidUrl('')).toBe(false);
  });

  test('handles whitespace', () => {
    expect(isValidUrl('  https://example.com  ')).toBe(true);
  });

  test('allows relative paths without leading slash', () => {
    expect(isValidUrl('path/to/page')).toBe(true);
  });
});

describe('sanitizeUrl', () => {
  test('returns escaped safe URLs', () => {
    expect(sanitizeUrl('https://example.com?q=a&b=c')).toBe(
      'https:&#x2F;&#x2F;example.com?q&#x3D;a&amp;b&#x3D;c',
    );
  });

  test('returns empty string for dangerous URLs', () => {
    expect(sanitizeUrl('javascript:alert(1)')).toBe('');
  });

  test('returns empty string for empty input', () => {
    expect(sanitizeUrl('')).toBe('');
  });

  test('trims whitespace', () => {
    const result = sanitizeUrl('  https://example.com  ');
    expect(result).toContain('example.com');
  });

  test('escapes special characters in URLs', () => {
    const result = sanitizeUrl('https://example.com/<path>');
    expect(result).toContain('&lt;path&gt;');
  });
});

describe('getSafeExternalUrl', () => {
  test.each(['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', 'not a URL'])(
    'rejects unsafe or malformed URL %s',
    (url) => {
      expect(getSafeExternalUrl(url)).toBe('');
    },
  );

  test('preserves a valid HTTPS URL', () => {
    expect(getSafeExternalUrl('https://example.com/jobs/1?source=test')).toBe(
      'https://example.com/jobs/1?source=test',
    );
  });
});

describe('getSafeReturnUrl', () => {
  test.each([
    ['absolute URL', 'https://attacker.example/steal'],
    ['protocol-relative URL', '//attacker.example/steal'],
    ['backslash authority URL', '/\\attacker.example/steal'],
    ['embedded backslash', '/jobs\\attacker'],
    ['control character', '/jobs\n/admin'],
    ['DEL character', `/jobs${String.fromCodePoint(0x7f)}/admin`],
    ['oversized path', `/${'a'.repeat(2048)}`],
    ['empty path', ''],
  ])('rejects a %s', (_name, returnUrl) => {
    expect(getSafeReturnUrl(returnUrl)).toBe('/');
  });

  test('preserves a same-origin path, query, and fragment', () => {
    expect(getSafeReturnUrl('/jobs/matches?minScore=75&remote=true#results')).toBe(
      '/jobs/matches?minScore=75&remote=true#results',
    );
  });

  test('accepts the maximum 2048-character local path', () => {
    const returnUrl = `/${'a'.repeat(2047)}`;
    expect(getSafeReturnUrl(returnUrl)).toBe(returnUrl);
  });
});
