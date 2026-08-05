import { sanitizeData } from '@shared/lib/index.ts';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Dataset } from '../model/index.ts';
import { useDocumentBuilderStore } from '../model/index.ts';
import { htmlToBlobUrl, loadCachedHtmlBlob, toErrorMessage } from './previewPaneHelpers.ts';
import { useDocumentOperations } from './useDocumentOperations.ts';
import type { JsWarningState } from './usePreviewPane.ts';
import { type RenderMethod, useTemplateJsWarning } from './useTemplateJsWarning.ts';

interface UseFullscreenPreviewDialogProps {
  templateId?: string | undefined;
  datasetId?: string | undefined;
  cachedHtmlData?: string | undefined;
  onHtmlGenerated?: ((datasetId: string, htmlData: string) => void) | undefined;
  onHtmlCleared?: ((datasetId: string) => void) | undefined;
}

interface UseFullscreenPreviewDialogReturn {
  htmlUrl: string | null;
  imageUrl: string | null;
  isGenerating: boolean;
  isGeneratingPreview: boolean;
  isGeneratingImage: boolean;
  error: string | null;
  renderMethod: RenderMethod;
  setRenderMethod: (method: RenderMethod) => void;
  handleGeneratePreview: (template?: string, data?: Record<string, unknown>) => Promise<void>;
  revokeHtmlUrl: () => void;
  revokeImageUrl: () => void;
  jsWarning: JsWarningState;
}

/** Resolves preview data from explicit data, dataset, or empty default. */
function preparePreviewData(
  data: Record<string, unknown> | undefined,
  datasetId: string | undefined,
  getDataset: (id: string) => Dataset | undefined,
): Record<string, unknown> {
  const dataset = datasetId ? getDataset(datasetId) : null;
  // biome-ignore lint/suspicious/noUnnecessaryConditions: Both optional preview sources can be undefined, so the empty object fallback is reachable.
  return sanitizeData(data ?? dataset?.data ?? {});
}

/** Computes the triple generating-state flags. */
function computeGeneratingFlags(
  isActive: boolean,
  method: RenderMethod,
): { isGenerating: boolean; isGeneratingPreview: boolean; isGeneratingImage: boolean } {
  return {
    isGenerating: isActive,
    isGeneratingPreview: isActive && method === 'html',
    isGeneratingImage: isActive && method !== 'html',
  };
}

/** Maps jsWarningHook fields to the JsWarningState interface. */
function buildJsWarning(hook: ReturnType<typeof useTemplateJsWarning>): JsWarningState {
  return {
    showWarning: hook.showWarning,
    templateName: hook.templateName,
    templateVersion: hook.templateVersion,
    reason: hook.reason,
    handleJsChoice: hook.handleJsChoice,
    checkJsRequirement: hook.checkJsRequirement,
  };
}

interface ObjectUrls {
  htmlUrl: string | null;
  imageUrl: string | null;
  revokeHtmlUrl: () => void;
  revokeImageUrl: () => void;
  setHtmlUrl: (url: string | null) => void;
  setImageUrl: (url: string | null) => void;
}

/** Manages HTML and image blob URLs with revocation and cleanup. */
function useObjectUrls(cachedHtmlData: string | undefined): ObjectUrls {
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
    (): (() => void) => (): void => {
      revokeHtmlUrl();
      revokeImageUrl();
    },
    // biome-ignore lint/correctness/useExhaustiveDependencies: React Compiler auto-memoizes these closures
    [revokeHtmlUrl, revokeImageUrl],
  );

  useEffect(() => {
    const url = loadCachedHtmlBlob(cachedHtmlData, htmlUrl);
    if (url) {
      setHtmlUrl(url);
    }
  }, [cachedHtmlData, htmlUrl]);

  return { htmlUrl, imageUrl, revokeHtmlUrl, revokeImageUrl, setHtmlUrl, setImageUrl };
}

interface GenerationParams {
  tvId: string;
  cleanedData: Record<string, unknown>;
  method: RenderMethod;
  ops: ReturnType<typeof useDocumentOperations>;
  urls: ObjectUrls;
  onHtmlGenerated: ((datasetId: string, htmlData: string) => void) | undefined;
  currentDatasetId?: string;
}

/** Generates preview content and updates blob URLs. Pure async - no React hooks. */
async function executeGeneration(params: GenerationParams): Promise<void> {
  const { tvId, cleanedData, method, ops, urls, onHtmlGenerated, currentDatasetId } = params;
  if (method === 'html') {
    const htmlContent = await ops.generateHtml({ template_version_id: tvId, data: cleanedData });
    urls.revokeHtmlUrl();
    urls.revokeImageUrl();
    urls.setHtmlUrl(htmlToBlobUrl(htmlContent));
    if (onHtmlGenerated && currentDatasetId) {
      onHtmlGenerated(currentDatasetId, htmlContent);
    }
  } else {
    const newImageUrl = await ops.generateImage({ template_version_id: tvId, data: cleanedData });
    urls.revokeImageUrl();
    urls.revokeHtmlUrl();
    urls.setImageUrl(newImageUrl);
  }
}

interface PreviewGenerationDeps {
  templateVersionId: string | undefined;
  templateId: string | undefined;
  datasetId: string | undefined;
  renderMethod: RenderMethod;
  onHtmlGenerated: ((datasetId: string, htmlData: string) => void) | undefined;
  urls: ObjectUrls;
  jsWarningHook: ReturnType<typeof useTemplateJsWarning>;
  getDataset: (id: string) => Dataset | undefined;
}

interface PreviewGenerationState {
  generatingFlags: ReturnType<typeof computeGeneratingFlags>;
  error: string | null;
  handleGeneratePreview: (template?: string, data?: Record<string, unknown>) => Promise<void>;
}

/** Manages preview generation lifecycle: abort control, flags, and error state. */
function usePreviewGeneration(deps: PreviewGenerationDeps): PreviewGenerationState {
  const { t } = useTranslation('omakase.preview');
  const [generatingFlags, setFlags] = useState(computeGeneratingFlags(false, 'html'));
  const [error, setError] = useState<string | null>(null);
  const acRef = useRef<AbortController | null>(null);
  const ops = useDocumentOperations();

  const handleGeneratePreview = async (template?: string, data?: Record<string, unknown>) => {
    if (!deps.templateVersionId) {
      setError(t('errors.templateVersionRequired'));
      return;
    }
    if (deps.jsWarningHook.checkJsRequirement(deps.templateId, template)) {
      return;
    }
    const cleanedData = preparePreviewData(data, deps.datasetId, deps.getDataset);
    acRef.current?.abort();
    const ac = new AbortController();
    acRef.current = ac;
    setFlags(computeGeneratingFlags(true, deps.renderMethod));
    setError(null);
    try {
      await executeGeneration({
        tvId: deps.templateVersionId,
        cleanedData,
        method: deps.renderMethod,
        ops,
        urls: deps.urls,
        onHtmlGenerated: deps.onHtmlGenerated,
        currentDatasetId: deps.datasetId,
      });
    } catch (err) {
      if (!ac.signal.aborted) {
        setError(toErrorMessage(err, t('errors.generationFailed')));
      }
    } finally {
      if (!ac.signal.aborted) {
        setFlags(computeGeneratingFlags(false, deps.renderMethod));
      }
      acRef.current = null;
    }
  };

  return { generatingFlags, error, handleGeneratePreview };
}

export function useFullscreenPreviewDialog({
  templateId,
  datasetId,
  cachedHtmlData,
  onHtmlGenerated,
  onHtmlCleared: _onHtmlCleared,
}: UseFullscreenPreviewDialogProps): UseFullscreenPreviewDialogReturn {
  const [renderMethod, setRenderMethod] = useState<RenderMethod>('html');
  const currentTemplate = useDocumentBuilderStore((state) => state.currentTemplate);
  const getDataset = useDocumentBuilderStore((state) => state.getDataset);

  const handleRenderChoice = (method: RenderMethod) => {
    setRenderMethod(method);
  };

  const jsWarningHook = useTemplateJsWarning(templateId, handleRenderChoice);
  const urls = useObjectUrls(cachedHtmlData);

  const { generatingFlags, error, handleGeneratePreview } = usePreviewGeneration({
    templateVersionId: currentTemplate?.id,
    templateId,
    datasetId,
    renderMethod,
    onHtmlGenerated,
    urls,
    jsWarningHook,
    getDataset,
  });

  const jsWarning = buildJsWarning(jsWarningHook);

  return {
    htmlUrl: urls.htmlUrl,
    imageUrl: urls.imageUrl,
    isGenerating: generatingFlags.isGenerating,
    isGeneratingPreview: generatingFlags.isGeneratingPreview,
    isGeneratingImage: generatingFlags.isGeneratingImage,
    error,
    renderMethod,
    setRenderMethod,
    handleGeneratePreview,
    revokeHtmlUrl: urls.revokeHtmlUrl,
    revokeImageUrl: urls.revokeImageUrl,
    jsWarning,
  };
}
