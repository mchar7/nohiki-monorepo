import type React from 'react';
import { type JSX, useId } from 'react';
import { useTranslation } from 'react-i18next';
import type { OmakaseTemplateMetadata, PageSize } from '../model/index.ts';
import { PageSizeEditor } from './PageSizeEditor.tsx';

function MetadataForm({
  metadata,
  onMetadataChange,
  onPageSizeChange,
}: {
  readonly metadata: OmakaseTemplateMetadata;
  readonly onMetadataChange: (metadata: OmakaseTemplateMetadata) => void;
  readonly onPageSizeChange: (pageSize: PageSize) => void;
}): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');
  const nameId = useId();
  const versionId = useId();
  const descriptionId = useId();

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    onMetadataChange({ ...metadata, name: e.target.value });
  };

  const handleVersionChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    onMetadataChange({ ...metadata, version: e.target.value });
  };

  const handleDescriptionChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    onMetadataChange({ ...metadata, description: e.target.value });
  };

  return (
    <div className="grid gap-4 sm:grid-cols-2 sm:gap-6 lg:grid-cols-4">
      <div className="sm:col-span-2 lg:col-span-1">
        <label htmlFor={nameId} className="mb-2 block font-medium text-sm">
          {t('metadata.name.label')}
        </label>
        <input
          id={nameId}
          type="text"
          value={metadata.name}
          onChange={handleNameChange}
          className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      <div>
        <label htmlFor={versionId} className="mb-2 block font-medium text-sm">
          {t('metadata.version.label')}
        </label>
        <input
          id={versionId}
          type="text"
          value={metadata.version}
          onChange={handleVersionChange}
          className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="1.0.0"
        />
      </div>

      <div className="lg:col-span-2">
        <span className="mb-2 block font-medium text-sm">{t('pageSize.title')}</span>
        <PageSizeEditor pageSize={metadata.pageSize} onChange={onPageSizeChange} compact={true} />
      </div>

      <div className="sm:col-span-2 lg:col-span-4">
        <label htmlFor={descriptionId} className="mb-2 block font-medium text-sm">
          {t('metadata.description.label')}
        </label>
        <input
          id={descriptionId}
          type="text"
          value={metadata.description}
          onChange={handleDescriptionChange}
          className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder={t('metadata.description.placeholder')}
        />
      </div>
    </div>
  );
}

export { MetadataForm };
