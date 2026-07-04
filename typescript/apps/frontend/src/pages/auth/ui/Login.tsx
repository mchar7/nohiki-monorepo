import { useNavigate } from '@tanstack/react-router';
import type { JSX } from 'react';

import { AuthPage } from '@/features/auth/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { getSafeReturnUrl } from '@/shared/lib/security/sanitization.ts';
import { handleNavigationPromise } from '@/shared/lib/utils/navigation.ts';
import { AuthLayout } from './AuthLayout';

interface LoginProps {
  readonly returnUrl?: string | undefined;
}

export function Login({ returnUrl }: LoginProps): JSX.Element {
  const safeReturnUrl = getSafeReturnUrl(returnUrl, '');
  const navigate = useNavigate();

  const handleSuccess = (): void => {
    if (safeReturnUrl) {
      handleNavigationPromise(navigate({ href: safeReturnUrl, replace: true }));
    } else {
      handleNavigationPromise(navigate({ to: ROUTE_PATHS.HOME, replace: true }));
    }
  };

  return (
    <AuthLayout>
      <AuthPage
        key="login"
        defaultMode="login"
        onSuccess={handleSuccess}
        returnUrl={safeReturnUrl}
      />
    </AuthLayout>
  );
}
