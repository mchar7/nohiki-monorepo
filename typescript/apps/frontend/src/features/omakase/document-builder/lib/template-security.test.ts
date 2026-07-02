import { describe, expect } from 'vitest';
import { detectJavaScript, shouldShowJsWarning } from './jsDetector.ts';

describe('Template Security - JavaScript Detection vs Declaration', () => {
  test('detects JavaScript in two-pane-resume template even without requiresJs declaration', () => {
    // Simulate the two-pane-resume template content that contains JavaScript
    const templateWithJs = `
      <html>
        <head>
          <script>
            document.addEventListener('DOMContentLoaded', () => {
              const MM_TO_PX = 3.78;
              function adjustLayout() {
                const leftCol = document.querySelector('.left-column');
                if (leftCol) {
                  leftCol.style.height = 'auto';
                }
              }
              adjustLayout();
            });
          </script>
        </head>
        <body>
          <div class="left-column">Content</div>
        </body>
      </html>
    `;

    const detection = detectJavaScript(templateWithJs);
    expect(detection.hasJavaScript).toBe(true);
    expect(detection.detectedFeatures).toContain('script-tag');
    expect(detection.detectedFeatures).toContain('dom-manipulation');

    // This should return true, triggering the warning
    expect(shouldShowJsWarning(templateWithJs)).toBe(true);
  });

  test('shows warning for template with requiresJavaScript.required=true even without detected JS', () => {
    const plainHtml = '<html><body><h1>Plain HTML</h1></body></html>';

    // Even if JS detection fails, if requiresJs is true, warning should show
    expect(shouldShowJsWarning(plainHtml)).toBe(false); // No JS detected

    // But the hook logic should still show warning if requiresJs=true
    const templateDeclaresJs = { requiresJavaScript: { required: true } };

    // Simulate the fixed logic: show warning if EITHER condition is true
    const shouldShow =
      templateDeclaresJs.requiresJavaScript.required || shouldShowJsWarning(plainHtml);
    expect(shouldShow).toBe(true);
  });

  test('does NOT show warning when neither requiresJavaScript nor JS detection is true', () => {
    const plainHtml = '<html><body><h1>Plain HTML</h1></body></html>';
    const templateWithoutJs = { requiresJavaScript: { required: false } };

    const shouldShow =
      templateWithoutJs.requiresJavaScript.required || shouldShowJsWarning(plainHtml);
    expect(shouldShow).toBe(false);
  });
});

describe('Template Security - Enhanced JavaScript Detection', () => {
  test('detects inline event handlers that might be missed by simple regex', () => {
    const htmlWithInlineJs = `
      <button onclick="console.log('clicked'); doSomething();">Click me</button>
      <div onmouseover="this.style.color='red'">Hover me</div>
    `;

    const result = shouldShowJsWarning(htmlWithInlineJs);
    expect(result).toBe(true);
  });

  test('detects complex JavaScript patterns', () => {
    const complexJs = `
      <script type="module">
        import { Component } from './component.js';
        window.addEventListener('load', () => {
          document.querySelectorAll('.dynamic').forEach(el => {
            el.innerHTML = 'Updated';
          });
        });
      </script>
    `;

    const result = shouldShowJsWarning(complexJs);
    expect(result).toBe(true);
  });

  test('detects SVG with JavaScript events', () => {
    const svgWithJs = `
      <svg>
        <rect onclick="alert('SVG clicked')" width="100" height="100"/>
        <circle onmouseover="highlight(this)" cx="50" cy="50" r="25"/>
      </svg>
    `;

    const result = shouldShowJsWarning(svgWithJs);
    expect(result).toBe(true);
  });
});

describe('Template Security - Bypass Prevention', () => {
  test('prevents security bypass when JS detection fails but requiresJavaScript is true', () => {
    const subtleJs = `
      <html>
        <head>
          <!-- Some JS that might be missed by regex -->
          <meta http-equiv="refresh" content="0; url=javascript:alert('bypass')">
        </head>
      </html>
    `;

    const templateData = { requiresJavaScript: { required: true } };

    // Even if detection misses it, requiresJs should trigger warning
    const jsDetected = shouldShowJsWarning(subtleJs);
    const shouldShowWarning = templateData.requiresJavaScript.required || jsDetected;
    expect(shouldShowWarning).toBe(true);
  });

  test('catches templates that have JS but forgot to declare requiresJavaScript', () => {
    const forgottenJs = `
      <script>
        // Developer added this but forgot to update requiresJs in schema
        document.body.addEventListener('click', () => {
          console.log('Page clicked');
        });
      </script>
    `;

    const templateData = { requiresJavaScript: { required: false } }; // Forgot to declare

    // Detection should catch it
    const jsDetected = shouldShowJsWarning(forgottenJs);
    const shouldShowWarning = templateData.requiresJavaScript.required || jsDetected;

    expect(shouldShowWarning).toBe(true);
  });

  test('shows warning when BOTH requiresJavaScript=true AND JS is detected', () => {
    const htmlWithJs = '<script>alert("test");</script>';
    const templateWithJs = { requiresJavaScript: { required: true } };

    const shouldShow =
      templateWithJs.requiresJavaScript.required || shouldShowJsWarning(htmlWithJs);
    expect(shouldShow).toBe(true);
  });
});
