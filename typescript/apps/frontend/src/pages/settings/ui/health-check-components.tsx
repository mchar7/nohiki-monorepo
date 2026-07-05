import type {
  HealthCheckResult,
  HealthResponse,
} from '@features/omakase/document-builder/index.ts';
import type { TFunction } from 'i18next';
import { CheckCircle, XCircle } from 'lucide-react';
import type { JSX } from 'react';
import { Alert, AlertDescription } from '@/shared/ui/alert.tsx';
import { Badge } from '@/shared/ui/badge.tsx';

const ComponentHealthDisplay = ({
  response,
  getStatusColor: statusColorFn,
  t,
}: {
  readonly response: HealthResponse;
  readonly getStatusColor: (status: string) => string;
  readonly t: TFunction<'settings'>;
}): JSX.Element | null => {
  const components = [
    { name: 'Database', status: response.database?.status },
    { name: 'Jinja Engine', status: response.jinja_engine?.status },
    { name: 'Gotenberg', status: response.gotenberg?.status },
  ].filter((c): c is { name: string; status: string } => c.status !== undefined);

  if (components.length === 0) {
    return null;
  }

  return (
    <div className="mt-2">
      <p className="mb-1 font-medium text-xs">{t('api.healthCheck.componentHealth')}</p>
      <div className="grid grid-cols-2 gap-2">
        {components.map((component) => (
          <div key={component.name} className="flex items-center justify-between text-xs">
            <span className="capitalize">{`${component.name}:`}</span>
            <Badge variant="outline" className={`text-xs ${statusColorFn(component.status)}`}>
              {component.status}
            </Badge>
          </div>
        ))}
      </div>
    </div>
  );
};

const SuccessAlert = ({
  healthCheck,
  getStatusColor: statusColorFn,
  t,
}: {
  readonly healthCheck: HealthCheckResult;
  readonly getStatusColor: (status: string) => string;
  readonly t: TFunction<'settings'>;
}): JSX.Element | null => {
  if (!healthCheck.response) {
    return null;
  }

  return (
    <Alert className="border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950">
      <CheckCircle className="size-4 text-green-600 dark:text-green-400" />
      <AlertDescription>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-medium">{t('api.connectionSuccess')}</span>
            {healthCheck.latency ? (
              <span className="text-muted-foreground text-xs">{`${healthCheck.latency}ms`}</span>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs">{t('api.healthCheck.serviceStatus')}</span>
            <Badge variant="outline" className={statusColorFn(healthCheck.response.status)}>
              {healthCheck.response.status.toUpperCase()}
            </Badge>
          </div>
          <ComponentHealthDisplay
            response={healthCheck.response}
            getStatusColor={statusColorFn}
            t={t}
          />
        </div>
      </AlertDescription>
    </Alert>
  );
};

const ErrorAlert = ({
  healthCheck,
  t,
}: {
  readonly healthCheck: HealthCheckResult;
  readonly t: TFunction<'settings'>;
}): JSX.Element => (
  <Alert variant="destructive">
    <XCircle className="size-4" />
    <AlertDescription>
      <div className="space-y-1">
        <span className="font-medium">{t('api.connectionFailed')}</span>
        <p className="text-xs">{healthCheck.error}</p>
        {healthCheck.latency ? (
          <p className="text-muted-foreground text-xs">
            {t('api.healthCheck.failedAfter', { latency: healthCheck.latency })}
          </p>
        ) : null}
      </div>
    </AlertDescription>
  </Alert>
);

const HealthCheckResults = ({
  healthCheck,
  getStatusColor: statusColorFn,
  t,
}: {
  readonly healthCheck: HealthCheckResult;
  readonly getStatusColor: (status: string) => string;
  readonly t: TFunction<'settings'>;
}): JSX.Element | null => {
  if (healthCheck.state === 'idle') {
    return null;
  }

  return (
    <div className="space-y-3">
      {healthCheck.state === 'success' && healthCheck.response ? (
        <SuccessAlert healthCheck={healthCheck} getStatusColor={statusColorFn} t={t} />
      ) : null}
      {healthCheck.state === 'error' ? <ErrorAlert healthCheck={healthCheck} t={t} /> : null}
    </div>
  );
};

export { HealthCheckResults };
