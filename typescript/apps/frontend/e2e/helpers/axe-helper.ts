import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

interface AxeViolationNode {
  html: string;
}

interface AxeViolation {
  id: string;
  impact?: string | null;
  description: string;
  nodes: AxeViolationNode[];
}

/** Format axe violations for readable test output. */
function formatViolations(violations: AxeViolation[]): string {
  return violations
    .map(
      (v) =>
        `[${v.impact}] ${v.id}: ${v.description}\n  ${v.nodes.map((n) => n.html).join('\n  ')}`,
    )
    .join('\n\n');
}

/**
 * Run axe accessibility scan on the current page.
 * Fails the test if any critical or serious violations are found.
 * Moderate/minor violations are logged as warnings.
 */
export async function expectNoA11yViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  const critical = results.violations.filter(
    (v) => v.impact === 'critical' || v.impact === 'serious',
  );

  expect(critical, `Accessibility violations found:\n${formatViolations(critical)}`).toHaveLength(
    0,
  );
}
