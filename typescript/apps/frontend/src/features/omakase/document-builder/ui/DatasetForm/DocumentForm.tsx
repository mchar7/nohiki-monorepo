import { PanelErrorState } from '@shared/ui/index.ts';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { useDocumentForm } from '../../lib/useDocumentForm.ts';
import { DatasetNotFound, TemplateNotFound } from './DocumentFormErrorStates.tsx';
import { renderObjectFields } from './ObjectFieldRenderer.tsx';

interface DocumentFormProps {
  readonly datasetId: string;
  readonly onDataChange?: (isDirty: boolean) => void;
}

export function DocumentForm({ datasetId, onDataChange }: DocumentFormProps): JSX.Element {
  const { t } = useTranslation('omakase.editor');
  const {
    dataset,
    template,
    resolvedSchema,
    isValid,
    validationErrors,
    form: { register, handleSubmit, control, errors, onSubmit },
  } = useDocumentForm({ datasetId, onDataChange });

  if (!dataset) {
    return <DatasetNotFound />;
  }

  if (!template) {
    return <TemplateNotFound />;
  }

  if (!isValid) {
    return (
      <PanelErrorState title={t('errors.invalidSchema')} error={validationErrors.join('\n')} />
    );
  }

  if (!resolvedSchema) {
    return (
      <PanelErrorState
        title={t('errors.schemaProcessingError')}
        error={t('errors.schemaProcessingErrorDescription')}
      />
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-2 sm:px-6">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <div className="space-y-4">
          {renderObjectFields({ baseName: '', schema: resolvedSchema, register, control, errors })}
        </div>
      </form>
    </div>
  );
}
