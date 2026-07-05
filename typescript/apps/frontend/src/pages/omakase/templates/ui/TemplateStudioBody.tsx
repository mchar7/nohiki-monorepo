import { type ContentSchema, TemplateFormMode } from '@features/omakase/document-builder';
import { Sparkles } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { FloatingActionButton } from '@/shared/ui/floating-action-button.tsx';
import type { FloatingAction } from '@/shared/ui/floating-action-button.types.ts';
import type { TemplateStudioState } from '../model/index.ts';
import { PreviewSheet } from './PreviewSheet.tsx';
import { EditorContentArea, PreviewToggleButton } from './TemplateStudioParts.tsx';

function TemplateStudioBody({
  state,
  offlineErrorHandler,
  fabActions,
}: {
  readonly state: TemplateStudioState;
  readonly offlineErrorHandler: (() => void) | undefined;
  readonly fabActions: FloatingAction[];
}): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');

  return (
    <>
      <div className="relative m-3 flex-1 sm:m-4">
        <div className="h-full overflow-hidden rounded-lg border bg-muted/5 shadow-sm">
          <EditorContentArea
            templateContent={state.templateContent}
            onTemplateChange={state.handleTemplateChange}
            validationIssues={state.validationIssues}
            isSinglePane={state.isSinglePane}
            previewOpen={state.previewOpen}
            pageSize={state.templateMetadata.pageSize}
            isBackendAvailable={state.isBackendAvailable}
            editorLabel={t('panels.htmlTemplate')}
            previewTitle={t('title')}
            templateData={state.templateData}
            editorOverride={
              state.editorMode === 'simple' ? (
                <TemplateFormMode
                  contentSchema={state.contentSchema as ContentSchema}
                  data={state.templateData}
                  onDataChange={state.handleTemplateDataChange}
                />
              ) : undefined
            }
          />
        </div>

        {state.isSinglePane ? null : (
          <PreviewToggleButton
            isOpen={state.previewOpen}
            onToggle={state.handleTogglePreview}
            openLabel={t('actions.showPanel')}
            closeLabel={t('actions.hidePanel')}
          />
        )}
      </div>

      <PreviewSheet
        open={state.mobilePreviewOpen}
        onOpenChange={state.setMobilePreviewOpen}
        pageSize={state.templateMetadata.pageSize}
        templateData={state.templateData}
        onError={offlineErrorHandler}
      />

      {state.isSinglePane ? (
        <FloatingActionButton
          actions={fabActions}
          triggerIcon={Sparkles}
          triggerLabel={t('fab.label')}
          closeOnScroll={true}
        />
      ) : null}
    </>
  );
}

export { TemplateStudioBody };
