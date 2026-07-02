import { PanelHeader } from '@shared/ui/index.ts';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

export function DocumentFormHeader(): JSX.Element {
  const { t } = useTranslation('omakase.editor');
  return <PanelHeader title={t('form.title')} />;
}
