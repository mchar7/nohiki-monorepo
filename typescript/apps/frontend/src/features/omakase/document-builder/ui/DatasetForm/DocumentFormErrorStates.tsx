import { PanelErrorState } from '@shared/ui/panel-error-state.tsx';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

function DatasetNotFound(): JSX.Element {
  const { t } = useTranslation('omakase.editor');

  return <PanelErrorState title={t('errors.loadFailed')} error={t('errors.datasetNotFound')} />;
}

function TemplateNotFound(): JSX.Element {
  const { t } = useTranslation('omakase.editor');

  return <PanelErrorState title={t('errors.loadFailed')} error={t('errors.templateNotFound')} />;
}

export { DatasetNotFound, TemplateNotFound };
