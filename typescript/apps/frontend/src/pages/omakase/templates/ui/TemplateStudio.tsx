import { CheckCircle, Code, Eye } from 'lucide-react';
import type { JSX } from 'react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useConnectivitySafe } from '@/shared/lib/contexts/index.ts';
import { useDocumentTitle, useIsNarrowerThan, useIsShortViewport } from '@/shared/lib/index.ts';
import { ConnectivityAwareButton } from '@/shared/ui/connectivity-aware-button.tsx';
import type { FloatingAction } from '@/shared/ui/floating-action-button.types.ts';
import { Tabs, TabsList, TabsTrigger } from '@/shared/ui/tabs.tsx';
import { useTemplateValidation } from '../lib/index.ts';
import type {
  EditorMode,
  ExtendedValidationIssue,
  OmakaseTemplateMetadata,
  PageSize,
  TemplateData,
  TemplateStudioState,
} from '../model/index.ts';
import { SAMPLE_DATA } from '../model/sample-data.ts';
import { TemplateStudioBody } from './TemplateStudioBody.tsx';
import { MetadataPanel, ValidationBadges } from './TemplateStudioParts.tsx';
import {
  DEFAULT_CONTENT_SCHEMA,
  DEFAULT_METADATA,
  DEFAULT_TEMPLATE,
  SINGLE_PANE_THRESHOLD_PX,
} from './templateStudioDefaults.ts';

/** Manages TemplateStudio template content and validation. */
function useTemplateContent(): {
  templateContent: string;
  templateMetadata: OmakaseTemplateMetadata;
  validationIssues: readonly ExtendedValidationIssue[];
  isValidating: boolean;
  errorCount: number;
  warningCount: number;
  validateTemplate: () => void;
  handleMetadataChange: (metadata: OmakaseTemplateMetadata) => void;
  handlePageSizeChange: (pageSize: PageSize) => void;
  handleTemplateChange: (content: string) => void;
} {
  const [templateContent, setTemplateContent] = useState(DEFAULT_TEMPLATE);
  const [templateMetadata, setTemplateMetadata] = useState(DEFAULT_METADATA);
  const {
    validationIssues,
    isValidating,
    errorCount,
    warningCount,
    validateTemplate,
    clearValidation,
  } = useTemplateValidation(templateContent);

  return {
    templateContent,
    templateMetadata,
    validationIssues,
    isValidating,
    errorCount,
    warningCount,
    validateTemplate,
    handleMetadataChange: (metadata: OmakaseTemplateMetadata) => setTemplateMetadata(metadata),
    handlePageSizeChange: (pageSize: PageSize) =>
      setTemplateMetadata((prev) => ({ ...prev, pageSize })),
    handleTemplateChange: (content: string) => {
      setTemplateContent(content);
      clearValidation();
    },
  };
}

function useTemplateStudioState(): TemplateStudioState {
  const { isBackendAvailable } = useConnectivitySafe();
  const content = useTemplateContent();

  const isSinglePane = useIsNarrowerThan(SINGLE_PANE_THRESHOLD_PX);
  const isShortViewport = useIsShortViewport();
  const [settingsOpen, setSettingsOpen] = useState(true);
  const [previewOpen, setPreviewOpen] = useState(true);
  const [mobilePreviewOpen, setMobilePreviewOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<EditorMode>('advanced');
  const [templateData, setTemplateData] = useState<TemplateData>({ ...SAMPLE_DATA });

  useEffect(() => {
    if (isShortViewport) {
      setSettingsOpen(false);
    }
  }, [isShortViewport]);

  return {
    ...content,
    isSinglePane,
    settingsOpen,
    setSettingsOpen,
    previewOpen,
    handleTogglePreview: () => setPreviewOpen((prev) => !prev),
    mobilePreviewOpen,
    setMobilePreviewOpen,
    isBackendAvailable,
    editorMode,
    setEditorMode,
    templateData,
    handleTemplateDataChange: setTemplateData,
    contentSchema: DEFAULT_CONTENT_SCHEMA,
  };
}

function EditorModeToggle({
  mode,
  onModeChange,
}: {
  readonly mode: EditorMode;
  readonly onModeChange: (mode: EditorMode) => void;
}): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');

  return (
    <Tabs
      value={mode}
      onValueChange={(v: string): void => onModeChange(v as EditorMode)}
      className="w-auto"
    >
      <TabsList aria-label={t('modes.label')}>
        <TabsTrigger value="simple">{t('modes.simple')}</TabsTrigger>
        <TabsTrigger value="advanced">{t('modes.advanced')}</TabsTrigger>
      </TabsList>
    </Tabs>
  );
}

function TemplateStudioHeader({ state }: { readonly state: TemplateStudioState }): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10">
          <Code className="size-5 text-primary" />
        </div>
        <div className="flex items-center gap-3">
          <h1 className="font-semibold text-lg">{t('title')}</h1>
          <ValidationBadges errorCount={state.errorCount} warningCount={state.warningCount} />
        </div>
      </div>
      <div className="flex items-center gap-3">
        <EditorModeToggle mode={state.editorMode} onModeChange={state.setEditorMode} />
        {state.isSinglePane ? null : (
          <ConnectivityAwareButton
            onClick={state.validateTemplate}
            disabled={state.isValidating || !state.templateContent.trim()}
            requiresConnection={true}
            offlineTooltip={t('tooltips.requiresConnection')}
          >
            {state.isValidating ? t('validation.validating') : t('validation.validate')}
          </ConnectivityAwareButton>
        )}
      </div>
    </header>
  );
}

function TemplateStudio(): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');
  useDocumentTitle(t('title'));
  const state = useTemplateStudioState();

  const offlineErrorHandler = state.isBackendAvailable
    ? undefined
    : (): void => {
        /* offline: swallow preview errors */
      };

  const fabActions: FloatingAction[] = [
    {
      id: 'preview',
      label: t('fab.openPreview'),
      icon: Eye,
      onClick: (): void => state.setMobilePreviewOpen(true),
      emphasis: true,
    },
    {
      id: 'validate',
      label: t('fab.validate'),
      icon: CheckCircle,
      onClick: state.validateTemplate,
      disabled: state.isValidating || !state.templateContent.trim() || !state.isBackendAvailable,
      loading: state.isValidating,
    },
  ];

  return (
    <div className="flex h-full flex-col bg-background">
      <TemplateStudioHeader state={state} />

      <MetadataPanel
        settingsOpen={state.settingsOpen}
        onSettingsOpenChange={state.setSettingsOpen}
        metadata={state.templateMetadata}
        onMetadataChange={state.handleMetadataChange}
        onPageSizeChange={state.handlePageSizeChange}
      />

      <TemplateStudioBody
        state={state}
        offlineErrorHandler={offlineErrorHandler}
        fabActions={fabActions}
      />
    </div>
  );
}

export { TemplateStudio };
