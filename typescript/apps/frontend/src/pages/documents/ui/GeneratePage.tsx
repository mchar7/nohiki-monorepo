import { useSearch } from '@tanstack/react-router';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/shared/ui/PageHeader.tsx';
import { GenerationWizard } from './wizard/GenerationWizard.tsx';

function GeneratePage(): JSX.Element {
  const { t } = useTranslation('documents');
  const search: { templateId?: string } = useSearch({ strict: false });

  return (
    <div className="space-y-6">
      <PageHeader title={t('wizard.title')} backTo="/documents" preferHistory={true} />
      <GenerationWizard preselectedTemplateId={search.templateId} />
    </div>
  );
}

export { GeneratePage };
