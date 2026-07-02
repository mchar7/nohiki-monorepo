import { type AnyRoute, createFileRoute } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type ZodTypeAny, z } from 'zod';
import { Login } from '@/pages/auth/index.ts';

const authSearchSchema: ZodTypeAny = z.object({
  returnUrl: z.string().optional(),
});

const Route: AnyRoute = createFileRoute('/auth/')({
  validateSearch: authSearchSchema,
  component: AuthIndexPage,
});

function AuthIndexPage(): JSX.Element {
  const { returnUrl } = Route.useSearch();
  return <Login returnUrl={returnUrl} />;
}

export { Route };
