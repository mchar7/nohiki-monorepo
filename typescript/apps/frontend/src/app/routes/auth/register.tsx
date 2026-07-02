import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { Register } from '@/pages/auth/index.ts';
import { FeatureErrorBoundary } from '@/shared/ui/feature-error-boundary.tsx';

const Route: AnyRoute = createFileRoute('/auth/register')({
  component: RegisterPage,
});

function RegisterPage(): JSX.Element {
  return (
    <FeatureErrorBoundary featureKey="auth">
      <Register />
    </FeatureErrorBoundary>
  );
}

export { Route };
