import type { ZodError } from 'zod';
import type { RenderMethod } from './useTemplateJsWarning.ts';

interface GeneratingSetters {
  readonly setIsGenerating: (v: boolean) => void;
  readonly setIsGeneratingPreview: (v: boolean) => void;
  readonly setIsGeneratingImage: (v: boolean) => void;
}

interface UsePreviewPaneOptions {
  template?: string | undefined;
  templateId?: string | undefined;
  data?: Record<string, unknown> | undefined;
  datasetId?: string | undefined;
  cachedHtmlData?: string | undefined;
  onHtmlGenerated?: ((datasetId: string, htmlData: string) => void) | undefined;
  onHtmlCleared?: ((datasetId: string) => void) | undefined;
}

interface JsWarningState {
  showWarning: boolean;
  templateName: string;
  templateVersion: string;
  reason: string | undefined;
  handleJsChoice: (method: RenderMethod, remember: boolean) => void;
  checkJsRequirement: (templateId?: string, htmlTemplate?: string) => boolean;
}

interface UsePreviewPaneReturn {
  htmlUrl: string | null;
  imageUrl: string | null;
  isGenerating: boolean;
  isGeneratingPreview: boolean;
  isGeneratingImage: boolean;
  hasPreview: boolean;
  error: string | null;
  clearError: () => void;
  generatePreview: () => Promise<void>;
  clearPreview: () => void;
  revokeHtmlUrl: () => void;
  revokeImageUrl: () => void;
  downloadPdf: () => Promise<void>;
  renderMethod: RenderMethod;
  setRenderMethod: (method: RenderMethod) => void;
  jsWarning: JsWarningState;
}

interface ObjectUrlState {
  htmlUrl: string | null;
  imageUrl: string | null;
  revokeHtmlUrl: () => void;
  revokeImageUrl: () => void;
  setHtmlUrl: (url: string | null) => void;
  setImageUrl: (url: string | null) => void;
  hasPreview: boolean;
}

interface GenerationParams {
  tvId: string;
  cleanedData: Record<string, unknown>;
  method: RenderMethod;
  generateHtml: (opts: {
    template_version_id: string;
    data: Record<string, unknown>;
  }) => Promise<string>;
  generateImage: (opts: {
    template_version_id: string;
    data: Record<string, unknown>;
  }) => Promise<string>;
  urls: ObjectUrlState;
  onHtmlGenerated: ((datasetId: string, htmlData: string) => void) | undefined;
  currentDatasetId: string | undefined;
}

interface PreviewCallbackParams {
  readonly templateVersionId: string | undefined;
  readonly templateId: string | undefined;
  readonly template: string | undefined;
  readonly data: Record<string, unknown>;
  readonly contentSchema: Record<string, unknown> | null | undefined;
  readonly renderMethod: RenderMethod;
  readonly datasetId: string | undefined;
  readonly urls: ObjectUrlState;
  readonly jsWarningHook: {
    checkJsRequirement: (templateId?: string, htmlTemplate?: string) => boolean;
  };
  readonly onHtmlGenerated: ((datasetId: string, htmlData: string) => void) | undefined;
  readonly t: (key: string) => string;
  readonly genSetters: GeneratingSetters;
  readonly abortControllerRef: { current: AbortController | null };
  readonly formatValidationErrorSummary: (error: ZodError) => string;
  readonly generateHtml: GenerationParams['generateHtml'];
  readonly generateImage: GenerationParams['generateImage'];
  readonly setError: (e: string | null) => void;
}

export type {
  GeneratingSetters,
  GenerationParams,
  JsWarningState,
  ObjectUrlState,
  PreviewCallbackParams,
  UsePreviewPaneOptions,
  UsePreviewPaneReturn,
};
