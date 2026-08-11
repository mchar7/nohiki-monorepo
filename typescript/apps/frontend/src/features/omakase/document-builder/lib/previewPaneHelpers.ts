import { sanitizeData } from '@shared/lib/index.ts';
import { jsonSchemaToZod } from '@shared/lib/services/index.ts';
import type { ZodError } from 'zod';
import { asJSONSchemaDefinition } from '@/shared/lib';
import type {
  GeneratingSetters,
  GenerationParams,
  JsWarningState,
  ObjectUrlState,
  PreviewCallbackParams,
  UsePreviewPaneOptions,
  UsePreviewPaneReturn,
} from './previewPaneHelpers.types.ts';
import type { RenderMethod, UseTemplateJsWarningReturn } from './useTemplateJsWarning.ts';

/** Validates data against a JSON schema, returning validity and optional error. */
function validateDataWithSchema(
  cleanedData: Record<string, unknown>,
  contentSchema: Record<string, unknown> | null | undefined,
  formatErrorSummary: (error: ZodError) => string,
): { isValid: boolean; error?: string } {
  if (!contentSchema) {
    return { isValid: true };
  }
  // Validate that the schema satisfies JSONSchemaDefinition's minimum shape
  // before passing it to jsonSchemaToZod, which assumes a well-formed schema.
  // Malformed schemas are treated as "no validation"; the surrounding try/catch
  // also keeps unexpected jsonSchemaToZod errors from breaking preview.
  const validated = asJSONSchemaDefinition(contentSchema);
  if (validated === null) {
    return { isValid: true };
  }
  try {
    const zodSchema = jsonSchemaToZod(validated);
    const result = zodSchema.safeParse(cleanedData);
    if (!result.success) {
      return { isValid: false, error: formatErrorSummary(result.error) };
    }
    return { isValid: true };
  } catch {
    return { isValid: true };
  }
}

/** Loads cached HTML string into a blob URL if available. */
function loadCachedHtmlBlob(
  cachedHtmlData: string | undefined,
  htmlUrl: string | null,
): string | null {
  if (!cachedHtmlData || htmlUrl) {
    return null;
  }
  try {
    const blob = new Blob([cachedHtmlData], { type: 'text/html' });
    return URL.createObjectURL(blob);
  } catch {
    return null;
  }
}

/** Extracts a user-facing error from an unknown thrown value. */
function toErrorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

/** Creates a blob URL from HTML content. */
function htmlToBlobUrl(htmlContent: string): string {
  const blob = new Blob([htmlContent], { type: 'text/html' });
  return URL.createObjectURL(blob);
}

/** Sets the generating state flags to active or inactive. */
function setGeneratingFlags(
  setters: GeneratingSetters,
  isActive: boolean,
  method: RenderMethod,
): void {
  setters.setIsGenerating(isActive);
  setters.setIsGeneratingPreview(isActive && method === 'html');
  setters.setIsGeneratingImage(isActive && method !== 'html');
}

/** Builds a JsWarningState from the raw hook return. */
function buildJsWarning(hook: UseTemplateJsWarningReturn): JsWarningState {
  return {
    showWarning: hook.showWarning,
    templateName: hook.templateName,
    templateVersion: hook.templateVersion,
    reason: hook.reason,
    handleJsChoice: hook.handleJsChoice,
    checkJsRequirement: hook.checkJsRequirement,
  };
}

/** Generates preview content (HTML or image) and updates blob URLs. */
async function executeGeneration(params: GenerationParams): Promise<void> {
  const { tvId, cleanedData, method, urls, onHtmlGenerated, currentDatasetId } = params;
  if (method === 'html') {
    const htmlContent = await params.generateHtml({ template_version_id: tvId, data: cleanedData });
    urls.revokeHtmlUrl();
    urls.revokeImageUrl();
    urls.setHtmlUrl(htmlToBlobUrl(htmlContent));
    if (onHtmlGenerated && currentDatasetId) {
      onHtmlGenerated(currentDatasetId, htmlContent);
    }
  } else {
    const newImageUrl = await params.generateImage({
      template_version_id: tvId,
      data: cleanedData,
    });
    urls.revokeImageUrl();
    urls.revokeHtmlUrl();
    urls.setImageUrl(newImageUrl);
  }
}

interface AbortGuardedParams {
  genSetters: GeneratingSetters;
  renderMethod: RenderMethod;
  generationParams: GenerationParams;
  onError: (msg: string) => void;
  fallbackError: string;
}

/** Runs generation within an AbortController, managing flags and error state. */
async function runAbortGuardedGeneration(
  ac: AbortController,
  params: AbortGuardedParams,
): Promise<void> {
  try {
    await executeGeneration(params.generationParams);
  } catch (err) {
    if (!ac.signal.aborted) {
      params.onError(toErrorMessage(err, params.fallbackError));
    }
  } finally {
    if (!ac.signal.aborted) {
      setGeneratingFlags(params.genSetters, false, params.renderMethod);
    }
  }
}

/** Parameters passed to executePreviewCallback; isolates hook wiring from async logic. */
/**
 * Executes the full preview generation flow: validates, sanitizes data, manages abort
 * controller lifecycle, and delegates to runAbortGuardedGeneration.
 * Pure async function - no React hooks - extracted so useGeneratePreview stays concise.
 */
async function executePreviewCallback({
  templateVersionId,
  templateId,
  template,
  data,
  contentSchema,
  renderMethod,
  datasetId,
  urls,
  jsWarningHook,
  onHtmlGenerated,
  t,
  genSetters,
  abortControllerRef,
  formatValidationErrorSummary,
  generateHtml,
  generateImage,
  setError,
}: PreviewCallbackParams): Promise<void> {
  if (!templateVersionId) {
    setError(t('errors.templateVersionRequired'));
    return;
  }
  if (jsWarningHook.checkJsRequirement(templateId, template)) {
    return;
  }
  const cleanedData = sanitizeData(data);
  const validation = validateDataWithSchema(
    cleanedData,
    contentSchema,
    formatValidationErrorSummary,
  );
  if (!validation.isValid) {
    setError(
      validation.error !== undefined && validation.error.length > 0
        ? validation.error
        : t('errors.dataValidationFailed'),
    );
    return;
  }
  const ac = new AbortController();
  abortControllerRef.current = ac;
  setGeneratingFlags(genSetters, true, renderMethod);
  setError(null);
  await runAbortGuardedGeneration(ac, {
    genSetters,
    renderMethod,
    onError: setError,
    fallbackError: t('errors.generationFailed'),
    generationParams: {
      tvId: templateVersionId,
      cleanedData,
      method: renderMethod,
      generateHtml,
      generateImage,
      urls,
      onHtmlGenerated,
      currentDatasetId: datasetId,
    },
  });
  abortControllerRef.current = null;
}

export type { JsWarningState, ObjectUrlState, UsePreviewPaneOptions, UsePreviewPaneReturn };
export {
  buildJsWarning,
  executePreviewCallback,
  htmlToBlobUrl,
  loadCachedHtmlBlob,
  toErrorMessage,
};
