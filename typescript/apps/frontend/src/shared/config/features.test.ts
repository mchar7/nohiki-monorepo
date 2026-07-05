import { render } from '@testing-library/react';
import type { JSX } from 'react';
import React from 'react';
import { describe, expect } from 'vitest';
import { featureFlags, isFeatureEnabled, useFeatureFlag, withFeatureFlag } from './features.ts';

describe('featureFlags', () => {
  test('has expected feature flags', () => {
    expect(featureFlags).toHaveProperty('omakase');
    expect(featureFlags).toHaveProperty('jobBoard');
    expect(featureFlags).toHaveProperty('schedules');
    expect(featureFlags).toHaveProperty('messaging');
    expect(featureFlags).toHaveProperty('auth');
    expect(featureFlags).toHaveProperty('experimentalTemplateEditor');
    expect(featureFlags).toHaveProperty('experimentalPdfViewer');
    expect(featureFlags).toHaveProperty('experimentalThemes');
    expect(featureFlags).toHaveProperty('debugMode');
    expect(featureFlags).toHaveProperty('performanceMetrics');
    expect(featureFlags).toHaveProperty('apiLogging');
  });

  test('has boolean values for all flags', () => {
    for (const key of Object.keys(featureFlags)) {
      expect(typeof featureFlags[key as keyof typeof featureFlags]).toBe('boolean');
    }
  });
});

describe('isFeatureEnabled', () => {
  test('returns boolean for omakase feature', () => {
    expect(typeof isFeatureEnabled('omakase')).toBe('boolean');
  });

  test('returns boolean for auth feature', () => {
    expect(typeof isFeatureEnabled('auth')).toBe('boolean');
  });

  test('returns boolean for experimental features', () => {
    expect(typeof isFeatureEnabled('experimentalTemplateEditor')).toBe('boolean');
    expect(typeof isFeatureEnabled('experimentalPdfViewer')).toBe('boolean');
    expect(typeof isFeatureEnabled('experimentalThemes')).toBe('boolean');
  });
});

describe('useFeatureFlag', () => {
  test('returns feature flag value for omakase', () => {
    expect(useFeatureFlag('omakase')).toBe(isFeatureEnabled('omakase'));
  });

  test('returns debug mode flag', () => {
    expect(useFeatureFlag('debugMode')).toBe(isFeatureEnabled('debugMode'));
  });
});

describe('withFeatureFlag - enabled feature', () => {
  const TestComponent = (): JSX.Element =>
    React.createElement('div', { 'data-testid': 'test' }, 'Test Component');

  test('renders component when omakase is enabled', () => {
    const WrappedComponent = withFeatureFlag('omakase', TestComponent);
    const { container } = render(React.createElement(WrappedComponent));

    // omakase is enabled by default in test env
    expect(container.textContent).toContain('Test Component');
  });
});

describe('withFeatureFlag - disabled feature', () => {
  const TestComponent = (): JSX.Element =>
    React.createElement('div', { 'data-testid': 'test' }, 'Test Component');
  const FallbackComponent = (): JSX.Element =>
    React.createElement('div', { 'data-testid': 'fallback' }, 'Fallback');

  test('renders fallback when experimentalPdfViewer is disabled', () => {
    const WrappedComponent = withFeatureFlag(
      'experimentalPdfViewer',
      TestComponent,
      FallbackComponent,
    );
    const { container } = render(React.createElement(WrappedComponent));

    // experimentalPdfViewer is disabled by default
    expect(container.textContent).toContain('Fallback');
  });

  test('renders null when experimentalPdfViewer is disabled and no fallback', () => {
    const WrappedComponent = withFeatureFlag('experimentalPdfViewer', TestComponent);
    const { container } = render(React.createElement(WrappedComponent));

    // experimentalPdfViewer is disabled by default
    expect(container.textContent).toBe('');
  });
});
