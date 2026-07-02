import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type ZodTypeAny, z } from 'zod';
import { OAuthCallbackPage } from '@/features/auth/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';

const callbackSearchSchema: ZodTypeAny = z.object({
  success: z.string().optional(),
  error: z.string().optional(),
  provider: z.string().optional(),
  returnUrl: z.string().optional(),
});

const Route: AnyRoute = createFileRoute('/auth/callback')({
  validateSearch: callbackSearchSchema,
  component: OAuthCallbackWrappedPage,
});

function OAuthCallbackWrappedPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="auth">
      <OAuthCallbackPage />
    </FeatureErrorBoundary>
  );
}

export { Route };
