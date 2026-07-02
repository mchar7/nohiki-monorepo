import type { JSX } from 'react';
import { useState } from 'react';
import type { TemplateResponse } from '@/shared/api';
import { useResizeObserver } from '@/shared/lib/index.ts';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/shared/ui/resizable.tsx';
import { useResponsiveEditor } from '../lib/useResponsiveEditor.ts';
import { useResponsiveSidebar } from '../lib/useResponsiveSidebar.ts';
import type { Dataset } from '../model/index.ts';
import { DocumentForm, DocumentFormHeader } from './DatasetForm/index.ts';
import { FloatingPreviewButton } from './FloatingPreviewButton.tsx';
import { FullscreenPreviewDialog } from './FullscreenPreviewDialog.tsx';
import { PreviewPane } from './PreviewPane/PreviewPane.tsx';

/** Form content with schema-driven editor and live preview. */
function FormContent({
  currentDataset,
  onDataChange,
  EmptyState,
}: {
  readonly currentDataset: Dataset | null;
  readonly onDataChange: (isDirty: boolean) => void;
  readonly EmptyState: React.ComponentType;
}): JSX.Element {
  return (
    <div className="flex-1 overflow-auto p-4">
      {currentDataset ? (
        <DocumentForm
          key={currentDataset.id}
          datasetId={currentDataset.id}
          onDataChange={onDataChange}
        />
      ) : (
        <EmptyState />
      )}
    </div>
  );
}

interface ResponsiveEditorProps {
  currentDataset: Dataset | null;
  currentTemplate: TemplateResponse | null;
  onDataChange: (isDirty: boolean) => void;
  onHtmlGenerated: (datasetId: string, htmlData: string) => void;
  onHtmlCleared: (datasetId: string) => void;
  EmptyState: React.ComponentType;
}

interface MobileEditorLayoutProps {
  readonly currentDataset: Dataset | null;
  readonly currentTemplate: TemplateResponse | null;
  readonly onDataChange: (isDirty: boolean) => void;
  readonly onHtmlGenerated: (datasetId: string, htmlData: string) => void;
  readonly onHtmlCleared: (datasetId: string) => void;
  readonly EmptyState: React.ComponentType;
  readonly editor: ReturnType<typeof useResponsiveEditor>;
  readonly onDialogClose: (open: boolean) => void;
}

function MobileEditorLayout({
  currentDataset,
  currentTemplate,
  onDataChange,
  onHtmlGenerated,
  onHtmlCleared,
  EmptyState,
  editor,
  onDialogClose,
}: MobileEditorLayoutProps): JSX.Element {
  return (
    <>
      <div className="flex h-full flex-col will-change-auto">
        <DocumentFormHeader />
        <FormContent
          currentDataset={currentDataset}
          onDataChange={onDataChange}
          EmptyState={EmptyState}
        />
      </div>

      {currentDataset && !editor.showMobilePreview ? (
        <FloatingPreviewButton
          onClick={editor.generatePreviewForDialog}
          isLoading={editor.isGeneratingForDialog}
        />
      ) : null}

      <FullscreenPreviewDialog
        open={editor.showMobilePreview}
        onOpenChange={onDialogClose}
        template={currentTemplate?.template_content ?? ''}
        data={currentDataset?.data}
        datasetId={currentDataset?.id}
        templateId={currentTemplate?.id}
        cachedHtmlData={editor.dialogHtmlData || currentDataset?.cachedHtmlData}
        onHtmlGenerated={onHtmlGenerated}
        onHtmlCleared={onHtmlCleared}
      />
    </>
  );
}

export function ResponsiveEditor({
  currentDataset,
  currentTemplate,
  onDataChange,
  onHtmlGenerated,
  onHtmlCleared,
  EmptyState,
}: Readonly<ResponsiveEditorProps>): JSX.Element {
  const [isFullscreen] = useState(false);
  const [previewContainerRef] = useResizeObserver<HTMLDivElement>();
  const [formContainerRef, formContainerSize] = useResizeObserver<HTMLDivElement>();

  const editor = useResponsiveEditor({ template: currentTemplate ?? undefined });
  const { isMobileDevice } = useResponsiveSidebar({
    formWidth: formContainerSize?.width,
    isEditorPage: true,
  });

  const handleDialogClose = (open: boolean): void => {
    editor.setShowMobilePreview(open);
    if (!open) {
      editor.setDialogHtmlData(null);
    }
  };

  if (isMobileDevice) {
    return (
      <MobileEditorLayout
        currentDataset={currentDataset}
        currentTemplate={currentTemplate}
        onDataChange={onDataChange}
        onHtmlGenerated={onHtmlGenerated}
        onHtmlCleared={onHtmlCleared}
        EmptyState={EmptyState}
        editor={editor}
        onDialogClose={handleDialogClose}
      />
    );
  }

  return (
    <ResizablePanelGroup orientation="horizontal" className="flex-1">
      <ResizablePanel defaultSize={50} minSize={25} maxSize={75}>
        <div ref={formContainerRef} className="flex h-full flex-col will-change-auto">
          <DocumentFormHeader />
          <FormContent
            currentDataset={currentDataset}
            onDataChange={onDataChange}
            EmptyState={EmptyState}
          />
        </div>
      </ResizablePanel>

      <ResizableHandle withHandle={true} />

      <ResizablePanel defaultSize={50} minSize={25}>
        <div ref={previewContainerRef} className="h-full will-change-auto">
          <PreviewPane
            template={currentTemplate?.template_content ?? ''}
            data={currentDataset?.data}
            datasetId={currentDataset?.id}
            templateId={currentTemplate?.id}
            cachedHtmlData={currentDataset?.cachedHtmlData}
            onHtmlGenerated={onHtmlGenerated}
            onHtmlCleared={onHtmlCleared}
            isFullscreen={isFullscreen}
            showHeader={true}
          />
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}
