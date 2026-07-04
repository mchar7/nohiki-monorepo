import { useNavigate } from '@tanstack/react-router';
import type { JSX } from 'react';

import { AuthPage } from '@/features/auth/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { handleNavigationPromise } from '@/shared/lib/utils/navigation.ts';
import { AuthLayout } from './AuthLayout';

export function Register(): JSX.Element {
  const navigate = useNavigate();

  const handleSuccess = (): void => {
    handleNavigationPromise(navigate({ to: ROUTE_PATHS.HOME, replace: true }));
  };

  return (
    <AuthLayout>
      <AuthPage key="register" defaultMode="register" onSuccess={handleSuccess} />
    </AuthLayout>
  );
}
