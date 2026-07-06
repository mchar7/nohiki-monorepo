import type { ErrorComponentProps } from '@tanstack/react-router';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from './button.tsx';
import { Card, CardContent, CardHeader, CardTitle } from './card.tsx';

/**
 * Route-level error fallback for TanStack Router's `errorComponent` prop.
 *
 * Catches errors during route transitions (loader failures, etc.),
 * complementing FeatureErrorBoundary which catches render-time errors.
 */
function RouteErrorFallback({ reset }: ErrorComponentProps): JSX.Element {
  const { t } = useTranslation('common');

  return (
    <div className="flex h-full items-center justify-center p-8">
      <Card className="w-full max-w-md text-center">
        <CardHeader>
          <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-full bg-destructive/10">
            <AlertTriangle className="size-6 text-destructive" aria-hidden="true" />
          </div>
          <CardTitle className="text-lg">{t('errors.generic')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">{t('errorBoundary.description')}</p>
          <Button onClick={reset} variant="outline" size="sm" className="gap-2">
            <RefreshCw className="size-4" aria-hidden="true" />
            {t('actions.tryAgain')}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

export { RouteErrorFallback };
