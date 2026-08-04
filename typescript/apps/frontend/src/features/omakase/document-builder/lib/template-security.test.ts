import { describe, expect } from 'vitest';
import { detectJavaScript, shouldShowJsWarning } from './jsDetector.ts';

describe('Template Security - JavaScript Detection', () => {
  test('detects JavaScript in the two-pane-resume template', () => {
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
