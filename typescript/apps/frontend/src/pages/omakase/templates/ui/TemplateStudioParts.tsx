import { ChevronDown, Code, FileText, PanelRightClose, PanelRightOpen } from 'lucide-react';
import type React from 'react';
import { type JSX, type LazyExoticComponent, lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/index.ts';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/ui/collapsible.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import type {
  ExtendedValidationIssue,
  OmakaseTemplateMetadata,
  PageSize,
  TemplateData,
} from '../model/index.ts';
import { SAMPLE_DATA } from '../model/sample-data.ts';
import { DynamicPreview } from './DynamicPreview.tsx';
import { MetadataForm } from './TemplateStudioMetadata.tsx';
import { ValidationIssuesList } from './TemplateStudioValidation.tsx';

interface CodeMirrorEditorProps {
  readonly value: string;
  readonly onChange?: (value: string) => void;
  readonly className?: string;
  readonly placeholder?: string;
}

const LazyCodeMirrorEditor: LazyExoticComponent<(props: CodeMirrorEditorProps) => JSX.Element> =
  lazy(() => import('./CodeMirrorEditor.tsx').then((m) => ({ default: m.CodeMirrorEditor })));

interface ResizablePanelGroupProps {
  readonly orientation: 'horizontal' | 'vertical';
  readonly className?: string;
  readonly children: React.ReactNode;
}

interface ResizablePanelProps {
  readonly defaultSize?: number;
  readonly minSize?: number;
  readonly maxSize?: number;
  readonly children: React.ReactNode;
}

interface ResizableHandleProps {
  readonly className?: string;
  readonly withHandle?: boolean;
}

const LazyResizablePanelGroup: LazyExoticComponent<
  (props: ResizablePanelGroupProps) => JSX.Element
> = lazy(() =>
  import('@/shared/ui/resizable.tsx').then((m) => ({ default: m.ResizablePanelGroup })),
);

const LazyResizablePanel: LazyExoticComponent<(props: ResizablePanelProps) => JSX.Element> = lazy(
  () => import('@/shared/ui/resizable.tsx').then((m) => ({ default: m.ResizablePanel })),
);

const LazyResizableHandle: LazyExoticComponent<(props: ResizableHandleProps) => JSX.Element> = lazy(
  () => import('@/shared/ui/resizable.tsx').then((m) => ({ default: m.ResizableHandle })),
);

/** Editor-sized skeleton shown while CodeMirror loads */
function EditorSkeleton(): JSX.Element {
  return (
    <div className="flex h-full flex-col gap-2 p-4">
      <div className="flex items-center gap-2">
        <Skeleton className="h-4 w-8" />
        <Skeleton className="h-4 w-full" />
      </div>
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="size-4/5" />
      <Skeleton className="w-full flex-1" />
    </div>
  );
}

/** Default size for each panel when two panes are shown (percent) */
const PANEL_DEFAULT_SIZE_HALF_PERCENT: number = 50;
/** Full-width panel size when preview is hidden (percent) */
const PANEL_DEFAULT_SIZE_FULL_PERCENT: number = 100;
/** Minimum panel width to prevent collapse (percent) */
const PANEL_MIN_SIZE_EDITOR_PERCENT: number = 30;
/** Minimum preview panel width (percent) */
const PANEL_MIN_SIZE_PREVIEW_PERCENT: number = 25;

// --- Editor sub-components ---

function EditorPanel({
  templateContent,
  onTemplateChange,
  validationIssues,
  headerLabel,
}: {
  readonly templateContent: string;
  readonly onTemplateChange: (content: string) => void;
  readonly validationIssues: readonly ExtendedValidationIssue[];
  readonly headerLabel: string;
}): JSX.Element {
  return (
    <>
      <div className="flex h-10 shrink-0 items-center gap-2 border-b bg-muted/20 px-4">
        <Code className="size-4 text-muted-foreground" />
        <span className="font-medium text-sm">{headerLabel}</span>
      </div>
      <div className="flex-1 overflow-hidden bg-card">
        <Suspense fallback={<EditorSkeleton />}>
          <LazyCodeMirrorEditor value={templateContent} onChange={onTemplateChange} />
        </Suspense>
      </div>
      <ValidationIssuesList issues={validationIssues} />
    </>
  );
}

// --- Preview toggle ---

function PreviewToggleButton({
  isOpen,
  onToggle,
  openLabel,
  closeLabel,
}: {
  readonly isOpen: boolean;
  readonly onToggle: () => void;
  readonly openLabel: string;
  readonly closeLabel: string;
}): JSX.Element {
  const buttonAriaLabel = isOpen ? closeLabel : openLabel;
  return (
    <button
      type="button"
      onClick={onToggle}
      className="absolute top-1/2 right-3 z-10 flex h-12 w-6 -translate-y-1/2 items-center justify-center rounded-l-md border border-r-0 bg-background text-muted-foreground shadow-sm transition-colors hover:bg-muted/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:right-4"
      aria-label={buttonAriaLabel}
    >
      {isOpen ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
    </button>
  );
}

// --- Editor content area (resizable panels) ---

function EditorContentArea({
  templateContent,
  onTemplateChange,
  validationIssues,
  isSinglePane,
  previewOpen,
  pageSize,
  isBackendAvailable,
  editorLabel,
  previewTitle,
  templateData,
  editorOverride,
}: {
  readonly templateContent: string;
  readonly onTemplateChange: (content: string) => void;
  readonly validationIssues: readonly ExtendedValidationIssue[];
  readonly isSinglePane: boolean;
  readonly previewOpen: boolean;
  readonly pageSize: PageSize;
  readonly isBackendAvailable: boolean;
  readonly editorLabel: string;
  readonly previewTitle: string;
  readonly templateData?: TemplateData | undefined;
  readonly editorOverride?: React.ReactNode | undefined;
}): JSX.Element {
  const offlineErrorHandler = isBackendAvailable
    ? undefined
    : (): void => {
        /* offline: swallow preview errors */
      };

  if (isSinglePane) {
    return (
      <div className="flex h-full flex-col">
        {editorOverride ?? (
          <EditorPanel
            templateContent={templateContent}
            onTemplateChange={onTemplateChange}
            validationIssues={validationIssues}
            headerLabel={editorLabel}
          />
        )}
      </div>
    );
  }

  return (
    <Suspense fallback={<Skeleton className="h-full w-full" />}>
      <LazyResizablePanelGroup orientation="horizontal" className="h-full">
        <LazyResizablePanel
          defaultSize={
            previewOpen ? PANEL_DEFAULT_SIZE_HALF_PERCENT : PANEL_DEFAULT_SIZE_FULL_PERCENT
          }
          minSize={PANEL_MIN_SIZE_EDITOR_PERCENT}
        >
          <div className="flex h-full flex-col rounded-l-lg bg-card">
            {editorOverride ?? (
              <EditorPanel
                templateContent={templateContent}
                onTemplateChange={onTemplateChange}
                validationIssues={validationIssues}
                headerLabel={editorLabel}
              />
            )}
          </div>
        </LazyResizablePanel>
        {previewOpen ? (
          <>
            <LazyResizableHandle className="w-1 bg-border/50 transition-colors hover:bg-primary/50" />
            <LazyResizablePanel
              defaultSize={PANEL_DEFAULT_SIZE_HALF_PERCENT}
              minSize={PANEL_MIN_SIZE_PREVIEW_PERCENT}
            >
              <div className="h-full rounded-r-lg bg-card">
                <DynamicPreview
                  pageSize={pageSize}
                  templateData={templateData ?? SAMPLE_DATA}
                  title={previewTitle}
                  className="h-full"
                  onError={offlineErrorHandler}
                />
              </div>
            </LazyResizablePanel>
          </>
        ) : null}
      </LazyResizablePanelGroup>
    </Suspense>
  );
}

function MetadataPanel({
  settingsOpen,
  onSettingsOpenChange,
  metadata,
  onMetadataChange,
  onPageSizeChange,
}: {
  readonly settingsOpen: boolean;
  readonly onSettingsOpenChange: (open: boolean) => void;
  readonly metadata: OmakaseTemplateMetadata;
  readonly onMetadataChange: (metadata: OmakaseTemplateMetadata) => void;
  readonly onPageSizeChange: (pageSize: PageSize) => void;
}): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');

  return (
    <div className="mx-3 mt-3 sm:mx-4 sm:mt-4">
      <Collapsible open={settingsOpen} onOpenChange={onSettingsOpenChange}>
        <div className="rounded-lg border bg-muted/5 shadow-sm">
          <CollapsibleTrigger asChild={true}>
            <button
              type="button"
              className="flex w-full items-center justify-between rounded-t-lg bg-muted/20 px-4 py-3 transition-colors hover:bg-muted/40"
            >
              <div className="flex items-center gap-3">
                <FileText className="size-4 text-muted-foreground" aria-hidden="true" />
                <span className="font-medium text-sm">{t('panels.metadata')}</span>
              </div>
              <ChevronDown
                className={cn(
                  'size-4 text-muted-foreground transition-transform duration-200',
                  !settingsOpen && '-rotate-90',
                )}
                aria-hidden="true"
              />
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="border-t bg-card/50 px-4 py-4 sm:px-6 sm:py-5">
              <MetadataForm
                metadata={metadata}
                onMetadataChange={onMetadataChange}
                onPageSizeChange={onPageSizeChange}
              />
            </div>
          </CollapsibleContent>
        </div>
      </Collapsible>
    </div>
  );
}

export { EditorContentArea, MetadataPanel, PreviewToggleButton };
// Re-export sub-components so existing consumers keep working via single import

export { ValidationBadges } from './TemplateStudioValidation.tsx';
