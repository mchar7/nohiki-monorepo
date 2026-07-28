import { useNavigate, useSearch } from '@tanstack/react-router';
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSession } from '@/shared/api/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { getSafeReturnUrl, handleNavigationPromise } from '@/shared/lib/index.ts';
import { Alert, AlertDescription, AlertTitle } from '@/shared/ui/alert.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';

const LOADING_REDIRECT_TIMEOUT_MS: number = 5000;

type CallbackStatus = 'loading' | 'success' | 'error';

function OAuthCallbackPage(): JSX.Element {
  const { t } = useTranslation('auth');
  const navigate = useNavigate();
  const searchParams = useSearch({ from: '/auth/callback' });
  const { refetch: refreshSession } = useSession();

  const { error: errorCode, provider, returnUrl } = searchParams;
  const success = searchParams.success === 'true';

  const safeReturnUrl = getSafeReturnUrl(returnUrl);

  let status: CallbackStatus = 'loading';
  if (success) {
    status = 'success';
  } else if (errorCode) {
    status = 'error';
  }

  const errorMessage = resolveErrorMessage(errorCode, t);

  useOAuthRedirects(status, safeReturnUrl, refreshSession, navigate);

  const handleRetry = (): void => {
    handleNavigationPromise(navigate({ to: ROUTE_PATHS.AUTH.ROOT, replace: true }));
  };

  if (status === 'loading') {
    return <LoadingCard />;
  }

  if (status === 'success') {
    return <SuccessCard />;
  }

  return <ErrorCard provider={provider} errorMessage={errorMessage} onRetry={handleRetry} />;
}

function resolveErrorMessage(
  errorCode: string | undefined,
  t: ReturnType<typeof useTranslation<'auth'>>['t'],
): string | null {
  if (!errorCode) {
    return null;
  }
  switch (errorCode) {
    case 'access_denied':
      return t('oauth.errors.accessDenied', '');
    case 'state_mismatch':
      return t('oauth.errors.stateMismatch', '');
    case 'code_exchange_failed':
      return t('oauth.errors.codeExchangeFailed', '');
    case 'profile_fetch_failed':
      return t('oauth.errors.profileFetchFailed', '');
    case 'account_disabled':
      return t('oauth.errors.accountDisabled', '');
    default:
      return t('oauth.errors.serverError', '');
  }
}

function useOAuthRedirects(
  status: CallbackStatus,
  safeReturnUrl: string,
  refreshSession: () => Promise<unknown>,
  navigate: ReturnType<typeof useNavigate>,
): void {
  useEffect(() => {
    if (status !== 'success') return;

    let active = true;
    refreshSession()
      .then(() => {
        if (active) {
          handleNavigationPromise(navigate({ to: safeReturnUrl, replace: true }));
        }
      })
      .catch(() => undefined);
    return (): void => {
      active = false;
    };
  }, [status, safeReturnUrl, refreshSession, navigate]);

  useEffect(() => {
    if (status !== 'loading') {
      return;
    }
    const timeoutId = setTimeout(() => {
      handleNavigationPromise(navigate({ to: ROUTE_PATHS.AUTH.ROOT, replace: true }));
    }, LOADING_REDIRECT_TIMEOUT_MS);
    return (): void => clearTimeout(timeoutId);
  }, [status, navigate]);
}

function LoadingCard(): JSX.Element {
  const { t } = useTranslation('auth');
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <Loader2 className="mx-auto size-8 animate-spin text-primary" />
          <CardTitle className="mt-4">{t('oauth.callback.processing')}</CardTitle>
          <CardDescription>{t('oauth.callback.pleaseWait')}</CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}

function SuccessCard(): JSX.Element {
  const { t } = useTranslation('auth');
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CheckCircle2 className="mx-auto size-8 text-green-500" />
          <CardTitle className="mt-4">{t('oauth.callback.success')}</CardTitle>
          <CardDescription>{t('oauth.callback.redirecting')}</CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}

interface ErrorCardProps {
  readonly provider: string | undefined;
  readonly errorMessage: string | null;
  readonly onRetry: () => void;
}

function ErrorCard({ provider, errorMessage, onRetry }: ErrorCardProps): JSX.Element {
  const { t } = useTranslation('auth');
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t('oauth.callback.errorTitle')}</CardTitle>
          <CardDescription>
            {provider ? t('oauth.callback.errorDescription', { provider }) : null}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Alert variant="destructive">
            <AlertCircle className="size-4" />
            <AlertTitle>{t('oauth.callback.errorOccurred')}</AlertTitle>
            <AlertDescription>{errorMessage}</AlertDescription>
          </Alert>
          <Button onClick={onRetry} className="w-full">
            {t('oauth.callback.tryAgain')}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

export { OAuthCallbackPage };
