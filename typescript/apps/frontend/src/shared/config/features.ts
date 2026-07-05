import type { JSX } from 'react';
import React from 'react';
import { config } from './env.ts';

interface FeatureFlags {
  omakase: boolean;
  jobBoard: boolean;
  schedules: boolean;
  messaging: boolean;
  auth: boolean;
  authListings: boolean;
  experimentalTemplateEditor: boolean;
  experimentalPdfViewer: boolean;
  experimentalThemes: boolean;
  debugMode: boolean;
  performanceMetrics: boolean;
  apiLogging: boolean;
}

export const featureFlags: FeatureFlags = {
  omakase: config.features.omakase,
  jobBoard: config.features.jobBoard,
  schedules: config.features.schedules,
  messaging: config.features.messaging,
  auth: config.features.auth,
  authListings: config.features.authListings,
  experimentalTemplateEditor: false,
  experimentalPdfViewer: false,
  experimentalThemes: false,
  debugMode: config.app.isDevelopment,
  performanceMetrics: config.app.isDevelopment,
  apiLogging: config.app.isDevelopment,
};

export function isFeatureEnabled(feature: keyof FeatureFlags): boolean {
  return featureFlags[feature];
}

export function useFeatureFlag(feature: keyof FeatureFlags): boolean {
  return isFeatureEnabled(feature);
}

export function withFeatureFlag<P extends object>(
  feature: keyof FeatureFlags,
  Component: React.ComponentType<P>,
  FallbackComponent?: React.ComponentType<P>,
) {
  return function FeatureGatedComponent(props: P): JSX.Element | null {
    if (isFeatureEnabled(feature)) {
      return React.createElement(Component, props);
    }

    if (FallbackComponent) {
      return React.createElement(FallbackComponent, props);
    }

    return null;
  };
}
