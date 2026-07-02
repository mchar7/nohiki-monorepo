import { sanitizeData } from '@shared/lib/index.ts';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDocumentBuilderStore } from '../model/index.ts';
import type {
  ObjectUrlState,
  UsePreviewPaneOptions,
  UsePreviewPaneReturn,
} from './previewPaneHelpers.ts';
import {
  buildJsWarning,
  executePreviewCallback,
  loadCachedHtmlBlob,
  toErrorMessage,
} from './previewPaneHelpers.ts';
import { useDocumentOperations } from './useDocumentOperations.ts';
import { type RenderMethod, useTemplateJsWarning } from './useTemplateJsWarning.ts';
import { useValidationErrorFormatter } from './useValidationErrorFormatter.ts';

/** Manages object URL lifecycle for HTML and image previews. */
function useObjectUrls(cachedHtmlData: string | undefined): ObjectUrlState {
  const [htmlUrl, setHtmlUrl] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);

  const revokeHtmlUrl = () => {
    if (htmlUrl) {
      URL.revokeObjectURL(htmlUrl);
      setHtmlUrl(null);
    }
  };

  const revokeImageUrl = () => {
    if (imageUrl) {
      URL.revokeObjectURL(imageUrl);
      setImageUrl(null);
    }
  };

  useEffect(
    () => (): void => {
      if (htmlUrl) {
        URL.revokeObjectURL(htmlUrl);
      }
    },
    [htmlUrl],
  );

  useEffect(
    () => (): void => {
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
    },
    [imageUrl],
  );

  const hasPreview = Boolean(htmlUrl) || Boolean(imageUrl);

  useEffect(() => {
    const url = loadCachedHtmlBlob(cachedHtmlData, htmlUrl);
    if (url) {
      setHtmlUrl(url);
    }
  }, [cachedHtmlData, htmlUrl]);

  return { htmlUrl, imageUrl, revokeHtmlUrl, revokeImageUrl, setHtmlUrl, setImageUrl, hasPreview };
}

interface GenerationDeps {
  templateVersionId: string | undefined;
  templateId: string | undefined;
  template: string | undefined;
  data: Record<string, unknown>;
  contentSchema: Record<string, unknown> | null | undefined;
  renderMethod: RenderMethod;
  datasetId: string | undefined;
  urls: ObjectUrlState;
  jsWarningHook: ReturnType<typeof useTemplateJsWarning>;
  onHtmlGenerated?: ((datasetId: string, htmlData: string) => void) | undefined;
  onHtmlCleared?: ((datasetId: string) => void) | undefined;
  setIsGenerating?: (v: boolean) => void;
  setIsGeneratingPreview?: (v: boolean) => void;
  setIsGeneratingImage?: (v: boolean) => void;
}

interface PreviewGenerationState {
  isGenerating: boolean;
  isGeneratingPreview: boolean;
  isGeneratingImage: boolean;
  error: string | null;
  clearError: () => void;
  generatePreview: () => Promise<void>;
  clearPreview: () => void;
}

/** Manages preview abort controller and cleanup effect. */
function usePreviewLifecycle(urls: ObjectUrlState): React.RefObject<AbortController | null> {
  const abortControllerRef = useRef<AbortController | null>(null);
  useEffect(
    (): (() => void) => (): void => {
      urls.revokeHtmlUrl();
      urls.revokeImageUrl();
      abortControllerRef.current?.abort();
    },
    [urls],
  );
  return abortControllerRef;
}

/** Creates the clearPreview callback that resets URLs, error, and notifies parent. */
function useClearPreview(
  urls: ObjectUrlState,
  setError: (e: string | null) => void,
  datasetId: string | undefined,
  onHtmlCleared: ((id: string) => void) | undefined,
): () => void {
  return () => {
    urls.revokeHtmlUrl();
    urls.revokeImageUrl();
    setError(null);
    if (datasetId) {
      onHtmlCleared?.(datasetId);
    }
  };
}

/** Wires React hook dependencies and delegates the async generation logic to executePreviewCallback. */
function useGeneratePreview(
  deps: GenerationDeps,
  setError: (e: string | null) => void,
): () => Promise<void> {
  const { t } = useTranslation('omakase.preview');
  const noop = (_v: boolean): void => undefined;
  const genSettersRef = useRef({
    setIsGenerating: deps.setIsGenerating ?? noop,
    setIsGeneratingPreview: deps.setIsGeneratingPreview ?? noop,
    setIsGeneratingImage: deps.setIsGeneratingImage ?? noop,
  });
  const abortControllerRef = usePreviewLifecycle(deps.urls);
  const { generateHtml, generateImage } = useDocumentOperations();
  const { formatValidationErrorSummary } = useValidationErrorFormatter();
  return () =>
    executePreviewCallback({
      templateVersionId: deps.templateVersionId,
      templateId: deps.templateId,
      template: deps.template,
      data: deps.data,
      contentSchema: deps.contentSchema,
      renderMethod: deps.renderMethod,
      datasetId: deps.datasetId,
      urls: deps.urls,
      jsWarningHook: deps.jsWarningHook,
      onHtmlGenerated: deps.onHtmlGenerated,
      t,
      genSetters: genSettersRef.current,
      abortControllerRef,
      formatValidationErrorSummary,
      generateHtml,
      generateImage,
      setError,
    });
}

/** Manages preview generation lifecycle including HTML/image rendering, errors, and abort. */
function usePreviewGeneration(deps: GenerationDeps): PreviewGenerationState {
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isGeneratingPreview, setIsGeneratingPreview] = useState(false);
  const [isGeneratingImage, setIsGeneratingImage] = useState(false);
  const fullDeps = { ...deps, setIsGenerating, setIsGeneratingPreview, setIsGeneratingImage };
  const generatePreview = useGeneratePreview(fullDeps, setError);
  const clearPreview = useClearPreview(deps.urls, setError, deps.datasetId, deps.onHtmlCleared);
  return {
    isGenerating,
    isGeneratingPreview,
    isGeneratingImage,
    error,
    clearError: () => setError(null),
    generatePreview,
    clearPreview,
  };
}

/** Manages PDF download with error handling. */
function usePdfDownload(
  templateVersionId: string | undefined,
  data: Record<string, unknown>,
  datasetId: string | undefined,
  setError: (err: string | null) => void,
): () => Promise<void> {
  const { t } = useTranslation('omakase.preview');
  const { downloadPdf: downloadPdfOp } = useDocumentOperations();
  return async () => {
    if (!templateVersionId) {
      setError(t('errors.templateVersionRequired'));
      return;
    }
    const cleanedData = sanitizeData(data);
    const pdfFilename: string = datasetId ? `document-${datasetId}.pdf` : 'document.pdf';
    try {
      await downloadPdfOp({
        template_version_id: templateVersionId,
        data: cleanedData,
        filename: pdfFilename,
      });
    } catch (err) {
      setError(toErrorMessage(err, t('errors.pdfDownloadFailed')));
    }
  };
}

function usePreviewPane({
  template,
  templateId,
  data = {},
  datasetId,
  cachedHtmlData,
  onHtmlGenerated,
  onHtmlCleared,
}: UsePreviewPaneOptions): UsePreviewPaneReturn {
  const [renderMethod, setRenderMethod] = useState<RenderMethod>('html');
  const currentTemplate = useDocumentBuilderStore((state) => state.currentTemplate);
  const templateVersionId = currentTemplate?.id;
  const jsWarningHook = useTemplateJsWarning(templateId, (method: RenderMethod) =>
    setRenderMethod(method),
  );
  const urls = useObjectUrls(cachedHtmlData);
  const generation = usePreviewGeneration({
    templateVersionId,
    templateId,
    template,
    data,
    contentSchema: currentTemplate?.content_schema as Record<string, unknown> | null | undefined,
    renderMethod,
    datasetId,
    urls,
    jsWarningHook,
    onHtmlGenerated,
    onHtmlCleared,
  });
  const downloadPdf = usePdfDownload(templateVersionId, data, datasetId, generation.clearError);
  const jsWarning = buildJsWarning(jsWarningHook);
  return {
    htmlUrl: urls.htmlUrl,
    imageUrl: urls.imageUrl,
    isGenerating: generation.isGenerating,
    isGeneratingPreview: generation.isGeneratingPreview,
    isGeneratingImage: generation.isGeneratingImage,
    hasPreview: urls.hasPreview,
    error: generation.error,
    clearError: generation.clearError,
    generatePreview: generation.generatePreview,
    clearPreview: generation.clearPreview,
    revokeHtmlUrl: urls.revokeHtmlUrl,
    revokeImageUrl: urls.revokeImageUrl,
    downloadPdf,
    renderMethod,
    setRenderMethod,
    jsWarning,
  };
}

export type { JsWarningState } from './previewPaneHelpers.ts';
export { usePreviewPane };
