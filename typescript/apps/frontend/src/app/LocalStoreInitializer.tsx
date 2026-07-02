import type { JSX, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocalStoreInit } from '@/shared/lib';
import { PageLoading } from '@/shared/ui/page-loading.tsx';
import { PanelErrorState } from '@/shared/ui/panel-error-state.tsx';

function LocalStoreInitializer({ children }: { readonly children: ReactNode }): JSX.Element {
  const { t } = useTranslation('common');
  const { isInitializing, error } = useLocalStoreInit();

  const handleRetry = (): void => {
    globalThis.location.reload();
  };

  if (isInitializing) {
    return <PageLoading />;
  }

  if (error) {
    const errorMessage = error instanceof Error ? error.message : t('app.storeInitFailed');
    return (
      <PanelErrorState title={t('app.initFailed')} error={errorMessage} onRetry={handleRetry} />
    );
  }

  return <>{children}</>;
}

export { LocalStoreInitializer };
