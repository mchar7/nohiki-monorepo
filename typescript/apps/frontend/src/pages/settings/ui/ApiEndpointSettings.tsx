import {
  type HealthCheckResult,
  useApiEndpointHealthCheck,
  useApiEndpointSettings,
} from '@features/omakase/document-builder/index.ts';
import type { TFunction } from 'i18next';
import { Globe, Loader2 } from 'lucide-react';
import type React from 'react';
import type { JSX } from 'react';
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { Label } from '@/shared/ui/label.tsx';
import { HealthCheckResults } from './health-check-components.tsx';
import { getStatusColor } from './health-check-status.ts';

/** Manages endpoint form state and actions for the settings panel. */
function useEndpointForm(): {
  endpoint: string;
  isCustomEndpoint: boolean;
  inputValue: string;
  setInputValue: (value: string) => void;
  hasUnsavedChanges: boolean;
  healthCheck: HealthCheckResult;
  validateUrl: (url: string) => boolean;
  handleTestConnection: () => Promise<void>;
  handleSave: () => Promise<void>;
  handleReset: () => void;
  endpointId: string;
  getStatusColor: (status: string) => string;
} {
  const { endpoint, isCustomEndpoint, resetToDefault, saveEndpoint } = useApiEndpointSettings();
  const { healthCheck, validateUrl, testConnection, resetHealthCheck } =
    useApiEndpointHealthCheck();

  const endpointId = useId();
  const [inputValue, setInputValue] = useState(endpoint);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  useEffect(() => {
    setInputValue(endpoint);
    setHasUnsavedChanges(false);
  }, [endpoint]);

  useEffect(() => {
    setHasUnsavedChanges(inputValue !== endpoint);
  }, [inputValue, endpoint]);

  return {
    endpoint,
    isCustomEndpoint,
    inputValue,
    setInputValue,
    hasUnsavedChanges,
    healthCheck,
    validateUrl,
    handleTestConnection: async () => {
      await testConnection(inputValue);
    },
    handleSave: async () => {
      const success = await testConnection(inputValue);
      if (success) {
        saveEndpoint(inputValue);
        setHasUnsavedChanges(false);
      }
    },
    handleReset: () => {
      resetToDefault();
      resetHealthCheck();
    },
    endpointId,
    getStatusColor,
  };
}

function ApiEndpointSettings(): JSX.Element {
  const { t } = useTranslation('settings');
  const form = useEndpointForm();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="size-5" />
          {t('api.title')}
        </CardTitle>
        <CardDescription>{t('api.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <CurrentEndpointStatus
          endpoint={form.endpoint}
          isCustomEndpoint={form.isCustomEndpoint}
          t={t}
        />
        <EndpointInput
          endpointId={form.endpointId}
          inputValue={form.inputValue}
          onInputChange={form.setInputValue}
          validateUrl={form.validateUrl}
          t={t}
        />
        <ActionButtons
          inputValue={form.inputValue}
          validateUrl={form.validateUrl}
          healthCheck={form.healthCheck}
          hasUnsavedChanges={form.hasUnsavedChanges}
          isCustomEndpoint={form.isCustomEndpoint}
          onTestConnection={form.handleTestConnection}
          onSave={form.handleSave}
          onReset={form.handleReset}
          t={t}
        />
        <HealthCheckResults
          healthCheck={form.healthCheck}
          getStatusColor={form.getStatusColor}
          t={t}
        />
        <HelpText t={t} />
      </CardContent>
    </Card>
  );
}

const CurrentEndpointStatus = ({
  endpoint,
  isCustomEndpoint,
  t,
}: {
  readonly endpoint: string;
  readonly isCustomEndpoint: boolean;
  readonly t: TFunction<'settings'>;
}): JSX.Element => (
  <div className="flex items-center justify-between rounded-lg bg-muted/50 p-3">
    <div>
      <p className="font-medium text-sm">{t('api.currentEndpoint.title')}</p>
      <p className="text-muted-foreground text-xs">{endpoint}</p>
    </div>
    <div className="flex items-center gap-2">
      {isCustomEndpoint ? (
        <Badge variant="secondary">{t('api.currentEndpoint.custom')}</Badge>
      ) : null}
      {isCustomEndpoint ? null : (
        <Badge variant="outline">{t('api.currentEndpoint.default')}</Badge>
      )}
    </div>
  </div>
);

function EndpointInput({
  endpointId,
  inputValue,
  onInputChange,
  validateUrl,
  t,
}: {
  readonly endpointId: string;
  readonly inputValue: string;
  readonly onInputChange: (value: string) => void;
  readonly validateUrl: (url: string) => boolean;
  readonly t: TFunction<'settings'>;
}): JSX.Element {
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>): void =>
    onInputChange(e.target.value);

  return (
    <div className="space-y-2">
      <Label htmlFor={endpointId}>{t('api.baseUrl.label')}</Label>
      <Input
        id={endpointId}
        type="url"
        placeholder={t('api.baseUrl.placeholder')}
        value={inputValue}
        onChange={handleChange}
        className={cn(!validateUrl(inputValue) && inputValue && 'border-destructive')}
      />
      {!validateUrl(inputValue) && inputValue ? (
        <p className="text-destructive text-xs">{t('api.baseUrl.invalidUrl')}</p>
      ) : null}
    </div>
  );
}

const ActionButtons = ({
  inputValue,
  validateUrl,
  healthCheck,
  hasUnsavedChanges,
  isCustomEndpoint,
  onTestConnection,
  onSave,
  onReset,
  t,
}: {
  readonly inputValue: string;
  readonly validateUrl: (url: string) => boolean;
  readonly healthCheck: HealthCheckResult;
  readonly hasUnsavedChanges: boolean;
  readonly isCustomEndpoint: boolean;
  readonly onTestConnection: () => void;
  readonly onSave: () => void;
  readonly onReset: () => void;
  readonly t: TFunction<'settings'>;
}): JSX.Element => (
  <div className="flex gap-2">
    <Button
      onClick={onTestConnection}
      disabled={!(inputValue && validateUrl(inputValue)) || healthCheck.state === 'checking'}
      variant="outline"
    >
      {healthCheck.state === 'checking' ? (
        <>
          <Loader2 className="mr-2 size-4 animate-spin" />
          {t('api.actions.testing')}
        </>
      ) : null}
      {healthCheck.state !== 'checking' ? t('api.actions.testConnection') : null}
    </Button>
    <Button
      onClick={onSave}
      disabled={
        !(hasUnsavedChanges && validateUrl(inputValue)) ||
        healthCheck.state === 'checking' ||
        healthCheck.state === 'error'
      }
    >
      {t('api.actions.saveEndpoint')}
    </Button>
    {isCustomEndpoint ? (
      <Button onClick={onReset} variant="outline">
        {t('api.actions.resetToDefault')}
      </Button>
    ) : null}
  </div>
);

const HelpText = ({ t }: { readonly t: TFunction<'settings'> }): JSX.Element => (
  <div className="space-y-1 text-muted-foreground text-xs">
    <p>{`• ${t('api.help.endpointHint')}`}</p>
    <p>{`• ${t('api.help.baseUrlHint')}`}</p>
    <p>{`• ${t('api.help.saveHint')}`}</p>
  </div>
);

export { ApiEndpointSettings };
