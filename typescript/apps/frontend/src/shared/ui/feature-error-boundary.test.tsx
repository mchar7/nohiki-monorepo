import { render } from '@testing-library/react';
import type { JSX } from 'react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { axe } from 'vitest-axe';
import '@/test/axe-setup.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { FeatureErrorBoundary } from './feature-error-boundary.tsx';

/** Throws on render to trigger the error boundary fallback. */
function ThrowingChild(): JSX.Element {
  throw new Error('Test error');
}

describe('FeatureErrorBoundary - accessibility', () => {
  test('has no accessibility violations in error state', async () => {
    // Suppress React error boundary console noise
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const { container } = render(
      <I18nextProvider i18n={i18n}>
        <FeatureErrorBoundary featureKey="dashboard" showDetails={true}>
          <ThrowingChild />
        </FeatureErrorBoundary>
      </I18nextProvider>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();

    spy.mockRestore();
  });

  test('has no accessibility violations when children render normally', async () => {
    const { container } = render(
      <I18nextProvider i18n={i18n}>
        <FeatureErrorBoundary featureKey="dashboard">
          <p>Normal content</p>
        </FeatureErrorBoundary>
      </I18nextProvider>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
