import { describe, expect } from 'vitest';
import { detectJavaScript, shouldShowJsWarning } from './jsDetector.ts';

describe('detectJavaScript - script tags and modules', () => {
  test('detects basic script tags', () => {
    const html = '<html><head><script>console.log("test");</script></head></html>';
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(true);
    expect(result.detectedFeatures).toContain('script-tag');
  });

  test('detects module scripts', () => {
    const html = '<script type="module">import { test } from "./test.js";</script>';
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(true);
    expect(result.detectedFeatures).toContain('script-tag');
    expect(result.detectedFeatures).toContain('module-script');
  });

  test('detects DOM manipulation in script content', () => {
    const html = '<script>document.getElementById("test").innerHTML = "hello";</script>';
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(true);
    expect(result.detectedFeatures).toContain('script-tag');
    expect(result.detectedFeatures).toContain('dom-manipulation');
  });
});

describe('detectJavaScript - event handlers and protocols', () => {
  test('detects event handlers', () => {
    const html = '<button onclick="alert(\'test\')">Click me</button>';
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(true);
    expect(result.detectedFeatures).toContain('event-handlers');
  });

  test('detects javascript: protocol', () => {
    const html = '<a href="javascript:alert(\'test\')">Link</a>';
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(true);
    expect(result.detectedFeatures).toContain('javascript-protocol');
  });

  test('detects SVG event handlers', () => {
    const html = '<svg><rect onclick="alert(\'test\')" /></svg>';
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(true);
    expect(result.detectedFeatures).toContain('svg-events');
  });

  test('detects inline JS functions in event handlers', () => {
    const html = '<button onclick="function test() { alert(\'hello\'); } test();">Click</button>';
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(true);
    expect(result.detectedFeatures).toContain('event-handlers');
    expect(result.detectedFeatures).toContain('inline-js-functions');
  });

  test('detects arrow functions in event handlers', () => {
    const html = '<button onclick="() => alert(\'test\')">Click</button>';
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(true);
    expect(result.detectedFeatures).toContain('event-handlers');
    expect(result.detectedFeatures).toContain('inline-js-functions');
  });
});

describe('detectJavaScript - edge cases', () => {
  test('handles empty or invalid input', () => {
    expect(detectJavaScript('').hasJavaScript).toBe(false);
    expect(detectJavaScript(null).hasJavaScript).toBe(false);
    expect(detectJavaScript(undefined).hasJavaScript).toBe(false);
  });

  test('does not detect JavaScript in plain HTML', () => {
    const html = '<html><body><h1>Hello World</h1><p>This is plain HTML</p></body></html>';
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(false);
    expect(result.detectedFeatures).toHaveLength(0);
  });
});

describe('detectJavaScript - multiple features', () => {
  test('detects multiple JavaScript features', () => {
    const html = `
      <html>
        <head>
          <script type="module">
            import { test } from "./test.js";
            document.addEventListener('load', () => {
              console.log('loaded');
            });
          </script>
        </head>
        <body>
          <button onclick="alert('test')">Click</button>
          <svg><circle onmouseover="highlight(this)" /></svg>
        </body>
      </html>
    `;
    const result = detectJavaScript(html);

    expect(result.hasJavaScript).toBe(true);
    expect(result.detectedFeatures).toContain('script-tag');
    expect(result.detectedFeatures).toContain('module-script');
    expect(result.detectedFeatures).toContain('dom-manipulation');
    expect(result.detectedFeatures).toContain('event-handlers');
    expect(result.detectedFeatures).toContain('svg-events');
  });
});

describe('shouldShowJsWarning', () => {
  test('returns true when JavaScript is detected', () => {
    const html = '<script>console.log("test");</script>';
    expect(shouldShowJsWarning(html)).toBe(true);
  });

  test('returns false when no JavaScript is detected', () => {
    const html = '<html><body><h1>Plain HTML</h1></body></html>';
    expect(shouldShowJsWarning(html)).toBe(false);
  });
});
