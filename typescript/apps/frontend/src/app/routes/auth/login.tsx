import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type ZodTypeAny, z } from 'zod';
import { Login } from '@/pages/auth/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';

const authSearchSchema: ZodTypeAny = z.object({
  returnUrl: z.string().optional(),
});

const Route: AnyRoute = createFileRoute('/auth/login')({
  validateSearch: authSearchSchema,
  component: AuthLoginPage,
});

function AuthLoginPage(): JSX.Element {
  const { returnUrl } = Route.useSearch();
  return (
    <FeatureErrorBoundary featureKey="auth">
      <Login returnUrl={returnUrl} />
    </FeatureErrorBoundary>
  );
}

export { Route };
